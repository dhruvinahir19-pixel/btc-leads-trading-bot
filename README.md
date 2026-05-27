# BTC Leads Trading Bot

An algorithmic trading bot for Binance Futures that trades altcoins based on Bitcoin price movements. Monitors BTC 1H candles and enters positions on correlated altcoins when BTC moves beyond a threshold.

## How It Works

| Trigger | Action |
|---------|--------|
| **BTC moves > 1% in an hour** | Enters long/short on correlated altcoins |
| **Position hits TP (+1%)** | Sells for profit |
| **Position hits SL (-0.5%)** | Cuts losses |
| **Daily loss > $60** | Stops trading for the day |
| **Every hour at xx:30 IST** | Checks BTC candle for new signals |
| **Every 60 seconds** | Monitors open positions (TP/SL) |
| **Every 6 hours** | Sends status summary email (if configured) |
| **Weekly (Sunday)** | Correlation scan to pick best coins |

---

## Quick Start (Local)

### Prerequisites

- Python 3.11+ (3.13 recommended)
- Node.js 20+
- A Binance account with API keys

### Setup

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Build the frontend dashboard
cd frontend
npm install
npm run build
cd ..

# 3. Configure environment
cp .env.example .env
# Edit .env with your API keys (see Configuration below)

# 4. Run the bot
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000** for the dashboard.

---

## Configuration

Copy `.env.example` to `.env` and fill in your values. Key variables:

### ✅ Required

| Variable | Description | Get it from |
|----------|-------------|-------------|
| `BINANCE_API_KEY` | Real Binance API key (read-only) | [Binance API Management](https://www.binance.com/en/support/faq/how-to-create-api-keys-on-binance-360002502072) |
| `BINANCE_SECRET_KEY` | Real API secret | Same as above |
| `BINANCE_DEMO_KEY` | Demo/testnet API key | [Binance Testnet](https://testnet.binancefuture.com/) |
| `BINANCE_DEMO_SECRET` | Demo API secret | Same as above |

### ⚙️ Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `BTC_TRIGGER_PCT` | `1.0` | BTC move % to trigger entry |
| `TP_PCT` | `1.0` | Take profit % |
| `SL_PCT` | `0.5` | Stop loss % |
| `POSITION_SIZE_USDT` | `10` | $ per coin per trade |
| `MAX_COINS_PER_TRADE` | `5` | Max coins per signal |
| `MAX_DAILY_LOSS_USDT` | `60` | Daily loss limit |
| `MAX_TRADES_PER_DAY` | `10` | Daily trade limit |
| `FIXED_COINS` | `ETHUSDT,DOGEUSDT` | Coins always traded |
| `SMTP_EMAIL` | — | Gmail for email alerts |
| `SMTP_PASSWORD` | — | Gmail App Password |
| `SMTP_TO` | — | Alert recipient email |

> **SMTP Note:** Use a Gmail **App Password** (not your regular password). Enable 2FA → [App Passwords](https://myaccount.google.com/apppasswords)

---

## Deploy to Render

This bot is designed to run as a single **Render Web Service** (backend + frontend together).

### 1. Push to GitHub

```bash
# If you haven't already:
git init
git add .
git commit -m "Initial commit"

# Create repo on GitHub and push
gh repo create btc-leads-trading-bot --public --push --source=.
```

### 2. Create Web Service on Render

1. Go to [Render Dashboard](https://dashboard.render.com/) → **New** → **Web Service**
2. Connect your GitHub repo (`dhruvinahir19-pixel/btc-leads-trading-bot`)
3. Configure:

| Setting | Value |
|---------|-------|
| **Name** | `btc-leads-trading-bot` |
| **Runtime** | Python (Render reads `runtime.txt`) |
| **Build Command** | `chmod +x render-build.sh && ./render-build.sh` |
| **Start Command** | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT --log-level \${LOG_LEVEL:-info}` |
| **Plan** | Starter (or higher for production) |

### 3. Set Environment Variables

In Render dashboard → **Environment** → add all variables from `.env.example`:

| Variable | Notes |
|----------|-------|
| `BINANCE_API_KEY` | Your real API key (read-only) |
| `BINANCE_SECRET_KEY` | Your real API secret |
| `BINANCE_DEMO_KEY` | Your demo API key |
| `BINANCE_DEMO_SECRET` | Your demo API secret |
| `SMTP_EMAIL` | (optional) |
| `SMTP_PASSWORD` | (optional) |
| `SMTP_TO` | (optional) |
| `RENDER_EXTERNAL_URL` | Set automatically by Render (don't add manually) |

> **Render automatically sets:** `PORT` (to 10000), `RENDER`, and `RENDER_EXTERNAL_URL`.

### 4. Deploy

Click **Create Web Service**. Render will:
1. Read `runtime.txt` → install Python 3.13.2
2. Run `render-build.sh` → install Python deps + build React frontend
3. Start the bot with `uvicorn ...`

Your bot is live at `https://btc-leads-trading-bot.onrender.com` ✨

### 5. Persistent Storage (Render Disk)

The bot uses **SQLite** (`DB_PATH=trading_bot.db`) to store all trade history, PnL data, and state. On Render's free tier, the filesystem is **ephemeral** — all data is lost every time the service restarts (which happens after 15 min of inactivity).

**To keep your data between restarts:**
1. Go to Render Dashboard → your Web Service → **Disks**
2. Add a **Render Disk** (Starter plan required, ~$2/month):
   - Name: `data`
   - Mount Path: `/data`
   - Size: 1 GB (more than enough)
3. Set environment variable: `DB_PATH=/data/trading_bot.db`

> **Important:** Without a Render Disk, all trade history and PnL data resets after every restart.

### 6. Keep Free Tier Alive

Render free tier spins down after inactivity (15 min). Use **UptimeRobot** (free) to ping your `/health` endpoint every 5 minutes:

```
https://btc-leads-trading-bot.onrender.com/health
```

> **Note:** Even with UptimeRobot, Render's free tier has 750 hours/month uptime limit. For 24/7 trading, upgrade to the **Starter** plan ($7/month) which never spins down.

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check (for uptime monitoring) |
| `GET /api/status` | Full bot status |
| `GET /api/stats` | Trading statistics |
| `GET /api/trades?limit=50` | Recent trades |
| `GET /api/config` | Current configuration |
| `GET /api/equity-curve` | PnL history for charts |
| `GET /api/pnl-breakdown` | Daily PnL by coin |
| `GET /api/logs?limit=50` | Recent logs |
| `POST /api/scan` | Trigger weekly scan manually |
| `POST /api/test-email` | Test SMTP configuration |
| `POST /api/status-email` | Send status summary email |

---

## Running Tests

```bash
# Run all tests
pytest tests/ -q --tb=no

# Run with detailed output
pytest tests/ -v --tb=short

# Run specific test file
pytest tests/test_config.py -v
```

---

## Project Structure

```
├── backend/
│   ├── main.py                 # FastAPI app, scheduler, API endpoints
│   ├── config.py               # Central configuration
│   ├── logging_setup.py        # Structured logging
│   ├── api/binance.py          # Binance Futures API client (real + demo)
│   ├── core/
│   │   ├── signal.py           # Signal generation (BTC candle analysis)
│   │   └── data_fetcher.py     # Market data & weekly correlation scan
│   ├── database/
│   │   ├── db.py               # SQLite database operations
│   │   └── schema.py           # Database schema
│   ├── trading/
│   │   ├── entry_manager.py    # Trade entry execution
│   │   ├── exit_manager.py     # TP/SL monitoring & exit
│   │   ├── order_manager.py    # Order placement
│   │   ├── tp_sl_manager.py    # TP/SL algo order management
│   │   ├── risk_manager.py     # Risk & trading hours
│   │   └── reconciliation.py   # State reconciliation
│   ├── state/
│   │   └── state_manager.py    # Position, risk, scan state
│   └── notifications/
│       └── email_alerts.py     # Email notifications
├── frontend/                   # React dashboard (Vite + Tailwind)
├── tests/                      # Test suite (266+ tests)
├── runtime.txt                 # Render Python version pin
├── render-build.sh             # Render build script
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variable template
├── Dockerfile                  # Docker build
└── docker-compose.yml          # Docker Compose
```

---

## Tech Stack

- **Backend:** Python 3.13 + FastAPI + APScheduler + aiosqlite
- **Frontend:** React 19 + Vite + Tailwind CSS + Recharts
- **Trading:** Binance Futures API (FAPI) + USDS-M Testnet
- **Database:** SQLite (persistent via Render Disk)
- **Deployment:** Render Web Service (or Docker)
