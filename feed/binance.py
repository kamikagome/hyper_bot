import asyncio
import json
import time
import websockets
import structlog

logger = structlog.get_logger()

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"

async def binance_feed(symbol: str, price_queue: asyncio.Queue):
    """
    Connects to Binance websocket and pushes the running mid price to queue.
    The symbol is expected to be the base coin, e.g., 'ETH', which is mapped to 'ethusdt'.
    """
    stream_name = f"{symbol.lower()}usdt@bookTicker"
    url = f"{BINANCE_WS_URL}/{stream_name}"
    
    while True:
        try:
            async with websockets.connect(url) as ws:
                logger.info("Connected to Binance WS", stream=stream_name)
                async for message in ws:
                    data = json.loads(message)
                    # Expected format:
                    # {"u":400900217,"s":"ETHUSDT","b":"25.351","B":"31.21","a":"25.365","A":"40.66"}
                    if 'b' in data and 'a' in data:
                        recv_time_ns = time.perf_counter_ns()
                        
                        bid = float(data['b'])
                        ask = float(data['a'])
                        mid = (bid + ask) / 2.0
                        
                        # We use the queue to communicate state to the execution engine.
                        await price_queue.put({
                            "exchange": "binance",
                            "symbol": symbol,
                            "mid": mid,
                            "bid": bid,
                            "ask": ask,
                            "recv_time_ns": recv_time_ns
                        })
        except asyncio.CancelledError:
            logger.info("Binance feed cancelled")
            break
        except Exception as e:
            logger.error("Binance WS error", error=str(e))
            await asyncio.sleep(5)
