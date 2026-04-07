import asyncio
import asyncpg
import structlog
from config import settings

logger = structlog.get_logger()

class MetricsCollector:
    def __init__(self, queue: asyncio.Queue):
        self.queue = queue
        self.pool = None
        self._task = None

    async def start(self):
        self.pool = await asyncpg.create_pool(settings.POSTGRES_URL)
        self._task = asyncio.create_task(self._worker())
        logger.info("Metrics collector started")

    async def _worker(self):
        while True:
            try:
                event = await self.queue.get()
                event_type = event.get("type")
                
                if event_type == "order_placed":
                    await self._insert_order(event)
                elif event_type == "order_cancelled":
                    await self._update_order_cancel(event)
                elif event_type == "fill":
                    await self._insert_fill(event)
                elif event_type == "position_snapshot":
                    await self._insert_snapshot(event)
                else:
                    logger.warning("Unknown metric event type", event_type=event_type)
                    
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in metric worker", error=str(e), exc_info=True)
                await asyncio.sleep(1)

    async def _insert_order(self, data: dict):
        query = """
            INSERT INTO orders (order_id, symbol, side, price, size, status, 
                binance_mid_at_placement, hl_mid_at_placement, ewma_spread_at_placement)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, str(data["order_id"]), data["symbol"], data["side"], 
                               float(data["price"]), float(data["size"]), data["status"],
                               data.get("binance_mid"), data.get("hl_mid"), data.get("ewma_spread"))

    async def _update_order_cancel(self, data: dict):
        query = """
            UPDATE orders 
            SET status = 'cancelled', cancelled_at = CURRENT_TIMESTAMP, tick_to_trade_ns = $2
            WHERE order_id = $1
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, str(data["order_id"]), data.get("tick_to_trade_ns"))

    async def _insert_fill(self, data: dict):
        query = """
            INSERT INTO fills (order_id, symbol, side, price, size, fee, 
                binance_microprice_at_fill, hl_microprice_at_fill)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, str(data["order_id"]), data["symbol"], data["side"],
                               float(data["price"]), float(data["size"]), data.get("fee", 0.0),
                               data.get("binance_microprice"), data.get("hl_microprice"))

    async def _insert_snapshot(self, data: dict):
        query = """
            INSERT INTO position_snapshots (symbol, position_size, unrealized_pnl, realized_pnl)
            VALUES ($1, $2, $3, $4)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, data["symbol"], float(data["position_size"]), 
                               float(data["unrealized_pnl"]), float(data["realized_pnl"]))

    async def wait_closed(self):
        if self._task:
            self._task.cancel()
        if self.pool:
            await self.pool.close()
