"""
schema.py - Database schema definitions for the trading bot.
Supports both PostgreSQL (production on Neon.tech) and SQLite (local development/testing).
Auto-detects backend and runs the appropriate DDL.
"""
from typing import Union

# ════════════════════════════════════════════════════════════════
# PostgreSQL DDL (production — used when DATABASE_URL is set)
# ════════════════════════════════════════════════════════════════

CREATE_CONFIG_TABLE_PG = """
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

CREATE_TRADES_TABLE_PG = """
CREATE TABLE IF NOT EXISTS trades (
    id              SERIAL PRIMARY KEY,
    trigger_time    TEXT NOT NULL,
    coin            TEXT NOT NULL,
    side            TEXT NOT NULL CHECK(side IN ('LONG', 'SHORT')),
    btc_return_pct  DOUBLE PRECISION NOT NULL,
    entry_price     DOUBLE PRECISION NOT NULL,
    tp_price        DOUBLE PRECISION NOT NULL,
    sl_price        DOUBLE PRECISION NOT NULL,
    position_size   DOUBLE PRECISION NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'closed', 'cancelled')),
    exit_price      DOUBLE PRECISION,
    exit_time       TEXT,
    pnl_usdt        DOUBLE PRECISION,
    pnl_pct         DOUBLE PRECISION,
    exit_reason     TEXT CHECK(exit_reason IN ('tp_hit', 'sl_hit', 'timeout', 'manual', 'error', NULL)),
    created_at      TEXT NOT NULL DEFAULT (to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')),
    updated_at      TEXT NOT NULL DEFAULT (to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'))
);
"""

# Each CREATE INDEX is a separate string — SQLite's execute() can only
# handle ONE statement at a time. PostgreSQL execute() also processes
# one statement at a time.
CREATE_TRADES_INDEXES_PG = [
    "CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)",
    "CREATE INDEX IF NOT EXISTS idx_trades_trigger ON trades(trigger_time)",
    "CREATE INDEX IF NOT EXISTS idx_trades_coin ON trades(coin)",
]

CREATE_PROCESSED_CANDLES_TABLE_PG = """
CREATE TABLE IF NOT EXISTS processed_candles (
    coin        TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    processed_at TEXT NOT NULL DEFAULT (to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')),
    PRIMARY KEY (coin, timestamp)
);
"""

CREATE_WEEKLY_SCAN_TABLE_PG = """
CREATE TABLE IF NOT EXISTS weekly_scan (
    week_start  TEXT PRIMARY KEY,
    scan_time   TEXT NOT NULL,
    num_scanned INTEGER NOT NULL DEFAULT 0,
    num_liquid  INTEGER NOT NULL DEFAULT 0,
    results     TEXT NOT NULL,
    top_coins   TEXT NOT NULL
);
"""

CREATE_LOGS_TABLE_PG = """
CREATE TABLE IF NOT EXISTS logs (
    id          SERIAL PRIMARY KEY,
    level       TEXT NOT NULL CHECK(level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    module      TEXT NOT NULL,
    message     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'))
);
"""

CREATE_LOGS_INDEXES_PG = [
    "CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level)",
    "CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at)",
]

CREATE_PNL_SNAPSHOTS_TABLE_PG = """
CREATE TABLE IF NOT EXISTS pnl_snapshots (
    id           SERIAL PRIMARY KEY,
    timestamp    TEXT NOT NULL,
    total_pnl    DOUBLE PRECISION NOT NULL,
    today_pnl    DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    in_trade     INTEGER NOT NULL DEFAULT 0
);
"""

CREATE_PNL_SNAPSHOTS_INDEXES_PG = [
    "CREATE INDEX IF NOT EXISTS idx_pnl_snapshots_ts ON pnl_snapshots(timestamp)",
]

PG_ALL_STATEMENTS = [
    CREATE_CONFIG_TABLE_PG,
    CREATE_TRADES_TABLE_PG,
    *CREATE_TRADES_INDEXES_PG,
    CREATE_PROCESSED_CANDLES_TABLE_PG,
    CREATE_WEEKLY_SCAN_TABLE_PG,
    CREATE_LOGS_TABLE_PG,
    *CREATE_LOGS_INDEXES_PG,
    CREATE_PNL_SNAPSHOTS_TABLE_PG,
    *CREATE_PNL_SNAPSHOTS_INDEXES_PG,
]


# ════════════════════════════════════════════════════════════════
# SQLite DDL (development/testing — used when DATABASE_URL is NOT set)
# ════════════════════════════════════════════════════════════════

CREATE_CONFIG_TABLE_SQLITE = """
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

CREATE_TRADES_TABLE_SQLITE = """
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

CREATE_TRADES_INDEXES_SQLITE = [
    "CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)",
    "CREATE INDEX IF NOT EXISTS idx_trades_trigger ON trades(trigger_time)",
    "CREATE INDEX IF NOT EXISTS idx_trades_coin ON trades(coin)",
]

CREATE_PROCESSED_CANDLES_TABLE_SQLITE = """
CREATE TABLE IF NOT EXISTS processed_candles (
    coin        TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    processed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (coin, timestamp)
);
"""

CREATE_WEEKLY_SCAN_TABLE_SQLITE = """
CREATE TABLE IF NOT EXISTS weekly_scan (
    week_start  TEXT PRIMARY KEY,
    scan_time   TEXT NOT NULL,
    num_scanned INTEGER NOT NULL DEFAULT 0,
    num_liquid  INTEGER NOT NULL DEFAULT 0,
    results     TEXT NOT NULL,
    top_coins   TEXT NOT NULL
);
"""

CREATE_LOGS_TABLE_SQLITE = """
CREATE TABLE IF NOT EXISTS logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    level       TEXT NOT NULL CHECK(level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    module      TEXT NOT NULL,
    message     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_LOGS_INDEXES_SQLITE = [
    "CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level)",
    "CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at)",
]

CREATE_PNL_SNAPSHOTS_TABLE_SQLITE = """
CREATE TABLE IF NOT EXISTS pnl_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL,
    total_pnl    REAL NOT NULL,
    today_pnl    REAL NOT NULL DEFAULT 0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    in_trade     INTEGER NOT NULL DEFAULT 0
);
"""

CREATE_PNL_SNAPSHOTS_INDEXES_SQLITE = [
    "CREATE INDEX IF NOT EXISTS idx_pnl_snapshots_ts ON pnl_snapshots(timestamp)",
]

SQLITE_ALL_STATEMENTS = [
    CREATE_CONFIG_TABLE_SQLITE,
    CREATE_TRADES_TABLE_SQLITE,
    *CREATE_TRADES_INDEXES_SQLITE,
    CREATE_PROCESSED_CANDLES_TABLE_SQLITE,
    CREATE_WEEKLY_SCAN_TABLE_SQLITE,
    CREATE_LOGS_TABLE_SQLITE,
    *CREATE_LOGS_INDEXES_SQLITE,
    CREATE_PNL_SNAPSHOTS_TABLE_SQLITE,
    *CREATE_PNL_SNAPSHOTS_INDEXES_SQLITE,
]

SCHEMA_VERSION = 2


def create_all_tables(conn) -> None:
    """Execute all CREATE TABLE statements on the given connection.
    
    Detects PostgreSQL vs SQLite automatically and runs the right DDL.
    """
    import sqlite3
    
    if not isinstance(conn, sqlite3.Connection):
        # PostgreSQL connection
        for stmt in PG_ALL_STATEMENTS:
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()
        # Set schema version
        conn.execute(
            "INSERT INTO config (key, value) VALUES ('schema_version', %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (str(SCHEMA_VERSION),)
        )
        conn.commit()
    else:
        # SQLite connection
        for stmt in SQLITE_ALL_STATEMENTS:
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
    import sqlite3
    
    if not isinstance(conn, sqlite3.Connection):
        # PostgreSQL: query information_schema
        cursor = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
        tables = {}
        for row in cursor.fetchall():
            table_name = row[0]
            col_cursor = conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s "
                "ORDER BY ordinal_position",
                (table_name,)
            )
            tables[table_name] = [col[0] for col in col_cursor.fetchall()]
        return tables
    else:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {}
        for row in cursor.fetchall():
            table_name = row[0]
            col_cursor = conn.execute(f"PRAGMA table_info({table_name})")
            tables[table_name] = [col[1] for col in col_cursor.fetchall()]
        return tables
