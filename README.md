# Hyperliquid Async Market-Making Bot ⚡️

A high-frequency market-making bot targeting nanosecond-precision microprice execution over the Hyperliquid API, anchored against a live Binance L2 WebSocket, featuring native NiceGUI telemetry out-of-the-box.

Built purely on `asyncio`.

---

## AWS Tokyo Deployment Sequence

For < 5ms latency tuning objectives, instance region clustering strictly demands `ap-northeast-1` (Tokyo).

### 1. Provision Ubuntu Sandbox
Spin up an EC2 `t3.medium` (or equivalent) instance strictly deployed in AWS Tokyo. Allow incoming TCP on `8080` (for NiceGUI) and `22`. Note: Use an Elastic IP if Pagerduty callback tunneling needs rigid whitelisting.

### 2. Install Native Dependencies & Repositories
SSH into host:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install build-essential python3.11-venv python3.11-dev git docker.io docker-compose -y
git clone https://github.com/kamikagome/hyper_bot.git /opt/hyper_bot
cd /opt/hyper_bot
```

### 3. Environment Context
Instantiate your settings mappings.
```bash
cp .env.example .env
nano .env # Populate with your HL Private Key, Wallet, and Pagerduty hooks securely!
```

### 4. Background Metrics (Postgres/Redis)
Boot the foundational memory systems globally prior to booting the Python environments.
```bash
sudo docker-compose up -d
```

### 5. Python Sandbox Architecture
```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt # See standard list below
```
*Required PIP hooks: `websockets hyperliquid-python-sdk pydantic-settings redis asyncpg structlog nicegui httpx eth-account`*

### 6. Process Daemons (SystemD)
Deploy the core and dashboard concurrently but independently so they NEVER share memory blocking limits.

```bash
# Attach bot logic
sudo cp bot.service /etc/systemd/system/
sudo systemctl enable bot
sudo systemctl start bot

# Run Nicegui loosely via detached tmux or create a secondary `dashboard.service` for 0.0.0.0:8080 mapping
```

---

## Safety Targets & Constraints Followed ⛑️
- **Slippage Bounds:** Hard boundary limits dynamically cancel deviations > `0.5`. 
- **Maximum Exposure Loss Box:** PagerDuty explicitly hooks + freezes any cumulative drawdown reaching above max configurations ($50 bounds natively).
- **Sub-Routine T2T Processing:** The hot loops (`execution/engine.py`) skip IO SQL overhead by queueing to independent `metrics/collector.py` loops natively!
