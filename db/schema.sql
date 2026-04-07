CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(255) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    price DECIMAL(18, 8) NOT NULL,
    size DECIMAL(18, 8) NOT NULL,
    status VARCHAR(50) NOT NULL,
    placed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    binance_mid_at_placement DECIMAL(18, 8),
    hl_mid_at_placement DECIMAL(18, 8),
    ewma_spread_at_placement DECIMAL(18, 8),
    cancelled_at TIMESTAMP WITH TIME ZONE,
    tick_to_trade_ns BIGINT
);

CREATE TABLE IF NOT EXISTS fills (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(255) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    price DECIMAL(18, 8) NOT NULL,
    size DECIMAL(18, 8) NOT NULL,
    fee DECIMAL(18, 8),
    filled_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    binance_microprice_at_fill DECIMAL(18, 8),
    hl_microprice_at_fill DECIMAL(18, 8),
    markout_5s DECIMAL(18, 8),
    markout_30s DECIMAL(18, 8),
    markout_5m DECIMAL(18, 8)
);

CREATE TABLE IF NOT EXISTS position_snapshots (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    position_size DECIMAL(18, 8) NOT NULL,
    unrealized_pnl DECIMAL(18, 8) NOT NULL,
    realized_pnl DECIMAL(18, 8) NOT NULL,
    snapshot_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
