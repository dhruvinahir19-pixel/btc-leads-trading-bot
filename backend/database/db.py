"""
db.py - SQLite database manager.
Handles connection lifecycle, CRUD operations for all tables.
Thread-safe: uses threading.Lock and check_same_thread=False for uvicorn.
"""
import sqlite3
import json
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from backend.config import DB_PATH, BINANCE_API_KEY
from backend.database.schema import create_all_tables, get_table_info

# ─── Connection Management (Thread-safe) ────────────────────

_conn: Optional[sqlite3.Connection] = None
_conn_lock = threading.Lock()


def get_connection() -> sqlite3.Connection:
    """Get or create the database connection. Thread-safe with lock."""
    global _conn
    if _conn is None:
        with _conn_lock:
            # Double-check after acquiring lock
            if _conn is None:
                _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
                _conn.row_factory = sqlite3.Row
                _conn.execute("PRAGMA journal_mode=WAL")   # Better concurrent access
                _conn.execute("PRAGMA foreign_keys=ON")
                _conn.execute("PRAGMA busy_timeout=5000")  # Wait 5s if locked
                # Auto-create tables on first connection
                create_all_tables(_conn)
    return _conn


def init_db():
    """Initialize the database: create all tables.
    This is called automatically on first get_connection().
    Calling it explicitly is safe (idempotent)."""
    conn = get_connection()
    return conn


def close_db():
    """Close the database connection."""
    global _conn
    if _conn:
        _conn.close()
        _conn = None


def verify_db() -> dict:
    """Verify database is working. Returns table info for testing."""
    conn = get_connection()
    tables = get_table_info(conn)
    # Try inserting and reading a test config
    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                 ("test_key", "test_value"))
    conn.commit()
    cursor = conn.execute("SELECT value FROM config WHERE key = ?", ("test_key",))
    result = cursor.fetchone()
    success = result is not None and result[0] == "test_value"
    return {
        "success": success,
        "tables": tables,
        "table_count": len(tables),
        "db_path": str(DB_PATH),
    }


# ─── Config CRUD ───────────────────────────────────────────

def config_get(key: str, default: str = "") -> str:
    conn = get_connection()
    cursor = conn.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = cursor.fetchone()
    return row[0] if row else default


def config_set(key: str, value: str):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


# ─── Trades CRUD ───────────────────────────────────────────

def trade_create(trigger_time: str, coin: str, side: str,
                 btc_return_pct: float, entry_price: float,
                 tp_price: float, sl_price: float,
                 position_size: float) -> int:
    """Create a new trade record. Returns the trade ID."""
    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO trades (trigger_time, coin, side, btc_return_pct,
                           entry_price, tp_price, sl_price, position_size)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (trigger_time, coin, side, btc_return_pct,
          entry_price, tp_price, sl_price, position_size))
    conn.commit()
    return cursor.lastrowid


def trade_close(trade_id: int, exit_price: float, exit_time: str,
                pnl_usdt: float, pnl_pct: float, exit_reason: str):
    """Close a trade with exit details."""
    conn = get_connection()
    conn.execute("""
        UPDATE trades SET
            status = 'closed',
            exit_price = ?,
            exit_time = ?,
            pnl_usdt = ?,
            pnl_pct = ?,
            exit_reason = ?,
            updated_at = datetime('now')
        WHERE id = ?
    """, (exit_price, exit_time, pnl_usdt, pnl_pct, exit_reason, trade_id))
    conn.commit()


def trade_cancel(trade_id: int):
    """Cancel a trade (e.g., order not filled)."""
    conn = get_connection()
    conn.execute("""
        UPDATE trades SET status = 'cancelled', updated_at = datetime('now')
        WHERE id = ?
    """, (trade_id,))
    conn.commit()


def get_open_trades() -> list:
    """Get all open trades."""
    conn = get_connection()
    cursor = conn.execute("""
        SELECT * FROM trades WHERE status = 'open' ORDER BY created_at DESC
    """)
    return [dict(row) for row in cursor.fetchall()]


def get_recent_trades(limit: int = 20) -> list:
    """Get most recent trades."""
    conn = get_connection()
    cursor = conn.execute("""
        SELECT * FROM trades ORDER BY created_at DESC LIMIT ?
    """, (limit,))
    return [dict(row) for row in cursor.fetchall()]


def get_trade_stats() -> dict:
    """Get aggregate trade statistics with fields matching frontend types."""
    conn = get_connection()
    
    total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    winning_trades = conn.execute("SELECT COUNT(*) FROM trades WHERE exit_reason = 'tp_hit'").fetchone()[0]
    losing_trades = conn.execute("SELECT COUNT(*) FROM trades WHERE exit_reason IN ('sl_hit', 'timeout')").fetchone()[0]
    open_trades = conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'open'").fetchone()[0]
    
    # PnL calculations
    total_pnl = conn.execute("SELECT COALESCE(SUM(pnl_usdt), 0) FROM trades WHERE status = 'closed'").fetchone()[0]
    avg_pnl = conn.execute("SELECT COALESCE(AVG(pnl_usdt), 0) FROM trades WHERE status = 'closed'").fetchone()[0]
    max_pnl = conn.execute("SELECT COALESCE(MAX(pnl_usdt), 0) FROM trades WHERE status = 'closed'").fetchone()[0]
    min_pnl = conn.execute("SELECT COALESCE(MIN(pnl_usdt), 0) FROM trades WHERE status = 'closed'").fetchone()[0]
    
    # Streak calculation: get last closed trades ordered by exit_time
    streaks_cursor = conn.execute(
        "SELECT pnl_usdt FROM trades WHERE status = 'closed' ORDER BY exit_time DESC"
    )
    streak_pnls = [row[0] for row in streaks_cursor.fetchall()]
    
    current_streak = 0
    best_streak = 0
    worst_streak = 0
    
    if streak_pnls:
        # Current streak (consecutive from most recent)
        if streak_pnls[0] is not None:
            first_sign = streak_pnls[0] >= 0
            for pnl in streak_pnls:
                if pnl is None:
                    break
                if (pnl >= 0) == first_sign:
                    current_streak += 1
                else:
                    break
        
        # Best / worst streaks
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
    today_pnl = conn.execute(
        "SELECT COALESCE(SUM(pnl_usdt), 0) FROM trades WHERE status = 'closed' AND date(exit_time) = ?",
        (today,)
    ).fetchone()[0]
    
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
    cursor = conn.execute(
        "SELECT 1 FROM processed_candles WHERE coin = ? AND timestamp = ?",
        (coin, timestamp)
    )
    return cursor.fetchone() is not None


def mark_candle_processed(coin: str, timestamp: str):
    """Mark a candle as processed to prevent duplicate triggers."""
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO processed_candles (coin, timestamp) VALUES (?, ?)",
        (coin, timestamp)
    )
    conn.commit()


def get_last_processed_candle(coin: str) -> Optional[str]:
    """Get the last processed candle timestamp for a coin."""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT timestamp FROM processed_candles WHERE coin = ? ORDER BY timestamp DESC LIMIT 1",
        (coin,)
    )
    row = cursor.fetchone()
    return row[0] if row else None


# ─── Weekly Scan ───────────────────────────────────────────

def save_scan_result(week_start: str, scan_time: str,
                     num_scanned: int, num_liquid: int,
                     results: list, top_coins: list):
    """Save weekly scan results."""
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO weekly_scan
        (week_start, scan_time, num_scanned, num_liquid, results, top_coins)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (week_start, scan_time, num_scanned, num_liquid,
          json.dumps(results), json.dumps(top_coins)))
    conn.commit()


def get_latest_scan() -> Optional[dict]:
    """Get the most recent weekly scan results."""
    conn = get_connection()
    cursor = conn.execute(
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
    """Insert a log entry."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO logs (level, module, message) VALUES (?, ?, ?)",
        (level, module, message)
    )
    conn.commit()


def get_recent_logs(level: Optional[str] = None, limit: int = 50) -> list:
    """Get recent log entries, optionally filtered by level."""
    conn = get_connection()
    if level:
        cursor = conn.execute(
            "SELECT * FROM logs WHERE level = ? ORDER BY created_at DESC LIMIT ?",
            (level.upper(), limit)
        )
    else:
        cursor = conn.execute(
            "SELECT * FROM logs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
    return [dict(row) for row in cursor.fetchall()]


# ─── Daily PnL Tracking ───────────────────────────────────

def get_daily_pnl(date_str: Optional[str] = None) -> float:
    """Get total PnL for a specific date (IST). Returns 0 if no trades."""
    conn = get_connection()
    if date_str is None:
        from datetime import datetime, timezone, timedelta
        ist_now = datetime.now(timezone.utc) + timedelta(hours=5.5)
        date_str = ist_now.strftime("%Y-%m-%d")
    
    cursor = conn.execute(
        "SELECT COALESCE(SUM(pnl_usdt), 0) FROM trades "
        "WHERE status = 'closed' AND date(exit_time) = ?",
        (date_str,)
    )
    result = cursor.fetchone()[0]
    return float(round(result, 2)) if result is not None else 0.0


def is_daily_loss_limit_hit(max_loss: float) -> bool:
    """Check if today's losses have exceeded the daily limit."""
    today_pnl = get_daily_pnl()
    return today_pnl <= -max_loss


# ─── PnL Snapshots (Equity Curve) ─────────────────────────

def save_pnl_snapshot(total_pnl: float, today_pnl: float, total_trades: int, in_trade: bool):
    """Save a PnL snapshot for the equity curve chart."""
    from datetime import datetime, timezone, timedelta
    ist_now = datetime.now(timezone.utc) + timedelta(hours=5.5)
    ts = ist_now.strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    conn.execute(
        "INSERT INTO pnl_snapshots (timestamp, total_pnl, today_pnl, total_trades, in_trade) "
        "VALUES (?, ?, ?, ?, ?)",
        (ts, total_pnl, today_pnl, total_trades, 1 if in_trade else 0)
    )
    conn.commit()


def get_pnl_history(limit: int = 200) -> list:
    """Get PnL snapshot history for the equity curve chart."""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT * FROM pnl_snapshots ORDER BY timestamp ASC LIMIT ?",
        (limit,)
    )
    return [dict(row) for row in cursor.fetchall()]


def get_pnl_breakdown_by_coin(days: int = 30) -> list:
    """Get daily PnL breakdown by coin for the last N days."""
    from datetime import datetime, timezone, timedelta
    ist_now = datetime.now(timezone.utc) + timedelta(hours=5.5)
    cutoff = (ist_now - timedelta(days=days)).strftime("%Y-%m-%d")
    
    conn = get_connection()
    cursor = conn.execute(
        """
        SELECT 
            date(exit_time) as day,
            coin,
            side,
            COUNT(*) as trade_count,
            COALESCE(SUM(pnl_usdt), 0) as total_pnl,
            COALESCE(AVG(pnl_usdt), 0) as avg_pnl,
            COALESCE(SUM(CASE WHEN pnl_usdt > 0 THEN 1 ELSE 0 END), 0) as wins,
            COALESCE(SUM(CASE WHEN pnl_usdt < 0 THEN 1 ELSE 0 END), 0) as losses
        FROM trades 
        WHERE status = 'closed' AND date(exit_time) >= ?
        GROUP BY date(exit_time), coin, side
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
        where_clauses.append("coin = ?")
        params.append(coin)
    if side:
        where_clauses.append("side = ?")
        params.append(side.upper())
    if exit_reason:
        where_clauses.append("exit_reason = ?")
        params.append(exit_reason)
    if date_from:
        where_clauses.append("date(trigger_time) >= ?")
        params.append(date_from)
    if date_to:
        where_clauses.append("date(trigger_time) <= ?")
        params.append(date_to)
    
    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    
    # Get total count
    count_cursor = conn.execute(
        f"SELECT COUNT(*) FROM trades WHERE {where_sql}", params
    )
    total = count_cursor.fetchone()[0]
    
    # Get paginated results
    cursor = conn.execute(
        f"SELECT * FROM trades WHERE {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset]
    )
    trades = [dict(row) for row in cursor.fetchall()]
    
    # Get aggregate stats for the filtered set
    agg_cursor = conn.execute(
        f"""
        SELECT 
            COUNT(*) as total,
            COALESCE(SUM(CASE WHEN pnl_usdt > 0 THEN 1 ELSE 0 END), 0) as wins,
            COALESCE(SUM(CASE WHEN pnl_usdt < 0 THEN 1 ELSE 0 END), 0) as losses,
            COALESCE(SUM(pnl_usdt), 0) as total_pnl
        FROM trades WHERE {where_sql}
        """,
        params
    )
    agg = dict(agg_cursor.fetchone())
    
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
            "total_pnl": round(agg["total_pnl"], 2),
        },
    }
