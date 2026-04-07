# Hyperliquid Async Market-Making Bot ⚡️

A high-frequency cryptocurrency market-making bot designed for the Hyperliquid L1, anchored against Binance WebSocket price feeds. Built with a focus on low-latency execution, robust risk management, and real-time performance monitoring.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![Exchange: Hyperliquid](https://img.shields.io/badge/Exchange-Hyperliquid-orange.svg)](https://hyperliquid.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 🚀 Overview

This bot implements a passive market-making strategy on Hyperliquid. It tracks the Binance mid-price as a reference, adjusts for a rolling EWMA spread, and places limit orders to capture the spread.

### Key Features
*   **Low-Latency Execution:** Core engine built on `asyncio` with non-blocking I/O. REST calls are wrapped in `asyncio.to_thread` to prevent event-loop blocking.
*   **Asynchronous Feeds:** Pure async WebSocket connections to Binance and Hyperliquid for real-time market data.
*   **Robust Risk Management:** Multiple circuit breakers (Drawdown, Notional, API Error Spike, State Drift) with automated PagerDuty alerts.
*   **Metrics & Analytics:** Comprehensive tracking of Tick-to-Trade (T2T), Hedging Slippage, Implementation Shortfall, and Markouts (+5s, +30s, +5m) with BTC beta adjustments.
*   **Live Dashboard:** Beautiful real-time telemetry dashboard built with NiceGUI, running in a completely separate process for zero impact on the trading loop.
*   **Data Persistence:** PostgreSQL for high-fidelity trade/order logging and Redis for low-latency state sharing.

## 🛠 Tech Stack
*   **Runtime:** Python 3.11+
*   **Async framework:** `asyncio`
*   **Exchange API:** `hyperliquid-python-sdk`
*   **External Data:** Binance WebSocket (`websockets`)
*   **State Store:** Redis (`redis-py`)
*   **Database:** PostgreSQL (`asyncpg`)
*   **Telemetry:** NiceGUI
*   **Alerting:** PagerDuty Events API v2
*   **Logging:** `structlog` (Structured JSON)

## 📂 Project Layout
```text
bot/
├── main.py               # Bot entry point, orchestrates subsystems
├── config.py             # Pydantic-settings configuration
├── feed/
│   ├── binance.py        # Binance WebSocket price feed
│   └── hyperliquid.py    # HL L2 book & fill feeds
├── execution/
│   ├── engine.py         # Hot-path execution loop
│   └── position.py       # Internal position management & child-ordering
├── risk/
│   └── circuit_breaker.py# Automated safety limits & incident triggering
├── metrics/
│   ├── collector.py      # Async PostgreSQL metrics writer
│   ├── calculations.py   # Latency & slippage math
│   └── markout_worker.py # Background process for historical markouts
├── dashboard/
│   ├── main.py           # Dashboard entry point
│   └── app.py            # NiceGUI layouts & data sync
├── alerts/
│   └── pagerduty.py      # PagerDuty integration
├── db/
│   └── schema.sql        # Database schema
├── bot.service           # Systemd service unit
└── docker-compose.yml    # Postgres & Redis infrastructure
```

## 🌏 AWS Tokyo Deployment

For optimal performance (< 5ms T2T), deployment in `ap-northeast-1` (Tokyo) is highly recommended.

### 1. Host Preparation
Provision an EC2 instance (e.g., `t3.medium`) running Ubuntu in AWS Tokyo. Ensure security groups allow inbound traffic on:
*   `22` (SSH)
*   `8080` (Dashboard)

### 2. Infrastructure Setup
```bash
# Install dependencies
sudo apt update && sudo apt install -y build-essential python3.11-venv python3.11-dev git docker.io docker-compose

# Start Postgres & Redis
docker-compose up -d
```

### 3. Bot Installation
```bash
# Clone the repository
git clone https://github.com/kamikagome/hyper_bot.git
cd hyper_bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Configuration
Create a `.env` file based on `.env.example`:
```bash
cp .env.example .env
# Edit .env with your HL_SECRET_KEY, HL_WALLET_ADDRESS, and PAGERDUTY_ROUTING_KEY
```

### 5. Deployment
Use the provided `bot.service` for production-grade process management:
```bash
sudo cp bot.service /etc/systemd/system/bot.service
sudo systemctl daemon-reload
sudo systemctl enable bot
sudo systemctl start bot
```

## 📊 Monitoring

The dashboard is accessible at `http://YOUR_SERVER_IP:8080`. It provides real-time visibility into:
*   **PnL & Exposure:** Live account balance and current position size.
*   **Latency Stats:** Rolling T2T percentiles (p50, p95, p99).
*   **Execution Quality:** Average markouts across different time horizons.
*   **Controls:** Manual target adjustment, engine pause/resume, and circuit breaker resets.

## 🛡 Performance Targets
*   **Execution Cost:** < 2 bps (Beta-adjusted hedging slippage + IS).
*   **Latency:** p99 Tick-to-Trade < 5ms (from Tokyo).
*   **Stability:** 99.9% uptime with zero unreconciled drift events.

The original article: https://stalequant.com/essays/index.html#bots

---
*Disclaimer: Trading cryptocurrencies involves significant risk. This bot is provided for educational and research purposes. Use at your own risk.*
