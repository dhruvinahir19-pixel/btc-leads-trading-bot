"""
db.py - Database manager supporting PostgreSQL (production) and SQLite (dev/test).
================================================================================

Production (Neon.tech / any PostgreSQL):
  Set DATABASE_URL environment variable to a PostgreSQL connection string.
  Uses psycopg 3 with SSL mode required.

Development / Testing (SQLite fallback):
  Leave DATABASE_URL unset. Falls back to local trading_bot.db with sqlite3.
  All existing tests continue to work unchanged.

Thread-safe: uses threading.Lock for both backends.
"""
import json
import os
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from backend.config import DATABASE_URL, DB_PATH
from backend.database.schema import create_all_tables, get_table_info

# ─── Global state ─────────────────────────────────────────────
_is_postgres: bool = False
_conn = None
_conn_lock = threading.Lock()

# ─── Lazy psycopg imports (only when DATABASE_URL is set) ─────
_psycopg = None
_dict_row = None


def _ensure_pg_imports():
    """Import psycopg lazily (avoids ImportError when not installed)."""
    global _psycopg, _dict_row
    if _psycopg is not None:
        return
    import psycopg as _psycopg
    from psycopg.rows import dict_row as _dict_row


def _is_pg() -> bool:
    """Check if the active backend is PostgreSQL."""
    global _is_postgres
    return _is_postgres


# ─── Connection Management (Thread-safe) ────────────────────

def get_connection():
    """Get or create the database connection. Thread-safe with lock.
    
    Returns either a psycopg (PostgreSQL) or sqlite3 connection
    depending on whether DATABASE_URL is set.
    
    For PostgreSQL: includes health check on every call. If the connection
    was dropped by Neon's idle timeout, it auto-reconnects before returning.
    This is essential for 24/7 operation on serverless Postgres.
    """
    global _conn, _is_postgres
    
    # ── Health check: if connection exists, ping it ──
    if _conn is not None:
        try:
            if _is_postgres:
                _conn.execute("SELECT 1")
            else:
                _conn.execute("SELECT 1")
            return _conn  # Connection is healthy
        except Exception:
            close_db()  # Stale connection — reset
    
    # ── Create new connection (first time or after reconnect) ──
    with _conn_lock:
        if _conn is not None:
            try:
                if _is_postgres:
                    _conn.execute("SELECT 1")
                else:
                    _conn.execute("SELECT 1")
                return _conn
            except Exception:
                close_db()
        
        if DATABASE_URL and DATABASE_URL.startswith("postgresql"):
            _is_postgres = True
            _ensure_pg_imports()
            
            # ── Unset any proxy env vars so libpq connects directly ──
            # The http_proxy / https_proxy env vars are NOT set by our
            # Dockerfile or entrypoint — the Binance proxy is configured
            # via BINANCE_PROXY config + a custom urllib opener in the
            # BinanceClient class. However, Hugging Face Spaces or other
            # container environments MAY inject them globally. If libpq
            # picks up http_proxy, it tries to route the PostgreSQL wire
            # protocol through Privoxy (HTTP proxy), which rejects the
            # non-HTTP socket connection and raises OperationalError.
            # Popping them here guarantees a direct connection to Neon.
            for _key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
                os.environ.pop(_key, None)
            
            sslmode = "require"
            # ── Explicit sslrootcert to avoid ~/.postgresql/ lookup ──
            # libpq searches ~/.postgresql/root.crt by default for the
            # root CA certificate. When running as appuser, this path
            # may not exist or may point to root's home dir where we
            # have no read permission, causing Permission denied errors.
            # Passing sslrootcert="" tells libpq to use the system CA
            # store (/etc/ssl/certs/) instead.
            if "sslmode=" not in DATABASE_URL:
                _conn = _psycopg.connect(
                    DATABASE_URL + f"&sslmode={sslmode}",
                    sslrootcert="",
                )
            else:
                _conn = _psycopg.connect(
                    DATABASE_URL,
                    sslrootcert="",
                )
            _conn.autocommit = False
            _conn.row_factory = _dict_row
            
            create_all_tables(_conn)
        else:
            _is_postgres = False
            import sqlite3
            
            _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA foreign_keys=ON")
            _conn.execute("PRAGMA busy_timeout=5000")
            
            create_all_tables(_conn)
    
    return _conn


def init_db():
    """Initialize the database: create all tables.
    Called automatically on first get_connection(). Safe to call explicitly."""
    return get_connection()


def close_db():
    """Close the database connection."""
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None


def verify_db() -> dict:
    """Verify database is working. Returns table info."""
    conn = get_connection()
    tables = get_table_info(conn)
    
    try:
        if _is_pg():
            conn.execute(
                "INSERT INTO config (key, value) VALUES ('test_key', 'test_value') "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            )
            conn.commit()
            cursor = conn.execute("SELECT value FROM config WHERE key = 'test_key'")
            row = cursor.fetchone()
            success = row is not None and row['value'] == 'test_value'
        else:
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                ("test_key", "test_value")
            )
            conn.commit()
            cursor = conn.execute("SELECT value FROM config WHERE key = ?", ("test_key",))
            row = cursor.fetchone()
            success = row is not None and row[0] == "test_value"
    except Exception:
        success = False
    
    return {
        "success": success,
        "tables": tables,
        "table_count": len(tables),
        "backend": "postgresql" if _is_pg() else "sqlite",
        "db_path": str(DB_PATH) if not _is_pg() else DATABASE_URL[:40] + "...",
    }


# ─── Helper: execute with backend-aware placeholder ──────────

def _execute(conn, sql: str, params: tuple = None):
    """Execute SQL, converting %s placeholders to ? for SQLite.
    
    Uses `is not None` check (not truthiness) so that an empty
    tuple `()` still gets passed as params (important for some
    PG queries that expect a tuple even when empty).
    """
    if not _is_pg():
        sql = sql.replace("%s", "?")
    if params is not None:
        return conn.execute(sql, params)
    return conn.execute(sql)


# ─── Config CRUD ───────────────────────────────────────────

def config_get(key: str, default: str = "") -> str:
    conn = get_connection()
    cursor = _execute(conn, "SELECT value FROM config WHERE key = %s", (key,))
    row = cursor.fetchone()
    if row:
        return row['value'] if _is_pg() else row[0]
    return default


def config_set(key: str, value: str):
    conn = get_connection()
    if _is_pg():
        conn.execute(
            "INSERT INTO config (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, value)
        )
    else:
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, value)
        )
    conn.commit()


# ─── Helper: format CURRENT_TIMESTAMP consistently ──────────

def _now_sql() -> str:
    """Return SQL expression for current timestamp as formatted text.
    
    PostgreSQL stores timestamps in various formats by default. To keep
    them consistent with the CREATE TABLE defaults (which use to_char()), 
    we explicitly format the timestamp. SQLite's datetime('now') is
    already a formatted string.
    """
    if _is_pg():
        return "to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')"
    return "datetime('now')"


# ─── Trades CRUD ───────────────────────────────────────────

def trade_create(trigger_time: str, coin: str, side: str,
                 btc_return_pct: float, entry_price: float,
                 tp_price: float, sl_price: float,
                 position_size: float) -> int:
    """Create a new trade record. Returns the trade ID."""
    conn = get_connection()
    if _is_pg():
        cursor = conn.execute(
            "INSERT INTO trades (trigger_time, coin, side, btc_return_pct, "
            "entry_price, tp_price, sl_price, position_size) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (trigger_time, coin, side, btc_return_pct,
             entry_price, tp_price, sl_price, position_size)
        )
        conn.commit()
        return cursor.fetchone()['id']
    else:
        cursor = conn.execute(
            "INSERT INTO trades (trigger_time, coin, side, btc_return_pct, "
            "entry_price, tp_price, sl_price, position_size) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (trigger_time, coin, side, btc_return_pct,
             entry_price, tp_price, sl_price, position_size)
        )
        conn.commit()
        return cursor.lastrowid


def trade_close(trade_id: int, exit_price: float, exit_time: str,
                pnl_usdt: float, pnl_pct: float, exit_reason: str):
    """Close a trade with exit details."""
    conn = get_connection()
    now_expr = _now_sql()
    _execute(conn,
        f"UPDATE trades SET status = 'closed', exit_price = %s, exit_time = %s, "
        f"pnl_usdt = %s, pnl_pct = %s, exit_reason = %s, "
        f"updated_at = {now_expr} WHERE id = %s",
        (exit_price, exit_time, pnl_usdt, pnl_pct, exit_reason, trade_id)
    )
    conn.commit()


def trade_cancel(trade_id: int):
    """Cancel a trade."""
    conn = get_connection()
    now_expr = _now_sql()
    _execute(conn,
        f"UPDATE trades SET status = 'cancelled', updated_at = {now_expr} "
        f"WHERE id = %s",
        (trade_id,)
    )
    conn.commit()


def get_open_trades() -> list:
    """Get all open trades."""
    conn = get_connection()
    cursor = _execute(conn,
        "SELECT * FROM trades WHERE status = 'open' ORDER BY created_at DESC"
    )
    return [dict(row) for row in cursor.fetchall()]


def get_recent_trades(limit: int = 20) -> list:
    """Get most recent trades."""
    conn = get_connection()
    cursor = _execute(conn,
        "SELECT * FROM trades ORDER BY created_at DESC LIMIT %s",
        (limit,)
    )
    return [dict(row) for row in cursor.fetchall()]


def get_trade_stats() -> dict:
    """Get aggregate trade statistics."""
    conn = get_connection()
    
    def _scalar(sql, params=None):
        cursor = _execute(conn, sql, params)
        row = cursor.fetchone()
        if row is None:
            return 0
        # psycopg dict_row only supports name-based access; sqlite3.Row
        # supports both. Use name-based via dict() for both backends.
        return list(dict(row).values())[0]
    
    total = _scalar("SELECT COUNT(*) FROM trades")
    winning_trades = _scalar("SELECT COUNT(*) FROM trades WHERE exit_reason = 'tp_hit'")
    losing_trades = _scalar(
        "SELECT COUNT(*) FROM trades WHERE exit_reason IN ('sl_hit', 'timeout')"
    )
    open_trades = _scalar("SELECT COUNT(*) FROM trades WHERE status = 'open'")
    total_pnl = _scalar(
        "SELECT COALESCE(SUM(pnl_usdt), 0) FROM trades WHERE status = 'closed'"
    )
    avg_pnl = _scalar(
        "SELECT COALESCE(AVG(pnl_usdt), 0) FROM trades WHERE status = 'closed'"
    )
    max_pnl = _scalar(
        "SELECT COALESCE(MAX(pnl_usdt), 0) FROM trades WHERE status = 'closed'"
    )
    min_pnl = _scalar(
        "SELECT COALESCE(MIN(pnl_usdt), 0) FROM trades WHERE status = 'closed'"
    )
    
    # Streak calculation
    cursor = _execute(conn,
        "SELECT pnl_usdt FROM trades WHERE status = 'closed' ORDER BY exit_time DESC"
    )
    streak_pnls = []
    for row in cursor.fetchall():
        try:
            val = row['pnl_usdt'] if _is_pg() else row[0]
        except (KeyError, IndexError, TypeError):
            val = row[0]  # Fallback for both backends
        streak_pnls.append(val)
    
    current_streak = 0
    best_streak = 0
    worst_streak = 0
    
    if streak_pnls:
        if streak_pnls[0] is not None:
            first_sign = streak_pnls[0] >= 0
            for pnl in streak_pnls:
                if pnl is None:
                    break
                if (pnl >= 0) == first_sign:
                    current_streak += 1
                else:
                    break
        
        pos_streak = 0
        neg_streak = 0
        for pnl in streak_pnls:
            if pnl is None:
                pos_streak = 0
                neg_streak = 0
            elif pnl >= 0:
                pos_streak += 1
                neg_streak = 0
            else:
                neg_streak += 1
                pos_streak = 0
            best_streak = max(best_streak, pos_streak)
            worst_streak = max(worst_streak, neg_streak)
    
    # Today's PnL (IST)
    today = (datetime.now(timezone.utc) + timedelta(hours=5.5)).strftime("%Y-%m-%d")
    today_pnl = _scalar(
        "SELECT COALESCE(SUM(pnl_usdt), 0) FROM trades "
        "WHERE status = 'closed' AND DATE(exit_time) = %s",
        (today,)
    )
    
    return {
        "total_trades": total,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": round(winning_trades / total * 100, 1) if total > 0 else 0,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2) if streak_pnls else 0,
        "max_pnl": round(max_pnl, 2) if streak_pnls else 0,
        "min_pnl": round(min_pnl, 2) if streak_pnls else 0,
        "current_streak": current_streak,
        "best_streak": best_streak,
        "worst_streak": worst_streak,
        "open_trades": open_trades,
        "today_pnl": round(today_pnl, 2),
    }


# ─── Processed Candles ─────────────────────────────────────

def is_candle_processed(coin: str, timestamp: str) -> bool:
    """Check if a candle timestamp has already been processed."""
    conn = get_connection()
    cursor = _execute(conn,
        "SELECT 1 FROM processed_candles WHERE coin = %s AND timestamp = %s",
        (coin, timestamp)
    )
    return cursor.fetchone() is not None


def mark_candle_processed(coin: str, timestamp: str):
    """Mark a candle as processed to prevent duplicate triggers."""
    conn = get_connection()
    if _is_pg():
        conn.execute(
            "INSERT INTO processed_candles (coin, timestamp) VALUES (%s, %s) "
            "ON CONFLICT (coin, timestamp) DO NOTHING",
            (coin, timestamp)
        )
    else:
        conn.execute(
            "INSERT OR IGNORE INTO processed_candles (coin, timestamp) VALUES (?, ?)",
            (coin, timestamp)
        )
    conn.commit()


def get_last_processed_candle(coin: str) -> Optional[str]:
    """Get the last processed candle timestamp for a coin."""
    conn = get_connection()
    cursor = _execute(conn,
        "SELECT timestamp FROM processed_candles WHERE coin = %s "
        "ORDER BY timestamp DESC LIMIT 1",
        (coin,)
    )
    row = cursor.fetchone()
    if row:
        return row['timestamp'] if _is_pg() else row[0]
    return None


# ─── Weekly Scan ───────────────────────────────────────────

def save_scan_result(week_start: str, scan_time: str,
                     num_scanned: int, num_liquid: int,
                     results: list, top_coins: list):
    """Save weekly scan results."""
    conn = get_connection()
    if _is_pg():
        conn.execute(
            "INSERT INTO weekly_scan (week_start, scan_time, num_scanned, "
            "num_liquid, results, top_coins) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (week_start) DO UPDATE SET "
            "scan_time = EXCLUDED.scan_time, num_scanned = EXCLUDED.num_scanned, "
            "num_liquid = EXCLUDED.num_liquid, results = EXCLUDED.results, "
            "top_coins = EXCLUDED.top_coins",
            (week_start, scan_time, num_scanned, num_liquid,
             json.dumps(results), json.dumps(top_coins))
        )
    else:
        conn.execute(
            "INSERT OR REPLACE INTO weekly_scan "
            "(week_start, scan_time, num_scanned, num_liquid, results, top_coins) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (week_start, scan_time, num_scanned, num_liquid,
             json.dumps(results), json.dumps(top_coins))
        )
    conn.commit()


def get_latest_scan() -> Optional[dict]:
    """Get the most recent weekly scan results."""
    conn = get_connection()
    cursor = _execute(conn,
        "SELECT * FROM weekly_scan ORDER BY week_start DESC LIMIT 1"
    )
    row = cursor.fetchone()
    if row:
        result = dict(row)
        result["results"] = json.loads(result["results"])
        result["top_coins"] = json.loads(result["top_coins"])
        return result
    return None


# ─── Logs ──────────────────────────────────────────────────

def log_event(level: str, module: str, message: str):
    """Insert a log entry into the database."""
    conn = get_connection()
    _execute(conn,
        "INSERT INTO logs (level, module, message) VALUES (%s, %s, %s)",
        (level, module, message)
    )
    conn.commit()


def get_recent_logs(level: Optional[str] = None, limit: int = 50) -> list:
    """Get recent log entries, optionally filtered by level."""
    conn = get_connection()
    if level:
        cursor = _execute(conn,
            "SELECT * FROM logs WHERE level = %s ORDER BY created_at DESC LIMIT %s",
            (level.upper(), limit)
        )
    else:
        cursor = _execute(conn,
            "SELECT * FROM logs ORDER BY created_at DESC LIMIT %s",
            (limit,)
        )
    return [dict(row) for row in cursor.fetchall()]


# ─── Daily PnL Tracking ───────────────────────────────────

def get_daily_pnl(date_str: Optional[str] = None) -> float:
    """Get total PnL for a specific date (IST). Returns 0 if no trades."""
    conn = get_connection()
    if date_str is None:
        ist_now = datetime.now(timezone.utc) + timedelta(hours=5.5)
        date_str = ist_now.strftime("%Y-%m-%d")
    
    cursor = _execute(conn,
        "SELECT COALESCE(SUM(pnl_usdt), 0) AS total FROM trades "
        "WHERE status = 'closed' AND DATE(exit_time) = %s",
        (date_str,)
    )
    row = cursor.fetchone()
    if row is not None and row['total'] is not None:
        # Use column name (aliased as 'total') — works for both
        # sqlite3.Row (supports name access) and psycopg dict_row.
        return float(round(float(row['total']), 2))
    return 0.0


def is_daily_loss_limit_hit(max_loss: float) -> bool:
    """Check if today's losses have exceeded the daily limit."""
    today_pnl = get_daily_pnl()
    return today_pnl <= -max_loss


# ─── PnL Snapshots (Equity Curve) ─────────────────────────

def save_pnl_snapshot(total_pnl: float, today_pnl: float, total_trades: int, in_trade: bool):
    """Save a PnL snapshot for the equity curve chart."""
    ist_now = datetime.now(timezone.utc) + timedelta(hours=5.5)
    ts = ist_now.strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    _execute(conn,
        "INSERT INTO pnl_snapshots (timestamp, total_pnl, today_pnl, total_trades, in_trade) "
        "VALUES (%s, %s, %s, %s, %s)",
        (ts, total_pnl, today_pnl, total_trades, 1 if in_trade else 0)
    )
    conn.commit()


def get_pnl_history(limit: int = 200) -> list:
    """Get PnL snapshot history for the equity curve chart."""
    conn = get_connection()
    cursor = _execute(conn,
        "SELECT * FROM pnl_snapshots ORDER BY timestamp ASC LIMIT %s",
        (limit,)
    )
    return [dict(row) for row in cursor.fetchall()]


def get_pnl_breakdown_by_coin(days: int = 30) -> list:
    """Get daily PnL breakdown by coin for the last N days."""
    ist_now = datetime.now(timezone.utc) + timedelta(hours=5.5)
    cutoff = (ist_now - timedelta(days=days)).strftime("%Y-%m-%d")
    
    conn = get_connection()
    cursor = _execute(conn,
        """
        SELECT 
            DATE(exit_time) AS day,
            coin,
            side,
            COUNT(*) AS trade_count,
            COALESCE(SUM(pnl_usdt), 0) AS total_pnl,
            COALESCE(AVG(pnl_usdt), 0) AS avg_pnl,
            COALESCE(SUM(CASE WHEN pnl_usdt > 0 THEN 1 ELSE 0 END), 0) AS wins,
            COALESCE(SUM(CASE WHEN pnl_usdt < 0 THEN 1 ELSE 0 END), 0) AS losses
        FROM trades 
        WHERE status = 'closed' AND DATE(exit_time) >= %s
        GROUP BY DATE(exit_time), coin, side
        ORDER BY day DESC, total_pnl DESC
        LIMIT 500
        """,
        (cutoff,)
    )
    return [dict(row) for row in cursor.fetchall()]


def get_trade_journal(
    limit: int = 100,
    offset: int = 0,
    coin: str = None,
    side: str = None,
    exit_reason: str = None,
    date_from: str = None,
    date_to: str = None,
) -> dict:
    """Get trades with advanced filtering for the trade journal."""
    conn = get_connection()
    
    where_clauses = []
    params = []
    
    if coin:
        where_clauses.append("coin = %s" if _is_pg() else "coin = ?")
        params.append(coin)
    if side:
        where_clauses.append("side = %s" if _is_pg() else "side = ?")
        params.append(side.upper())
    if exit_reason:
        where_clauses.append("exit_reason = %s" if _is_pg() else "exit_reason = ?")
        params.append(exit_reason)
    if date_from:
        where_clauses.append("DATE(trigger_time) >= %s" if _is_pg() else "date(trigger_time) >= ?")
        params.append(date_from)
    if date_to:
        where_clauses.append("DATE(trigger_time) <= %s" if _is_pg() else "date(trigger_time) <= ?")
        params.append(date_to)
    
    where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"
    
    # Get total count
    count_cursor = _execute(conn,
        f"SELECT COUNT(*) AS cnt FROM trades WHERE {where_sql}", tuple(params) if params else None
    )
    count_row = count_cursor.fetchone()
    # Use column name (aliased as 'cnt') — works for both backends
    total = count_row['cnt'] if count_row else 0
    
    # Get paginated results
    cursor = _execute(conn,
        f"SELECT * FROM trades WHERE {where_sql} ORDER BY created_at DESC "
        f"LIMIT %s OFFSET %s",
        tuple(params + [limit, offset])
    )
    trades = [dict(row) for row in cursor.fetchall()]
    
    # Get aggregate stats for the filtered set
    agg_cursor = _execute(conn,
        f"""
        SELECT 
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN pnl_usdt > 0 THEN 1 ELSE 0 END), 0) AS wins,
            COALESCE(SUM(CASE WHEN pnl_usdt < 0 THEN 1 ELSE 0 END), 0) AS losses,
            COALESCE(SUM(pnl_usdt), 0) AS total_pnl
        FROM trades WHERE {where_sql}
        """,
        tuple(params) if params else None
    )
    agg_row = agg_cursor.fetchone()
    agg = dict(agg_row) if agg_row else {"total": 0, "wins": 0, "losses": 0, "total_pnl": 0}
    
    return {
        "trades": trades,
        "total": total,
        "returned": len(trades),
        "offset": offset,
        "limit": limit,
        "summary": {
            "count": agg["total"],
            "wins": agg["wins"],
            "losses": agg["losses"],
            "total_pnl": round(float(agg["total_pnl"]), 2),
        },
    }
