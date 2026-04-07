import asyncio
import structlog
import random
import time
from config import settings
from .position import PositionManager
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from hyperliquid.info import Info
from eth_account.account import Account
import redis.asyncio as redis

logger = structlog.get_logger()

class ExecutionEngine:
    def __init__(self, binance_queue: asyncio.Queue, hl_queue: asyncio.Queue, 
                 metrics_queue: asyncio.Queue, fills_queue: asyncio.Queue, 
                 cb_event: asyncio.Event, redis_client: redis.Redis):
        self.binance_queue = binance_queue
        self.hl_queue = hl_queue
        self.metrics_queue = metrics_queue
        self.fills_queue = fills_queue
        self.cb_event = cb_event
        self.redis = redis_client
        
        self.position = PositionManager()
        self.ewma_spread = 0.0
        self.alpha = 2.0 / (settings.EWMA_WINDOW_SAMPLES + 1)
        self.hl_mid = None
        self.active_order_id = None
        self.active_order_price = None
        self.active_order_is_buy = None
        self.api_failures = 0
        
        account: Account = Account.from_key(settings.HL_SECRET_KEY)
        self.exchange = Exchange(account, constants.MAINNET_API_URL)
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        
    async def hl_call(self, func, *args, **kwargs):
        """Async retry wrapper for sync HL API calls"""
        max_retries = 5
        for attempt in range(max_retries):
            try:
                res = await asyncio.to_thread(func, *args, **kwargs)
                if isinstance(res, dict) and res.get("status") == "err":
                    raise Exception(res.get("response"))
                return res
            except Exception as e:
                self.api_failures += 1
                await self.redis.incr("bot:api_failures_60s")
                await self.redis.expire("bot:api_failures_60s", 60)
                
                sleep_t = (2 ** attempt) + random.uniform(0, 1)
                logger.warning("HL API retry", attempt=attempt+1, error=str(e), sleep_time=sleep_t)
                await asyncio.sleep(sleep_t)
                if attempt == max_retries - 1:
                    logger.error("HL API exhausted retries")
                    return None

    async def reconcile_state(self):
        logger.info("Reconciling internal position with HL live state...")
        user_state = await self.hl_call(self.info.user_state, settings.HL_WALLET_ADDRESS)
        if user_state is None:
            logger.error("Failed to fetch user state on startup!")
            return
            
        asset_positions = user_state.get("assetPositions", [])
        live_pos = 0.0
        for pos in asset_positions:
            if pos["position"]["coin"] == settings.SYMBOL:
                live_pos = float(pos["position"]["szi"])
        
        drift = abs(live_pos - self.position.current_position)
        if drift > 1e-4:
            logger.warning("Reconciliation drift", internal=self.position.current_position, live=live_pos)
            self.position.current_position = live_pos
            await self.metrics_queue.put({"type": "position_snapshot", "symbol": settings.SYMBOL, "position_size": live_pos, "unrealized_pnl": 0.0, "realized_pnl": 0.0})

    async def cancel_active_order(self, binance_recv_ns: int):
        if not self.active_order_id: return
        
        # Nanosecond precision tick-to-trade track
        await self.hl_call(self.exchange.cancel, settings.SYMBOL, self.active_order_id)
        
        ttt_ns = time.perf_counter_ns() - binance_recv_ns
        
        await self.metrics_queue.put({
            "type": "order_cancelled",
            "order_id": str(self.active_order_id),
            "tick_to_trade_ns": ttt_ns
        })
        logger.info("Order cancelled", order_id=self.active_order_id, ttt_ms=ttt_ns / 1_000_000)
        self.active_order_id = None
        self.active_order_price = None
        self.active_order_is_buy = None

    async def _drain_queues(self):
        while not self.hl_queue.empty():
            hl_t = self.hl_queue.get_nowait()
            self.hl_mid = hl_t["mid"]
            
        while not self.fills_queue.empty():
            fill_evt = self.fills_queue.get_nowait()
            self.position.process_fill(fill_evt)
            fill_evt["type"] = "fill"
            fill_evt["order_id"] = str(fill_evt.get("oid"))
            # Fills handled async in collector
            await self.metrics_queue.put(fill_evt)
            if self.active_order_id and str(fill_evt.get("oid")) == str(self.active_order_id):
                self.active_order_id = None # Cleared by fill
                self.active_order_price = None
                self.active_order_is_buy = None

    async def run(self):
        await self.reconcile_state()
        logger.info("Execution engine running hot loop...")
        
        while True:
            try:
                # Halt all placements if CB trips
                if self.cb_event.is_set():
                    await asyncio.sleep(1)
                    continue

                binance_evt = await self.binance_queue.get()
                b_mid = binance_evt["mid"]
                recv_ns = binance_evt["recv_time_ns"]
                
                await self._drain_queues()
                
                if self.hl_mid is None:
                    continue
                    
                cur_spread = b_mid - self.hl_mid
                if self.ewma_spread == 0.0:
                    self.ewma_spread = cur_spread
                else:
                    self.ewma_spread = (self.alpha * cur_spread) + ((1 - self.alpha) * self.ewma_spread)
                
                tgt_bytes = await self.redis.get("bot:target_position")
                target_pos = float(tgt_bytes) if tgt_bytes else 0.0
                
                child_szs = self.position.get_child_orders(target_pos)
                
                theoretical_hl_price = b_mid - self.ewma_spread
                
                if self.active_order_id:
                    cancel_needed = False
                    if not child_szs:
                        cancel_needed = True # Target reached or zeroed
                    else:
                        req_sz = child_szs[0]
                        direction_matches = (req_sz > 0) == self.active_order_is_buy
                        if not direction_matches:
                            cancel_needed = True
                        elif abs(theoretical_hl_price - self.active_order_price) > settings.SPREAD_CANCEL_THRESHOLD:
                            cancel_needed = True
                            
                    if cancel_needed:
                        await self.cancel_active_order(recv_ns)
                        
                if not self.active_order_id and child_szs:
                    req_sz = child_szs[0]
                    is_buy = req_sz > 0
                    sz_abs = abs(req_sz)
                    
                    # Rounding logic depends on tick size, assume 2 decimals for ETH price
                    px = round(theoretical_hl_price, 2)
                    
                    res = await self.hl_call(self.exchange.order, settings.SYMBOL, is_buy, sz_abs, px, {"limit": {"tif": "Gtc"}})
                    if res and res.get("status") == "ok":
                        # Attempt to parse order id safely
                        resp_data = res.get("response", {}).get("data", {})
                        statuses = resp_data.get("statuses", [])
                        if statuses and isinstance(statuses[0], dict) and "filled" in statuses[0]:
                            self.active_order_id = statuses[0]["filled"]["oid"]
                        elif statuses and isinstance(statuses[0], dict) and "resting" in statuses[0]:
                            self.active_order_id = statuses[0]["resting"]["oid"]
                            
                        self.active_order_price = px
                        self.active_order_is_buy = is_buy
                        
                        await self.metrics_queue.put({
                            "type": "order_placed",
                            "order_id": str(self.active_order_id),
                            "symbol": settings.SYMBOL,
                            "side": "BUY" if is_buy else "SELL",
                            "price": px,
                            "size": sz_abs,
                            "status": "placed",
                            "binance_mid": b_mid,
                            "hl_mid": self.hl_mid,
                            "ewma_spread": self.ewma_spread
                        })
                        
            except Exception as e:
                logger.error("Engine loop error", error=str(e), exc_info=True)
                await asyncio.sleep(1)
