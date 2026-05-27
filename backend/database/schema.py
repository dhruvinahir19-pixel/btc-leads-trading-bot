"""
schema.py - Database schema definitions for the trading bot.
Tables: config, trades, processed_candles, weekly_scan, logs
"""
import sqlite3
from pathlib import Path

CREATE_CONFIG_TABLE = """
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

CREATE_TRADES_TABLE = """
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_time    TEXT NOT NULL,           -- IST time of BTC trigger (YYYY-MM-DD HH:MM:SS)
    coin            TEXT NOT NULL,           -- e.g., FARTCOINUSDT
    side            TEXT NOT NULL CHECK(side IN ('LONG', 'SHORT')),
    btc_return_pct  REAL NOT NULL,           -- BTC return % that triggered
    entry_price     REAL NOT NULL,
    tp_price        REAL NOT NULL,
    sl_price        REAL NOT NULL,
    position_size   REAL NOT NULL,           -- in USDT
    status          TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'closed', 'cancelled')),
    
    -- Exit details
    exit_price      REAL,
    exit_time       TEXT,                    -- IST time
    pnl_usdt        REAL,                    -- in USDT
    pnl_pct         REAL,                    -- in % (positive = gain)
    exit_reason     TEXT CHECK(exit_reason IN ('tp_hit', 'sl_hit', 'timeout', 'manual', 'error', NULL)),
    
    -- Metadata
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_TRADES_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_trades_status   ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_trigger  ON trades(trigger_time);
CREATE INDEX IF NOT EXISTS idx_trades_coin     ON trades(coin);
"""

CREATE_PROCESSED_CANDLES_TABLE = """
CREATE TABLE IF NOT EXISTS processed_candles (
    coin        TEXT NOT NULL,
    timestamp   TEXT NOT NULL,               -- Candle close time in IST (YYYY-MM-DD HH:MM:SS)
    processed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (coin, timestamp)
);
"""

CREATE_WEEKLY_SCAN_TABLE = """
CREATE TABLE IF NOT EXISTS weekly_scan (
    week_start  TEXT PRIMARY KEY,            -- Monday of the week (YYYY-MM-DD)
    scan_time   TEXT NOT NULL,               -- When scan ran (IST)
    num_scanned INTEGER NOT NULL DEFAULT 0,  -- Number of coins scanned
    num_liquid  INTEGER NOT NULL DEFAULT 0,  -- Number of liquid coins found
    results     TEXT NOT NULL,               -- Full JSON: list of {symbol, correlation, beta, volume, align_rate}
    top_coins   TEXT NOT NULL                -- JSON: list of top coin symbols
);
"""

CREATE_LOGS_TABLE = """
CREATE TABLE IF NOT EXISTS logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    level       TEXT NOT NULL CHECK(level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    module      TEXT NOT NULL,
    message     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_LOGS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at);
"""

CREATE_PNL_SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS pnl_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,               -- IST timestamp (YYYY-MM-DD HH:MM:SS)
    total_pnl   REAL NOT NULL,               -- Cumulative total PnL
    today_pnl   REAL NOT NULL DEFAULT 0,     -- Today's PnL
    total_trades INTEGER NOT NULL DEFAULT 0, -- Total trades so far
    in_trade    INTEGER NOT NULL DEFAULT 0   -- 1 if in trade, 0 otherwise
);
"""

CREATE_PNL_SNAPSHOTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_pnl_snapshots_ts ON pnl_snapshots(timestamp);
"""

# ─── Schema version for future migrations ───────────────────
SCHEMA_VERSION = 2

# ─── All statements in order ─────────────────────────────────
ALL_STATEMENTS = [
    CREATE_CONFIG_TABLE,
    CREATE_TRADES_TABLE,
    *CREATE_TRADES_INDEXES.strip().split("\n"),
    CREATE_PROCESSED_CANDLES_TABLE,
    CREATE_WEEKLY_SCAN_TABLE,
    CREATE_LOGS_TABLE,
    *CREATE_LOGS_INDEX.strip().split("\n"),
    CREATE_PNL_SNAPSHOTS_TABLE,
    *CREATE_PNL_SNAPSHOTS_INDEX.strip().split("\n"),
]


def create_all_tables(conn: sqlite3.Connection):
    """Execute all CREATE TABLE statements on the given connection."""
    for stmt in ALL_STATEMENTS:
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    
    # Set schema version
    conn.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION))
    )
    conn.commit()


def get_table_info(conn: sqlite3.Connection) -> dict:
    """Return dict of table_name -> list of column names for verification."""
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {}
    for row in cursor.fetchall():
        table_name = row[0]
        col_cursor = conn.execute(f"PRAGMA table_info({table_name})")
        tables[table_name] = [col[1] for col in col_cursor.fetchall()]
    return tables
