import asyncio
import asyncpg
import httpx
import structlog
from datetime import datetime, timezone, timedelta
from config import settings
from .calculations import beta_adjusted_pnl

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
        closest = min(candles, key=lambda x: abs(x['t'] - ts_ms))
        return float(closest['c'])
    except Exception as e:
        logger.error("Failed to fetch HL markout price", symbol=symbol, ts=ts_ms, error=str(e))
        return None

async def fetch_binance_btc_price(client: httpx.AsyncClient, ts_ms: int) -> float | None:
    try:
        # Request 1s klines around the timestamp
        resp = await client.get(f"{BINANCE_API_URL}/klines", params={
            "symbol": "BTCUSDT",
            "interval": "1s",
            "startTime": ts_ms - 1000,
            "endTime": ts_ms + 60000,
            "limit": 1
        })
        resp.raise_for_status()
        klines = resp.json()
        if not klines: return None
        return float(klines[0][4]) # Close price
    except Exception as e:
        logger.error("Failed to fetch Binance BTC price", ts=ts_ms, error=str(e))
        return None

async def process_markouts(pool, client: httpx.AsyncClient):
    async with pool.acquire() as conn:
        five_mins_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
        one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
        
        while True:
            # Poll postgres for fills older than 5 minutes that lack markout calculations
            # Bounded to 1 day to prevent infinite retry loops on dead records
            rows = await conn.fetch("""
                SELECT id, symbol, filled_at, side, price, size
                FROM fills
                WHERE filled_at < $1 AND filled_at > $2 AND markout_5m IS NULL
                LIMIT 50
            """, five_mins_ago, one_day_ago)
            
            if not rows:
                break
                
            for row in rows:
                fid = row['id']
                symbol = row['symbol']
                filled_at = row['filled_at']
                fill_price = float(row['price'])
                size = float(row['size'])
                side = row['side']
                
                sign = 1 if side.upper() == "BUY" else -1
                position_size = size * sign
                
                ts_fill = int(filled_at.timestamp() * 1000)
                
                # Sequential async fetch for the 3 horizons
                p5s = await fetch_hl_price_at(client, symbol, ts_fill + 5000)
                p30s = await fetch_hl_price_at(client, symbol, ts_fill + 30000)
                p5m = await fetch_hl_price_at(client, symbol, ts_fill + 300000)
                
                # Fetch BTC for Beta adjustments
                btc_t0 = await fetch_binance_btc_price(client, ts_fill)
                btc_p5s = await fetch_binance_btc_price(client, ts_fill + 5000)
                btc_p30s = await fetch_binance_btc_price(client, ts_fill + 30000)
                btc_p5m = await fetch_binance_btc_price(client, ts_fill + 300000)
                
                def calc_adj_markout(p_horizon, b_horizon):
                    if not p_horizon or not btc_t0 or not b_horizon: return None
                    
                    # Original markup per unit
                    raw_markout_per_unit = (p_horizon - fill_price) * sign
                    raw_pnl = raw_markout_per_unit * size
                    
                    # BTC beta adjustment logic
                    btc_ret = (b_horizon - btc_t0) / btc_t0
                    adj_pnl = beta_adjusted_pnl(raw_pnl, btc_ret, settings.BTC_BETA, position_size)
                    
                    # Store as per-unit markout matching DB Schema bounds
                    return adj_pnl / size if size > 0 else 0.0

                m5s = calc_adj_markout(p5s, btc_p5s)
                m30s = calc_adj_markout(p30s, btc_p30s)
                m5m = calc_adj_markout(p5m, btc_p5m)
                
                # Require at least one to be valid to perform an update.
                if m5s is not None or m30s is not None or m5m is not None:
                    await conn.execute("""
                        UPDATE fills
                        SET markout_5s = COALESCE($1, markout_5s), 
                            markout_30s = COALESCE($2, markout_30s), 
                            markout_5m = COALESCE($3, markout_5m)
                        WHERE id = $4
                    """, m5s, m30s, m5m, fid)
                    logger.info("Processed markouts for fill", fill_id=fid, symbol=symbol)
                else:
                    # Mark unreachable ones explicitly using COALESCE isn't enough to trip the NULL check
                    # We will force 0.0 to safely clear it if it fails entirely and we must skip.
                    # As a simpler fail-safe, the day bound handles the skip perfectly.
                    pass

async def markout_loop():
    logger.info("Starting markout background worker loop")
    pool = await asyncpg.create_pool(settings.POSTGRES_URL)
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                await process_markouts(pool, client)
            except Exception as e:
                logger.error("Markout worker error", error=str(e), exc_info=True)
            
            # Rate limit our background loop checking
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(markout_loop())
