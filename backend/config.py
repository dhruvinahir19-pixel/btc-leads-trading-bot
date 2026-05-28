"""
config.py - Central configuration manager.
Loads from .env file with sensible defaults.
All settings accessible as module-level constants.
"""
import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─── Project Paths ───────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent  # D:/GOD
ENV_FILE = BASE_DIR / ".env"


def _load_env():
    """Load .env file manually (no dependency on python-dotenv)."""
    env_path = ENV_FILE
    if not env_path.exists():
        print(f"[config] WARNING: {env_path} not found. Using system env vars.")
        return

    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes if any
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
                value = value[1:-1]
            os.environ[key] = value


# Load .env on import
_load_env()


# ─── Helper: get env with default ────────────────────────────
def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def env_float(key: str, default: float = 0.0) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def env_int(key: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, "").lower().strip()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default


# ─── Binance API Keys ────────────────────────────────────────
# Real API (read-only - for data fetching)
BINANCE_API_KEY = env("BINANCE_API_KEY")
BINANCE_API_SECRET = env("BINANCE_SECRET_KEY")  # matches .env variable name

# Demo API (for order placement)
BINANCE_DEMO_KEY = env("BINANCE_DEMO_KEY")
BINANCE_DEMO_SECRET = env("BINANCE_DEMO_SECRET")

# ─── Exchange Settings ───────────────────────────────────────
BASE_URL = "https://fapi.binance.com"  # Mainnet (for real API / data)
BASE_URL_TESTNET = "https://testnet.binancefuture.com"  # Testnet (for demo API / orders)

# ─── Strategy Parameters ─────────────────────────────────────
BTC_TRIGGER_PCT = env_float("BTC_TRIGGER_PCT", 1.0)  # 1% BTC move triggers
TP_PCT = env_float("TP_PCT", 1.0)                  # 1% take profit
SL_PCT = env_float("SL_PCT", 0.5)                  # 0.5% stop loss
WINDOW_BARS = env_int("WINDOW_BARS", 4)            # 4H window
POSITION_SIZE_USDT = env_float("POSITION_SIZE_USDT", 10.0)  # $10 per coin
MAX_COINS_PER_TRADE = env_int("MAX_COINS_PER_TRADE", 5)

# ─── Account & Risk ──────────────────────────────────────────
# Start with $1000 default. Will be overridden by actual demo balance if available.
ACCOUNT_SIZE_USDT = env_float("ACCOUNT_SIZE_USDT", 1000.0)
MAX_DAILY_LOSS_USDT = env_float("MAX_DAILY_LOSS_USDT", 60.0)  # $60 max daily loss
MAX_TRADES_PER_DAY = env_int("MAX_TRADES_PER_DAY", 10)
MAX_CONSECUTIVE_LOSSES = env_int("MAX_CONSECUTIVE_LOSSES", 5)

# ─── Timing (IST = UTC + 5:30) ──────────────────────────────
# 1H candles close at xx:30 IST on Binance Futures
CANDLE_CHECK_MINUTE = env_int("CANDLE_CHECK_MINUTE", 30)   # xx:30
CANDLE_CHECK_SECOND = env_int("CANDLE_CHECK_SECOND", 2)    # xx:30:02
IN_TRADE_CHECK_INTERVAL = env_int("IN_TRADE_CHECK_INTERVAL", 60)  # Every 60s when in trade
IN_TRADE_CHECK_OFFSET = env_int("IN_TRADE_CHECK_OFFSET", 2)  # xx:xx:02 start

# ─── Weekly Coin Scan ────────────────────────────────────────
SCAN_DAY = env_int("SCAN_DAY", 6)          # 6 = Sunday (0=Mon, 6=Sun)
SCAN_HOUR = env_int("SCAN_HOUR", 0)        # 00:00 IST Sunday
SCAN_MAX_SYMBOLS = env_int("SCAN_MAX_SYMBOLS", 645)
SCAN_DURATION_MINUTES = env_int("SCAN_DURATION_MINUTES", 60)  # 60 min for full scan (30d data w/ 2-3s rate-limit delay)

# ─── Fixed Coins (always included) ──────────────────────────
FIXED_COINS = env("FIXED_COINS", "ETHUSDT,DOGEUSDT").split(",")
TOP_DYNAMIC_COINS = env_int("TOP_DYNAMIC_COINS", 3)  # Top 3 from weekly scan

# ─── Trading Coins (combined) ───────────────────────────────
# Will be populated by weekly scan + fixed coins
TRADING_COINS = list(FIXED_COINS)  # Start with fixed coins

# ─── Alerts (Email via SMTP) ─────────────────────────────────
SMTP_EMAIL = env("SMTP_EMAIL", "")
SMTP_PASSWORD = env("SMTP_PASSWORD", "")
SMTP_TO = env("SMTP_TO", "")
SMTP_HOST = env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = env_int("SMTP_PORT", 587)

# ─── Market Hours (only trade during these) ──────────────────
TRADE_START_HOUR = env_int("TRADE_START_HOUR", 0)    # 24h format
TRADE_END_HOUR = env_int("TRADE_END_HOUR", 23)

# ─── Database ────────────────────────────────────────────────
DB_PATH = BASE_DIR / env("DB_PATH", "trading_bot.db")

# ─── Logging ─────────────────────────────────────────────────
LOG_LEVEL = env("LOG_LEVEL", "INFO")

# ─── Server ──────────────────────────────────────────────────
HOST = env("HOST", "0.0.0.0")
PORT = env_int("PORT", 8000)

# ─── Render.com Detection ───────────────────────────────────
IS_RENDER = "RENDER" in os.environ or "RENDER_EXTERNAL_URL" in os.environ
RENDER_EXTERNAL_URL = env("RENDER_EXTERNAL_URL", "")
RENDER_SERVICE_NAME = env("RENDER_SERVICE_NAME", "btc-trading-bot")


# ─── IST Timezone (UTC + 5:30) ──────────────────────────────
IST_TZ = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    """Returns the current time as an aware datetime in IST."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone(IST_TZ)


def get_ist_offset() -> float:
    """Return IST offset in hours from UTC."""
    return 5.5  # UTC + 5:30


def to_ist_timestamp(utc_timestamp_ms: int) -> str:
    """Convert UTC millisecond timestamp to IST datetime string."""
    from datetime import datetime, timezone, timedelta
    utc_dt = datetime.fromtimestamp(utc_timestamp_ms / 1000, tz=timezone.utc)
    ist_dt = utc_dt + timedelta(hours=get_ist_offset())
    return ist_dt.strftime("%Y-%m-%d %H:%M:%S")


def to_ist_hour_minute(utc_timestamp_ms: int) -> tuple:
    """Return (hour, minute) in IST for a UTC timestamp."""
    from datetime import datetime, timezone, timedelta
    utc_dt = datetime.fromtimestamp(utc_timestamp_ms / 1000, tz=timezone.utc)
    ist_dt = utc_dt + timedelta(hours=get_ist_offset())
    return ist_dt.hour, ist_dt.minute


# ─── Display Config on Import ────────────────────────────────
def show_config():
    """Print current configuration for verification."""
    print("=" * 60)
    print("  TRADING BOT CONFIGURATION")
    print("=" * 60)
    print(f"  Strategy: BTC > {BTC_TRIGGER_PCT}% -> Altcoins")
    print(f"  TP: {TP_PCT}% | SL: {SL_PCT}% | Window: {WINDOW_BARS}H")
    print(f"  Position: ${POSITION_SIZE_USDT}/coin × {MAX_COINS_PER_TRADE} coins")
    print(f"  Account: ${ACCOUNT_SIZE_USDT}")
    print(f"  Daily Loss Limit: ${MAX_DAILY_LOSS_USDT}")
    print(f"  Fixed Coins: {FIXED_COINS}")
    print(f"  Dynamic Coins: Top {TOP_DYNAMIC_COINS} (scan Sun 00:00 IST)")
    print(f"  Candle Check: xx:{CANDLE_CHECK_MINUTE:02d}:{CANDLE_CHECK_SECOND:02d} IST")
    print(f"  In-Trade Check: every {IN_TRADE_CHECK_INTERVAL}s")
    print(f"  DB Path: {DB_PATH}")
    print(f"  Demo API Key: {'[OK]' if BINANCE_DEMO_KEY else '[!!] MISSING'}")
    print(f"  Real API Key: {'[OK]' if BINANCE_API_KEY else '[!!] MISSING'}")
    print(f"  SMTP: {'[OK]' if SMTP_EMAIL else '[!!] NOT SET'}")
    print("=" * 60)
