import asyncio
import structlog
import redis.asyncio as redis
from config import settings
from alerts.pagerduty import trigger_incident
from hyperliquid.utils import constants
from hyperliquid.info import Info
from eth_account.account import Account

logger = structlog.get_logger()

class CircuitBreaker:
    def __init__(self, cb_event: asyncio.Event, redis_client: redis.Redis, position_manager):
        self.cb_event = cb_event
        self.redis = redis_client
        self.position = position_manager
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        acc = Account.from_key(settings.HL_SECRET_KEY)
        self.wallet_address = acc.address

    async def trip(self, reason: str, details: dict):
        logger.critical("CIRCUIT BREAKER TRIPPED!", reason=reason, details=details)
        self.cb_event.set()
        await self.redis.set("bot:paused", "true")
        await trigger_incident(
            summary=f"Circuit Breaker: {reason}",
            custom_details=details
        )
        
    async def _check_max_loss(self):
        try:
            user_state = await asyncio.to_thread(self.info.user_state, self.wallet_address)
            m_value = float(user_state.get("marginSummary", {}).get("accountValue", 0.0))
            # Rough logic mapping for PNL. HL doesn't strictly provide raw PNL vs starting unless cached natively.
            # Assuming we cache start value via a redis key on initial start.
            start_val_b = await self.redis.get("bot:start_margin")
            if not start_val_b:
                await self.redis.set("bot:start_margin", m_value)
                return
            
            start_val = float(start_val_b)
            pnl = m_value - start_val
            
            if pnl < -settings.MAX_LOSS_USD:
                await self.trip("Max Drawdown Exceeded", {"pnl": pnl, "limit": -settings.MAX_LOSS_USD})
                
        except Exception as e:
            logger.error("CB: failed to verify max loss", error=str(e))

    async def _check_api_spike(self):
        fails_b = await self.redis.get("bot:api_failures_60s")
        if fails_b and int(fails_b) > 10:
            await self.trip("API Error Spike", {"fails_last_60s": int(fails_b)})
            
    async def _check_max_notional(self):
        # We need the current price to compute notional size correctly.
        # Assuming position checks are fine internally.
        sz = abs(self.position.current_position)
        # simplistic bounding for now (Size * rough price limit)
        # Using margin summary is better.
        try:
            user_state = await asyncio.to_thread(self.info.user_state, self.wallet_address)
            tot_pos = float(user_state.get("marginSummary", {}).get("totalPositionValue", 0.0))
            if tot_pos > settings.MAX_POSITION_USD:
                await self.trip("Max Notional Exceeded", {"notional": tot_pos, "limit": settings.MAX_POSITION_USD})
        except Exception:
            pass
            
    async def _check_paused_but_exposed(self):
        is_paused = await self.redis.get("bot:paused")
        if is_paused == b"true" and abs(self.position.current_position) > 0:
            # Note, if paused > 60s
            paused_t = await self.redis.get("bot:paused_time")
            if not paused_t:
                import time
                await self.redis.set("bot:paused_time", int(time.time()))
            else:
                import time
                if int(time.time()) - int(paused_t) > 60:
                    await self.trip("Bot paused for >60s with open position", {"position": self.position.current_position})
        else:
            await self.redis.delete("bot:paused_time")

    async def run_loop(self):
        logger.info("Circuit breaker monitor active")
        while True:
            try:
                # If already tripped, checking continues quietly but shouldn't re-trip infinitely
                if not self.cb_event.is_set():
                    await self._check_max_loss()
                    await self._check_max_notional()
                    await self._check_api_spike()
                    await self._check_paused_but_exposed()
                else:
                    # Checking if manual unpause via redis
                    is_paused = await self.redis.get("bot:paused")
                    if is_paused == b"false":
                        logger.info("Circuit breaker manually reset from dashboard")
                        self.cb_event.clear()
            except Exception as e:
                logger.error("Circuit breaker error", error=str(e), exc_info=True)
            
            await asyncio.sleep(5)
