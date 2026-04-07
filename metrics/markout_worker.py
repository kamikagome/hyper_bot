import asyncio
import asyncpg
import httpx
import structlog
from datetime import datetime, timezone, timedelta
from config import settings

logger = structlog.get_logger()

HL_INFO_URL = "https://api.hyperliquid.xyz/info"
BINANCE_API_URL = "https://api.binance.com/api/v3"

async def fetch_hl_price_at(client: httpx.AsyncClient, symbol: str, ts_ms: int) -> float | None:
    try:
        # Request 1m candles spanning precisely the target stamp
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": symbol,
                "interval": "1m",
                "startTime": ts_ms - 60000,
                "endTime": ts_ms + 60000
            }
        }
        resp = await client.post(HL_INFO_URL, json=payload)
        resp.raise_for_status()
        candles = resp.json()
        if not candles: return None
        # Closest candle to timestamp logic
        # candles[i] = {"t": timestamp_ms, "c": close_price_string, ...}
        closest = min(candles, key=lambda x: abs(x['t'] - ts_ms))
        return float(closest['c'])
    except Exception as e:
        logger.error("Failed to fetch HL markout price", symbol=symbol, ts=ts_ms, error=str(e))
        return None

async def markout_loop():
    logger.info("Starting markout background worker loop")
    pool = await asyncpg.create_pool(settings.POSTGRES_URL)
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                async with pool.acquire() as conn:
                    # Poll postgres for fills older than 5 minutes that lack markout calculations
                    five_mins_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
                    rows = await conn.fetch("""
                        SELECT id, symbol, filled_at, side, price
                        FROM fills
                        WHERE filled_at < $1 AND markout_5m IS NULL
                        LIMIT 100
                    """, five_mins_ago)
                    
                    for row in rows:
                        fid = row['id']
                        symbol = row['symbol']
                        filled_at = row['filled_at']
                        fill_price = float(row['price'])
                        side = row['side']
                        sign = 1 if side.upper() == "BUY" else -1
                        
                        ts_fill = int(filled_at.timestamp() * 1000)
                        
                        # Sequential async fetch for the 3 horizons to avoid rate limits
                        p5s = await fetch_hl_price_at(client, symbol, ts_fill + 5000)
                        p30s = await fetch_hl_price_at(client, symbol, ts_fill + 30000)
                        p5m = await fetch_hl_price_at(client, symbol, ts_fill + 300000)
                        
                        # Markout is: (Price_horizon - Fill_price) * direction
                        m5s = ((p5s - fill_price) * sign) if p5s else None
                        m30s = ((p30s - fill_price) * sign) if p30s else None
                        m5m = ((p5m - fill_price) * sign) if p5m else None
                        
                        await conn.execute("""
                            UPDATE fills
                            SET markout_5s = $1, markout_30s = $2, markout_5m = $3
                            WHERE id = $4
                        """, m5s, m30s, m5m, fid)
                        
                        logger.info("Processed markouts for fill", fill_id=fid, symbol=symbol)
                
            except Exception as e:
                logger.error("Markout worker error", error=str(e), exc_info=True)
            
            # Rate limit our background loop checking
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(markout_loop())
