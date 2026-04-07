import asyncio
import structlog
import redis.asyncio as redis
from config import settings
from feed.binance import binance_feed
from feed.hyperliquid import hl_l2_feed, hl_user_feed
from execution.engine import ExecutionEngine
from risk.circuit_breaker import CircuitBreaker
from metrics.collector import MetricsCollector
from metrics.markout_worker import markout_loop

logger = structlog.get_logger()

async def async_main():
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    
    binance_q = asyncio.Queue()
    hl_l2_q = asyncio.Queue()
    metrics_q = asyncio.Queue()
    fills_q = asyncio.Queue()
    cb_event = asyncio.Event()

    engine = ExecutionEngine(
        binance_queue=binance_q,
        hl_queue=hl_l2_q,
        metrics_queue=metrics_q,
        fills_queue=fills_q,
        cb_event=cb_event,
        redis_client=redis_client
    )
    
    circuit_breaker = CircuitBreaker(
        cb_event=cb_event,
        redis_client=redis_client,
        position_manager=engine.position
    )
    
    collector = MetricsCollector(metrics_q)
    await collector.start()

    logger.info("Spawning all isolated coroutines via TaskGroup")
    try:
        async with asyncio.TaskGroup() as tg:
            # Feeds
            tg.create_task(binance_feed(settings.SYMBOL, binance_q))
            tg.create_task(hl_l2_feed(settings.SYMBOL, hl_l2_q))
            tg.create_task(hl_user_feed(settings.HL_WALLET_ADDRESS, fills_q))
            
            # Subsystems
            tg.create_task(circuit_breaker.run_loop())
            tg.create_task(engine.run())
            
            # Isolated markout cron
            tg.create_task(markout_loop())
    except Exception as e:
        logger.error("Critical TaskGroup failure. Graceful halt...", error=str(e), exc_info=True)
    finally:
        await collector.wait_closed()
        await redis_client.aclose()

if __name__ == "__main__":
    asyncio.run(async_main())
