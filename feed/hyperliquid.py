import asyncio
import json
import time
import websockets
import structlog

logger = structlog.get_logger()

HL_WS_URL = "wss://api.hyperliquid.xyz/ws"

async def hl_l2_feed(symbol: str, hl_queue: asyncio.Queue):
    """
    Connects to Hyperliquid L2 book websocket to get mid price.
    """
    while True:
        try:
            async with websockets.connect(HL_WS_URL) as ws:
                logger.info("Connected to HL WS (L2)", symbol=symbol)
                
                subscribe_msg = {
                    "method": "subscribe",
                    "subscription": {"type": "l2Book", "coin": symbol}
                }
                await ws.send(json.dumps(subscribe_msg))
                
                async for message in ws:
                    data = json.loads(message)
                    if data.get("channel") == "l2Book":
                        book = data.get("data", {})
                        levels = book.get("levels", [])
                        
                        # levels[0] is bids, levels[1] is asks
                        if len(levels) == 2 and len(levels[0]) > 0 and len(levels[1]) > 0:
                            best_bid = float(levels[0][0]["px"])
                            best_ask = float(levels[1][0]["px"])
                            mid = (best_bid + best_ask) / 2.0
                            
                            recv_time_ns = time.perf_counter_ns()
                            
                            await hl_queue.put({
                                "exchange": "hyperliquid",
                                "symbol": symbol,
                                "mid": mid,
                                "bid": best_bid,
                                "ask": best_ask,
                                "recv_time_ns": recv_time_ns
                            })
        except asyncio.CancelledError:
            logger.info("HL L2 feed cancelled")
            break
        except Exception as e:
            logger.error("Hyperliquid WS (L2) error", error=str(e))
            await asyncio.sleep(5)


async def hl_user_feed(user_address: str, fills_queue: asyncio.Queue):
    """
    Connects to Hyperliquid userEvents websocket to get live fills.
    """
    while True:
        try:
            async with websockets.connect(HL_WS_URL) as ws:
                logger.info("Connected to HL WS (User)", address=user_address)
                
                subscribe_msg = {
                    "method": "subscribe",
                    "subscription": {"type": "userEvents", "user": user_address}
                }
                await ws.send(json.dumps(subscribe_msg))
                
                async for message in ws:
                    data = json.loads(message)
                    if data.get("channel") == "user":
                        event_data = data.get("data", {})
                        fills = event_data.get("fills", [])
                        for fill in fills:
                            await fills_queue.put(fill)
        except asyncio.CancelledError:
            logger.info("HL user feed cancelled")
            break
        except Exception as e:
            logger.error("Hyperliquid WS (User) error", error=str(e))
            await asyncio.sleep(5)
