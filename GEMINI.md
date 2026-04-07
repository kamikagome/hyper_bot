

**Build a Hyperliquid Market-Making Bot (Phase 1: Execution + Measurement Foundation)**

You are building a crypto trading bot on Hyperliquid in Python. The goal of this phase is not to make money — it is to build a solid execution engine with measurement infrastructure. Follow these steps precisely.

### Stack & Environment
* **Exchange SDK:** `hyperliquid-python-sdk` (Note: Since the SDK uses synchronous `requests` for REST, wrap all REST calls in `asyncio.to_thread()`. Keep websockets purely async).
* **Reference feed:** Binance WebSocket via `websockets`.
* **Async runtime:** `asyncio` (all I/O must be non-blocking. Use `asyncio.TaskGroup` for concurrent tasks).
* **State store:** Redis via `redis-py` (async client).
* **Database:** Postgres via `asyncpg`.
* **Dashboard:** NiceGUI (Must run as a completely separate process to avoid blocking the hot-path event loop).
* **Alerts:** PagerDuty Events API v2 (plain `httpx` POST).
* **Config:** `pydantic-settings` — all config from `.env`, never hardcoded.
* **Logging:** `structlog` — structured JSON to stdout and file.
* **Process manager:** `systemd` service with `Restart=always`.
* **Deployment target:** AWS Tokyo (ap-northeast-1) — latency to HL matters.
* **Python version:** 3.11+.

### Project Layout
```text
bot/
├── main.py               # bot entry point, wires engine together
├── config.py             # pydantic-settings config model
├── feed/
│   ├── binance.py        # Binance WebSocket price feed
│   └── hyperliquid.py    # HL order book / fill feed
├── execution/
│   ├── engine.py         # order placement & cancellation loop
│   └── position.py       # position manager, target tracking
├── risk/
│   └── circuit_breaker.py
├── metrics/
│   ├── collector.py      # async metric writer → Postgres
│   ├── calculations.py   # hedging slippage, IS, t2t
│   └── markout_worker.py # separate background loop for +5s, +30s, +5m markouts
├── dashboard/
│   ├── main.py           # separate entry point for NiceGUI
│   └── app.py            # dashboard layouts and components
├── alerts/
│   └── pagerduty.py
├── db/
│   └── schema.sql        # Postgres DDL
├── docker-compose.yml    # Postgres + Redis
├── .env.example
└── README.md
```

### Step 1 — Execution Engine (`execution/engine.py`)
Implement an async loop that:
* Awaits the latest Binance mid price from a shared `asyncio.Queue`.
* Reads current Hyperliquid mid from a second queue (HL feed).
* Computes a rolling EWMA of the Binance–HL spread; window configurable via `.env`.
* Places passive limit orders on Hyperliquid near the Binance mid, adjusted by the EWMA.
* Cancels resting orders immediately when the Binance mid moves beyond a configurable threshold.
* Reads a `target_position` float from a Redis key (`bot:target_position`) on every loop iteration — do not cache it.
* Wraps all HL API REST calls in `asyncio.to_thread()` and an async retry helper with exponential backoff (max 5 retries, jitter); log every retry at WARNING level.
* **Hot path rule:** No Postgres writes, no metric calculations, no dashboard interactions inside the execution loop. Enqueue events to a separate `asyncio.Queue` for async processing.

### Step 2 — Position Manager (`execution/position.py`)
* Tracks `current_position: float` by consuming the fills queue.
* Exposes `set_target(target: float)` — splits the delta into child orders respecting a `max_order_size` config value.
* On startup, reconcile internal state against live HL positions via the SDK; log and alert if mismatch > threshold.

### Step 3 — Risk & Circuit Breakers (`risk/circuit_breaker.py`)
Halt all order placement (set a shared `asyncio.Event`) and fire a PagerDuty alert when any of the following trip:
* **Max drawdown:** Unrealized + realized loss > MAX_LOSS_USD.
* **Max notional:** Abs position notional > MAX_POSITION_USD.
* **API error spike:** >10 failed HL API calls in 60s rolling window.
* **State drift:** Resting orders on exchange ≠ internal state for >30s.
Check circuit breakers every 5 seconds in a dedicated asyncio task. Resume only via dashboard toggle (not automatically).

### Step 4 — Metric Collection (`metrics/`)
Log every order event and fill to Postgres using the schema in `db/schema.sql`. All writes go through `collector.py`, which drains an `asyncio.Queue` in a background task. 
Compute these metrics:
* **Hedging slippage:** Fill price − Binance microprice at fill timestamp.
* **Implementation shortfall:** Fill price − EWMA-adjusted Binance mid at order placement time.
* **Markout:** Fill price − HL microprice at +5s, +30s, +5min. **Crucial:** Calculate this in `markout_worker.py` (a background loop) that polls Postgres for fills older than 5 minutes, fetches historical HL data, and updates the DB rows to prevent holding state in memory.
* **Tick-to-trade:** `time.perf_counter_ns()` from Binance WS message receipt → cancel order sent. (primary iteration target, log on every cancel).
* **BTC beta adjustment:** For all metrics with a time window, subtract the BTC Binance return over that window multiplied by the symbol's configured BTC beta:
    `adjusted_pnl = raw_pnl - (btc_return_in_window * config.btc_beta * position_size)`

### Step 5 — Dashboard (`dashboard/`)
NiceGUI page (Runs as a **completely separate process** started via `dashboard/main.py`, reading state only from Redis and Postgres) with:
* Live P&L, current position, open order count.
* Tick-to-trade percentile chart (rolling 1000 cancels, display p50/p95/p99 updated every 10s).
* Markout chart at each horizon (rolling 500 fills).
* Controls: set `target_position`, pause / resume, adjust EWMA window — all write to Redis.
* Circuit breaker status panel with manual reset button.

### Step 6 — Alerts (`alerts/pagerduty.py`)
Send a PagerDuty trigger event (`httpx.AsyncClient`) on:
* Any circuit breaker trip.
* Bot process restarts (check a Redis heartbeat key on startup to detect unclean shutdowns).
* Open position detected but bot is paused for > 60s.

### Tuning Targets — Definition of "Ready"
* Passive fill execution cost < 2 bps (hedging slippage + implementation shortfall, beta-adjusted).
* Markout at 30s is near zero (no consistent adverse selection).
* Tick-to-trade p99 < 5ms measured from the Tokyo server.
* Zero crashes, zero unreconciled position drift events.

### Constraints
* Starting account size: $500; max single order notional: $50 until tuning targets are met.
* Do not use CCXT or Hummingbot — use `hyperliquid-python-sdk`.
* Fees: ignore in early measurement; assume mid-tier rate, optimize later.
* All secrets via `.env` — use `pydantic-settings`; raise on startup if any are missing.

### Deliverables & Execution Rules
Due to output length limits, act as my coding partner and generate this project iteratively. Do not generate the entire codebase at once.
* **Phase A:** Output `db/schema.sql`, `docker-compose.yml`, `config.py`, `.env.example`, and the `bot.service` systemd unit file. Stop and ask if I am ready for Phase B.
* **Phase B:** Output `feed/binance.py`, `feed/hyperliquid.py`, and `alerts/pagerduty.py`. Stop and ask if I am ready for Phase C.
* **Phase C:** Output `metrics/collector.py`, `metrics/calculations.py`, and `metrics/markout_worker.py`. Stop and ask if I am ready for Phase D.
* **Phase D:** Output `execution/engine.py`, `execution/position.py`, and `risk/circuit_breaker.py`. Stop and ask if I am ready for Phase E.
* **Phase E:** Output `bot/main.py`, `dashboard/main.py`, and `dashboard/app.py`. Add a `README.md` with setup/deployment steps for AWS Tokyo.