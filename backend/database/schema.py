"""
schema.py - SQLite database schema definitions for the trading bot.
"""

import sqlite3

# ════════════════════════════════════════════════════════════════
# SQLite DDL
# ════════════════════════════════════════════════════════════════

CREATE_CONFIG_TABLE = """
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

CREATE_TRADES_TABLE = """
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_time    TEXT NOT NULL,
    coin            TEXT NOT NULL,
    side            TEXT NOT NULL CHECK(side IN ('LONG', 'SHORT')),
    btc_return_pct  REAL NOT NULL,
    entry_price     REAL NOT NULL,
    tp_price        REAL NOT NULL,
    sl_price        REAL NOT NULL,
    position_size   REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'closed', 'cancelled')),
    exit_price      REAL,
    exit_time       TEXT,
    pnl_usdt        REAL,
    pnl_pct         REAL,
    exit_reason     TEXT CHECK(exit_reason IN ('tp_hit', 'sl_hit', 'timeout', 'manual', 'error', NULL)),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_TRADES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)",
    "CREATE INDEX IF NOT EXISTS idx_trades_trigger ON trades(trigger_time)",
    "CREATE INDEX IF NOT EXISTS idx_trades_coin ON trades(coin)",
]

CREATE_PROCESSED_CANDLES_TABLE = """
CREATE TABLE IF NOT EXISTS processed_candles (
    coin        TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    processed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (coin, timestamp)
);
"""

CREATE_WEEKLY_SCAN_TABLE = """
CREATE TABLE IF NOT EXISTS weekly_scan (
    week_start  TEXT PRIMARY KEY,
    scan_time   TEXT NOT NULL,
    num_scanned INTEGER NOT NULL DEFAULT 0,
    num_liquid  INTEGER NOT NULL DEFAULT 0,
    results     TEXT NOT NULL,
    top_coins   TEXT NOT NULL
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

CREATE_LOGS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level)",
    "CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at)",
]

CREATE_PNL_SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS pnl_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL,
    total_pnl    REAL NOT NULL,
    today_pnl    REAL NOT NULL DEFAULT 0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    in_trade     INTEGER NOT NULL DEFAULT 0
);
"""

CREATE_PNL_SNAPSHOTS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_pnl_snapshots_ts ON pnl_snapshots(timestamp)",
]

ALL_STATEMENTS = [
    CREATE_CONFIG_TABLE,
    CREATE_TRADES_TABLE,
    *CREATE_TRADES_INDEXES,
    CREATE_PROCESSED_CANDLES_TABLE,
    CREATE_WEEKLY_SCAN_TABLE,
    CREATE_LOGS_TABLE,
    *CREATE_LOGS_INDEXES,
    CREATE_PNL_SNAPSHOTS_TABLE,
    *CREATE_PNL_SNAPSHOTS_INDEXES,
]

SCHEMA_VERSION = 2


def create_all_tables(conn) -> None:
    """Execute all CREATE TABLE statements on the given connection."""
    for stmt in ALL_STATEMENTS:
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    conn.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),)
    )
    conn.commit()


def get_table_info(conn) -> dict:
    """Return dict of table_name -> list of column names for verification."""
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {}
    for row in cursor.fetchall():
        table_name = row[0]
        col_cursor = conn.execute(f"PRAGMA table_info({table_name})")
        tables[table_name] = [col[1] for col in col_cursor.fetchall()]
    return tables
