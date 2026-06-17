"""
main.py - FastAPI application entry point.
Serves the trading bot, scheduler, dashboard API, and frontend.
"""
import sys
import os
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional
import threading
import urllib.request
import urllib.error

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ─── Structured Logging ────────────────────────────────────
from backend.logging_setup import setup_logging, get_logger
logger = get_logger("main")

# ─── Backend Imports ───────────────────────────────────────
from backend.config import (
    HOST, PORT, LOG_LEVEL, show_config, DB_PATH, BASE_DIR,
    TRADING_COINS, BINANCE_DEMO_KEY, SMTP_EMAIL,
    BTC_TRIGGER_PCT, TP_PCT, SL_PCT, POSITION_SIZE_USDT, MAX_DAILY_LOSS_USDT,
    to_ist_timestamp, CANDLE_CHECK_MINUTE, CANDLE_CHECK_SECOND,
    IN_TRADE_CHECK_INTERVAL, SCAN_DAY, SCAN_HOUR,
    IS_RENDER, RENDER_EXTERNAL_URL, IST_TZ, now_ist,
)
from backend.database.db import (
    init_db, get_connection, get_recent_trades, get_trade_stats,
    get_recent_logs, log_event, get_daily_pnl, get_open_trades,
    save_pnl_snapshot, get_pnl_history,
)
from backend.notifications.email_alerts import get_notifier
from backend.state.state_manager import get_bot_status
from backend.core.signal import SignalGenerator
from backend.core.data_fetcher import DataFetcher
from backend.trading.entry_manager import EntryManager
from backend.trading.exit_manager import ExitManager
from backend.trading.reconciliation import Reconciliation
from backend.trading.risk_manager import RiskManager
from backend.api import websocket_manager as ws

# ─── Global state ──────────────────────────────────────────
signal_generator = SignalGenerator()
data_fetcher = DataFetcher()
entry_manager = EntryManager()
exit_manager = ExitManager()
reconciliation = Reconciliation()
risk_manager = RiskManager()
_bot_started_at = datetime.now(timezone.utc)

# ─── Startup health flag ───────────────────────────────────
# If ANY step of lifespan initialization fails, this flag is set to False
# and the /health endpoint reports the degraded state instead of crashing.
# The app ALWAYS serves requests, even with partial initialization.
_startup_healthy = True
_startup_errors: list[str] = []


# ─── BTC Price Cache (avoids Binance calls on every dashboard load) ────
# When banned, the cache returns the last known price instead of calling Binance.
_btc_price_cache = {'price': 0.0, 'timestamp': 0.0}



# ─── Application Lifecycle ─────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown.
    Graceful shutdown is handled by uvicorn's built-in signal handlers.
    The shutdown section (after yield) runs automatically on SIGTERM/SIGINT.
    
    SAFETY: The ENTIRE startup is wrapped in try/except. Even if something
    fails (DB corrupt, import error, network timeout), the app still starts
    and serves requests in degraded mode. The /health endpoint reports
    startup errors so you can diagnose without crashing.
    """
    global _startup_healthy, _startup_errors
    _startup_errors = []
    
    try:
        # Initialize structured logging
        log_dir = BASE_DIR / "logs"
        setup_logging(log_dir=log_dir, log_level=LOG_LEVEL)
        
        logger.info(f"{'='*60}")
        logger.info(f"TRADING BOT v1.0 - Starting up")
        logger.info(f"DB: {DB_PATH}")
        logger.info(f"{'='*60}")
        
        # Initialize database
        try:
            init_db()
            log_event('INFO', 'main', 'Database initialized')
        except Exception as e:
            err = f"DB init failed: {e}"
            _startup_errors.append(err)
            print(f"[FATAL] {err}", file=sys.stderr)
        
        # Show configuration (safe — just prints)
        try:
            show_config()
        except Exception as e:
            _startup_errors.append(f"show_config failed: {e}")
        
        # Check for orphan positions from previous bot session
        try:
            _check_orphan_positions()
        except Exception as e:
            _startup_errors.append(f"Orphan check failed: {e}")
        
        # Start scheduler
        try:
            _start_scheduler()
        except Exception as e:
            _startup_errors.append(f"Scheduler start failed: {e}")
        
        # Send startup email
        try:
            config_summary = (
                f"Trigger: {BTC_TRIGGER_PCT}% | TP: {TP_PCT}% | SL: {SL_PCT}% | "
                f"Position: ${POSITION_SIZE_USDT:.0f} | Daily Loss Limit: ${MAX_DAILY_LOSS_USDT:.0f}"
            )
            notifier = get_notifier()
            app.state.notifier = notifier
            if notifier.is_configured:
                notifier.send_startup("1.0.0", str(DB_PATH), config_summary)
        except Exception as e:
            _startup_errors.append(f"Startup email failed: {e}")
        
        # Store bot started timestamp
        app.state.bot_started_at = _bot_started_at
        
        # ── Determine overall health ──
        if _startup_errors:
            _startup_healthy = False
            print(f"[WARNING] Startup completed with {len(_startup_errors)} error(s):", file=sys.stderr)
            for err in _startup_errors:
                print(f"  - {err}", file=sys.stderr)
            log_event('WARNING', 'main',
                      f"Startup degraded: {len(_startup_errors)} error(s): {'; '.join(_startup_errors)}")
            logger.warning(f"Startup degraded with {len(_startup_errors)} error(s)")
        else:
            _startup_healthy = True
            log_event('INFO', 'main', 'Bot started successfully')
            logger.info("Bot started successfully")
        
    except Exception as e:
        # Safety net: if anything in the outer try/except itself crashes
        _startup_healthy = False
        _startup_errors.append(f"Unexpected startup crash: {e}")
        print(f"[CRITICAL] Startup crashed: {e}", file=sys.stderr)
        log_event('ERROR', 'main', f"Startup crashed: {e}")
    
    # ── Start WebSocket manager for live market data ──
    # Subscribes to Binance Futures WebSocket streams (klines, tickers)
    # so the bot NEVER needs REST calls for live data. Falls back to
    # REST if WS not connected (cold start).
    try:
        ws.start()
        logger.info("WebSocket manager started for live market data")
    except Exception as e:
        _startup_errors.append(f"WebSocket start failed: {e}")
        logger.warning(f"WebSocket manager failed to start: {e}")

    # ── Start keep-alive thread ALWAYS, even in degraded mode ──
    # The app must keep itself alive even when degraded so it can
    # serve /health and allow diagnosis. Without this, degraded mode
    # falls into a permanent sleep-loop (spin down → wake → spin down).
    _start_keepalive_thread()
    
    yield
    
    # Shutdown (also wrapped in try/except — never crash on shutdown)
    try:
        uptime = (datetime.now(timezone.utc) - _bot_started_at).total_seconds()
        logger.info(f"Shutting down after {uptime:.0f}s uptime")
        notifier = getattr(app.state, 'notifier', None)
        if notifier and notifier.is_configured:
            notifier.send_shutdown(uptime)
        log_event('INFO', 'main', 'Bot shutting down')
        logger.info("Bot shutdown complete.")
    except Exception as e:
        print(f"[WARNING] Shutdown error: {e}", file=sys.stderr)


# ─── FastAPI App ───────────────────────────────────────────

app = FastAPI(
    title="BTC Leads Trading Bot",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Scheduler ─────────────────────────────────────────────

def _start_scheduler():
    """Start the APScheduler with all scheduled jobs."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        
        scheduler = BackgroundScheduler()
        
        # Job 1: Check BTC candle at xx:30:02 IST every hour
        # APScheduler supports timezone-aware cron triggers
        # ── All cron schedules converted to UTC equivalents ──
        # IST = UTC + 5:30.  xx:30 IST = (xx-5):00 UTC.
        # This avoids any pytz/zoneinfo timezone-name resolution issues.
        UTC_TZ = timezone.utc
        
        # Job 1: Check BTC candle at xx:30:02 IST = (xx-5):00:02 UTC every hour
        scheduler.add_job(
            check_btc_candle,
            CronTrigger(hour='*', minute=0, second=2, timezone=UTC_TZ),
            id='check_btc',
            name='Check BTC candle for triggers',
        )
        
        # Job 2: In-trade monitoring (every 60 seconds, aligned to :02 second mark UTC)
        now_utc = datetime.now(timezone.utc)
        now_second = now_utc.second
        seconds_to_next_check = (2 - now_second) % 60
        if seconds_to_next_check < 2:
            seconds_to_next_check += 60
        first_run = now_utc + timedelta(seconds=seconds_to_next_check)
        scheduler.add_job(
            monitor_positions,
            trigger='interval',
            seconds=IN_TRADE_CHECK_INTERVAL,
            next_run_time=first_run,
            id='monitor_positions',
            name='Monitor open positions',
        )
        
        # Job 3: Daily reset at 00:01 IST = 18:31 UTC (previous day)
        scheduler.add_job(
            daily_reset,
            CronTrigger(hour=18, minute=31, second=0, timezone=UTC_TZ),
            id='daily_reset',
            name='Reset daily counters',
        )
        
        # Job 4: Weekly scan every Sunday 00:00 IST = Saturday 18:30 UTC
        scheduler.add_job(
            run_weekly_scan_job,
            CronTrigger(day_of_week='sat', hour=18, minute=30, second=0, timezone=UTC_TZ),
            id='weekly_scan',
            name='Weekly correlation scan',
        )
        
        # Also run weekly scan on startup if needed
        scheduler.add_job(
            run_weekly_scan_if_needed,
            trigger='date',
            next_run_time=datetime.now(timezone.utc) + timedelta(minutes=1),
            id='initial_scan_check',
            name='Check if initial scan needed',
        )
        
        # Job 5: Check orphan positions 5s after startup
        scheduler.add_job(
            _deferred_orphan_check,
            trigger='date',
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=5),
            id='check_orphans_deferred',
            name='Deferred orphan position check',
        )
        
        # Job 6: BTC candle check immediately at startup (3s delay)
        scheduler.add_job(
            check_btc_candle,
            trigger='date',
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=3),
            id='check_btc_startup',
            name='BTC candle check right after startup',
        )
        
        # Job 7: Send status summary email every 6 hours
        # 06:00:30 IST = 00:30:30 UTC
        # 12:00:30 IST = 06:30:30 UTC
        # 18:00:30 IST = 12:30:30 UTC
        # 00:00:30 IST = 18:30:30 UTC (previous day)
        scheduler.add_job(
            send_status_summary_email,
            CronTrigger(hour='0,6,12,18', minute=30, second=30, timezone=UTC_TZ),
            id='status_email',
            name='Send periodic status summary email',
        )
        
        # Job 8: Take PnL snapshot every hour
        # xx:35:00 IST = (xx-5):05:00 UTC
        scheduler.add_job(
            take_pnl_snapshot,
            CronTrigger(hour='*', minute=5, second=0, timezone=UTC_TZ),
            id='pnl_snapshot',
            name='Hourly PnL snapshot for equity curve',
        )
        
        # Also take an initial snapshot at startup
        scheduler.add_job(
            take_pnl_snapshot,
            trigger='date',
            next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2),
            id='pnl_snapshot_initial',
            name='Initial PnL snapshot',
        )
        
        scheduler.start()
        
        # ── Log scheduler status in IST for user visibility ──
        ist_now = now_ist()
        next_btc_job = scheduler.get_job('check_btc')
        next_ist_str = "N/A"
        if next_btc_job and next_btc_job.next_run_time:
            next_ist = next_btc_job.next_run_time.astimezone(IST_TZ)
            next_ist_str = next_ist.strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"IST time now: {ist_now.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"Next BTC candle check: {next_ist_str} IST")
            logger.info(f"(Every hour at xx:30:02 IST = :00:02 UTC)")
        else:
            logger.info(f"IST time now: {ist_now.strftime('%Y-%m-%d %H:%M:%S')}")
        
        log_event('INFO', 'main',
                  f'Scheduler started. IST={ist_now.strftime("%Y-%m-%d %H:%M:%S")}. '
                  f'Next BTC check={next_ist_str} IST')
        logger.info("Scheduler started with jobs: BTC check, position monitor, PnL snapshot, weekly scan")
        
        # Store scheduler reference on app
        app.state.scheduler = scheduler
        
    except Exception as e:
        log_event('ERROR', 'main', f"Failed to start scheduler: {e}")
        logger.error(f"Failed to start scheduler: {e}")


def check_btc_candle():
    """Check BTC candle for triggers. Runs every hour at xx:30:02 IST.
    
    SAFETY: Entire function wrapped in try/except. If ANY step fails,
    the error is logged and the scheduler continues running — the job
    never crashes the scheduler or the main app.
    """
    try:
        from backend.api.binance import is_ip_banned, get_ban_info
        
        # ── Skip if Binance IP is banned ──
        if is_ip_banned():
            ban_info = get_ban_info()
            log_event('WARNING', 'main',
                      f'BTC check skipped: Binance IP banned for {ban_info["remaining"]}s more')
            return
        
        try:
            # Always check daily reset at start of each cycle
            from backend.state.state_manager import RiskState
            RiskState.check_and_reset_daily()
            
            signal = signal_generator.check_trigger()
            if signal:
                log_event('INFO', 'main',
                          f"Signal generated: {signal.side} BTC={signal.btc_return_pct:+.2f}%")
                # Execute signal through trading engine
                entry_result = entry_manager.execute_signal(signal)
                entries = len(entry_result.get('entries', []))
                failed = len(entry_result.get('failed', []))
                log_event('INFO', 'main',
                          f"Signal execution: {entries} entered, {failed} failed")
                
                # Send email alert
                notifier = get_notifier()
                if notifier.is_configured and entries > 0:
                    notifier.send_trade_entry(
                        signal_side=signal.side,
                        btc_return_pct=signal.btc_return_pct,
                        entries=entry_result.get('entries', []),
                        failed=entry_result.get('failed', []),
                    )
        except Exception as e:
            log_event('ERROR', 'main', f"BTC check failed: {e}")
            # Send error alert
            notifier = get_notifier()
            if notifier.is_configured:
                notifier.send_error_alert('main', f"BTC check failed: {e}")
    except Exception as e:
        # Absolute last resort — never let any crash escape the job
        log_event('ERROR', 'main', f"BTC check CRASHED (scheduler-safe): {e}")


def monitor_positions():
    """Monitor open positions. Runs every ~5 minutes.
    
    SAFETY: Entire function wrapped in try/except. If ANY step fails,
    the error is logged and the scheduler continues running.
    """
    try:
        from backend.state.state_manager import PositionState, RiskState
        from backend.api.binance import is_ip_banned, get_ban_info
        
        # ── Skip if Binance IP is banned ──
        if is_ip_banned():
            ban_info = get_ban_info()
            log_event('WARNING', 'main',
                      f'Monitor skipped: Binance IP banned for {ban_info["remaining"]}s more')
            return
        
        # Check daily reset
        RiskState.check_and_reset_daily()
        
        # Run reconciliation first (catch any state drift)
        recon_result = reconciliation.reconcile_all()
        if recon_result.get('issues_found', 0) > 0:
            log_event('INFO', 'main',
                      f"Reconciliation: {recon_result['issues_found']} issues, "
                      f"{recon_result['issues_fixed']} fixed")
        
        if not PositionState.is_in_trade():
            return  # No open positions
        
        # Check TP/SL and handle exits for all open positions
        exit_events = exit_manager.check_all_positions()
        if exit_events:
            for ev in exit_events:
                log_event('INFO', 'main',
                          f"Exit event: {ev['symbol']} - {ev['type']} "
                          f"PnL=${ev.get('pnl_usdt', 0):+.2f}")
                # Send email alert for exit events
                notifier = get_notifier()
                if notifier.is_configured:
                    notifier.send_trade_exit(
                        exit_type=ev['type'],
                        symbol=ev['symbol'],
                        side=ev.get('side', 'LONG'),
                        entry_price=ev.get('entry_price', 0),
                        exit_price=ev.get('exit_price', 0),
                        pnl_usdt=ev.get('pnl_usdt', 0),
                        pnl_pct=ev.get('pnl_pct', 0),
                        exit_time=ev.get('exit_time', ''),
                    )
    except Exception as e:
        log_event('ERROR', 'main', f"Monitor positions CRASHED (scheduler-safe): {e}")


def daily_reset():
    """Reset daily counters. Runs at 00:01 IST every day."""
    try:
        from backend.state.state_manager import RiskState
        RiskState.check_and_reset_daily()
        log_event('INFO', 'main', 'Daily reset completed')
    except Exception as e:
        log_event('ERROR', 'main', f"Daily reset CRASHED (scheduler-safe): {e}")


def run_weekly_scan_job():
    """Run the weekly correlation scan."""
    try:
        log_event('INFO', 'main', 'Starting weekly correlation scan...')
        result = data_fetcher.run_weekly_scan()
        log_event('INFO', 'main',
                  f"Weekly scan: {result.get('scanned', 0)} scanned, "
                  f"{result.get('top_coins', [])}")
        return result
    except Exception as e:
        log_event('ERROR', 'main', f"Weekly scan CRASHED (scheduler-safe): {e}")
        return {'success': False, 'error': str(e)}


def run_weekly_scan_if_needed():
    """Run scan on startup if needed (e.g., first deploy)."""
    try:
        from backend.state.state_manager import WeeklyScanState
        if WeeklyScanState.needs_scan():
            log_event('INFO', 'main', 'No scan for this week, running initial scan...')
            run_weekly_scan_job()
    except Exception as e:
        log_event('ERROR', 'main', f"Initial scan check CRASHED (scheduler-safe): {e}")


def _check_orphan_positions():
    """Check for orphan positions on startup (called during lifespan)."""
    try:
        orphans = reconciliation.check_for_orphan_entries()
        if orphans:
            symbols = [o['symbol'] for o in orphans]
            log_event('INFO', 'main',
                      f"Found {len(orphans)} orphan position(s) from previous session: {symbols}")
            # Send orphan alert
            notifier = get_notifier()
            if notifier.is_configured:
                notifier.send_error_alert(
                    'reconciliation',
                    f"Found {len(orphans)} orphan positions from previous session",
                    context=f"Symbols: {', '.join(symbols)}",
                )
        else:
            log_event('INFO', 'main', 'No orphan positions found')
    except Exception as e:
        log_event('WARNING', 'main', f'Orphan check failed: {e}')


def _deferred_orphan_check():
    """Deferred orphan check that runs 5s after scheduler starts."""
    log_event('INFO', 'main', 'Running deferred orphan position check...')
    _check_orphan_positions()


def send_status_summary_email():
    """Send periodic status summary email (every 6 hours)."""
    try:
        from backend.state.state_manager import get_bot_status
        notifier = get_notifier()
        if not notifier.is_configured:
            return
        status = get_bot_status()
        status['health'] = 'ok'
        status['btc_current'] = get_btc_price()
        notifier.send_status_summary(status)
    except Exception as e:
        log_event('WARNING', 'main', f'Status summary email failed: {e}')


def take_pnl_snapshot():
    """Take a PnL snapshot for the equity curve chart.
    Runs every hour and at startup.
    
    SAFETY: Already had try/except, but now also catches critical failures.
    """
    try:
        from backend.state.state_manager import get_bot_status
        from backend.database.db import get_trade_stats, save_pnl_snapshot
        stats = get_trade_stats()
        status = get_bot_status()
        save_pnl_snapshot(
            total_pnl=stats.get('total_pnl', 0),
            today_pnl=status.get('daily_pnl', 0) or stats.get('today_pnl', 0),
            total_trades=stats.get('total_trades', 0),
            in_trade=status.get('in_trade', False),
        )
        logger.debug(f"PnL snapshot saved: total=${stats.get('total_pnl', 0):.2f}")
    except Exception as e:
        logger.warning(f"PnL snapshot failed: {e}")


# ─── API Endpoints ─────────────────────────────────────────

@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    """Health check endpoint (used by UptimeRobot to keep Render alive).
    
    Supports both GET and HEAD methods (UptimeRobot uses HEAD).
    CRITICAL: This endpoint MUST NEVER return 500. If anything fails
    (DB locked, state unavailable), it returns a degraded status instead
    of crashing. Docker HEALTHCHECK and UptimeRobot rely on this.
    """
    try:
        in_trade = len(get_open_trades()) > 0
    except Exception:
        in_trade = False
    
    status = "degraded" if not _startup_healthy else "ok"
    
    # Log health check pings for visibility in Render logs
    logger.debug(f"Health check: {status} | uptime={int((datetime.now(timezone.utc) - _bot_started_at).total_seconds())}s")
    
    return {
        "status": status,
        "healthy": _startup_healthy,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": int((datetime.now(timezone.utc) - _bot_started_at).total_seconds()),
        "in_trade": in_trade,
        "version": "1.0.0",
        "startup_errors": _startup_errors if _startup_errors else None,
    }


@app.get("/api/status")
def api_status():
    """Get full bot status for dashboard."""
    try:
        status = get_bot_status()
        status['health'] = 'ok'
        status['btc_current'] = get_btc_price()
        return status
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/stats")
def api_stats():
    """Get trading statistics."""
    try:
        stats = get_trade_stats()
        return stats
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/trades")
def api_trades(limit: int = 50):
    """Get recent trades."""
    try:
        trades = get_recent_trades(limit)
        return {"trades": trades, "count": len(trades)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/logs")
def api_logs(level: str = None, limit: int = 50):
    """Get recent logs."""
    try:
        logs = get_recent_logs(level=level, limit=limit)
        return {"logs": logs, "count": len(logs)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/config")
def api_config():
    """Get current configuration (safe values only)."""
    from backend.config import (
        BTC_TRIGGER_PCT, TP_PCT, SL_PCT, WINDOW_BARS,
        POSITION_SIZE_USDT, MAX_COINS_PER_TRADE,
        MAX_DAILY_LOSS_USDT, FIXED_COINS,
    )
    from backend.state.state_manager import WeeklyScanState
    return {
        "btc_trigger_pct": BTC_TRIGGER_PCT,
        "tp_pct": TP_PCT,
        "sl_pct": SL_PCT,
        "window_bars": WINDOW_BARS,
        "position_size_usdt": POSITION_SIZE_USDT,
        "max_coins_per_trade": MAX_COINS_PER_TRADE,
        "max_daily_loss_usdt": MAX_DAILY_LOSS_USDT,
        "fixed_coins": FIXED_COINS,
        "trading_coins": WeeklyScanState.get_trading_coins(),
        "demo_api_configured": bool(BINANCE_DEMO_KEY),
        "smtp_configured": bool(SMTP_EMAIL),
    }


@app.post("/api/scan")
def trigger_scan():
    """Manually trigger a weekly scan."""
    result = run_weekly_scan_job()
    return result


@app.get("/api/trading")
def api_trading():
    """Get trading engine status."""
    from backend.trading.risk_manager import RiskManager
    rm = RiskManager()
    return rm.get_risk_status()


@app.post("/api/reset-state")
def reset_state():
    """Reset all bot state (for testing)."""
    from backend.state.state_manager import reset_all_state
    reset_all_state()
    return {"status": "reset"}


@app.post("/api/test-email")
def test_email():
    """Send a test email to verify SMTP configuration."""
    notifier = get_notifier()
    if not notifier.is_configured:
        return {"status": "error", "message": "SMTP not configured. Set SMTP_EMAIL, SMTP_PASSWORD, SMTP_TO in .env"}
    ok = notifier.send_test()
    if ok:
        return {"status": "ok", "message": "Test email sent successfully"}
    else:
        return {"status": "error", "message": "Failed to send test email — check logs for details"}


@app.post("/api/status-email")
def status_email():
    """Send a manual status summary email."""
    from backend.state.state_manager import get_bot_status
    notifier = get_notifier()
    if not notifier.is_configured:
        return {"status": "error", "message": "SMTP not configured"}
    status = get_bot_status()
    status['health'] = 'ok'
    status['btc_current'] = get_btc_price()
    ok = notifier.send_status_summary(status)
    return {"status": "ok" if ok else "error"}


# ─── Performance Analytics API ───────────────────────────

@app.get("/api/equity-curve")
def api_equity_curve(limit: int = 200):
    """Get PnL history for the equity curve chart."""
    try:
        history = get_pnl_history(limit=limit)
        return {"points": history, "count": len(history)}
    except Exception as e:
        logger.error(f"Equity curve fetch failed: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/pnl-breakdown")
def api_pnl_breakdown(days: int = 30):
    """Get daily PnL breakdown by coin for the last N days."""
    try:
        from backend.database.db import get_pnl_breakdown_by_coin
        breakdown = get_pnl_breakdown_by_coin(days=days)
        return {"breakdown": breakdown}
    except Exception as e:
        logger.error(f"PnL breakdown fetch failed: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/trade-journal")
def api_trade_journal(
    limit: int = 100,
    offset: int = 0,
    coin: str = "",
    side: str = "",
    exit_reason: str = "",
    date_from: str = "",
    date_to: str = "",
):
    """Get trade journal with advanced filtering."""
    try:
        from backend.database.db import get_trade_journal
        result = get_trade_journal(
            limit=limit,
            offset=offset,
            coin=coin or None,
            side=side or None,
            exit_reason=exit_reason or None,
            date_from=date_from or None,
            date_to=date_to or None,
        )
        return result
    except Exception as e:
        logger.error(f"Trade journal fetch failed: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ─── Keep-Alive Thread ───────────────────────────────────────

def _start_keepalive_thread():
    """Start a daemon thread that pings our own public URL every 10 minutes.
    
    This serves as a SECONDARY keep-alive mechanism alongside external
    monitors like UptimeRobot. As long as the app is running, this
    self-ping prevents Render's 15-minute spin-down even if the external
    monitor misses a few checks.
    
    The thread is a daemon thread — it won't block shutdown.
    Uses urllib (standard library) — no extra dependencies.
    """
    if not IS_RENDER or not RENDER_EXTERNAL_URL:
        logger.info("Keep-alive: disabled (requires RENDER_EXTERNAL_URL)")
        return
    
    health_url = f"{RENDER_EXTERNAL_URL}/health"
    logger.info(f"Keep-alive: pinging {health_url} every 600s")
    
    def _ping_loop():
        while True:
            try:
                time.sleep(600)  # 10 minutes (under Render's 15-min threshold)
                req = urllib.request.Request(health_url, method="GET")
                with urllib.request.urlopen(req, timeout=15) as resp:
                    status = resp.status
                if status == 200:
                    logger.debug(f"Keep-alive ping: {health_url} \u2192 {status}")
                else:
                    logger.warning(f"Keep-alive ping: {health_url} \u2192 {status}")
            except urllib.error.URLError as e:
                logger.debug(f"Keep-alive ping failed (transient): {e.reason}")
            except Exception as e:
                logger.debug(f"Keep-alive ping failed: {e}")
    
    thread = threading.Thread(target=_ping_loop, daemon=True, name="keepalive-ping")
    thread.start()
    logger.info("Keep-alive thread running")


# ─── Helper ────────────────────────────────────────────────

def get_btc_price() -> float:
    """Get current BTC price.
    
    PRIMARY: Uses WebSocket stream (btcusdt@ticker) — zero REST calls,
    live updates every ~250ms, no API weight consumed.
    FALLBACK: If WebSocket not connected yet, uses REST with 60s cache.
    When Binance IP is banned, returns last known price.
    """
    global _btc_price_cache
    
    # ── Try WebSocket first (no API weight, real-time) ──
    ws_price = ws.get_btc_price()
    if ws_price > 0:
        # Update cache so banned fallback has fresh data
        _btc_price_cache['price'] = ws_price
        _btc_price_cache['timestamp'] = time.time()
        return ws_price
    
    # ── Fallback to REST + cache ──
    from backend.api.binance import is_ip_banned
    if is_ip_banned():
        return _btc_price_cache.get('price', 0.0)
    
    if time.time() - _btc_price_cache['timestamp'] < 60:
        return _btc_price_cache['price']
    
    try:
        from backend.api.binance import get_data_client
        price = get_data_client().get_ticker_price('BTCUSDT')
        _btc_price_cache['price'] = price
        _btc_price_cache['timestamp'] = time.time()
        return price
    except Exception:
        return _btc_price_cache.get('price', 0.0)


# ─── Serve Frontend ──────────────────────────────────────

STATIC_DIR = Path(__file__).resolve().parent / "static"
_frontend_available = STATIC_DIR.exists()

if _frontend_available:
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="static-assets")
    logger.info(f"Frontend built at {STATIC_DIR}")
else:
    logger.warning(f"Frontend NOT BUILT — run 'cd frontend && npm run build' to build it")


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def serve_index():
    """Serve the frontend SPA, or return a health-like JSON for uptime monitors.
    
    Supports both GET and HEAD methods (UptimeRobot uses HEAD).
    Always returns 200 so uptime monitors never see 405.
    """
    # Log root pings at DEBUG level for visibility
    logger.debug("Root route ping")
    if _frontend_available:
        return FileResponse(str(STATIC_DIR / "index.html"))
    # Always return 200 so UptimeRobot / Render keepalive never sees 405
    return JSONResponse(content={
        "status": "ok",
        "service": "BTC Leads Trading Bot",
        "version": "1.0.0",
        "frontend": "not built",
        "health_endpoint": "/health",
    })


if _frontend_available:
    # Catch-all: serve index.html for any non-API, non-health path (SPA routing)
    @app.api_route("/{path:path}", methods=["GET"])
    async def catch_all(path: str):
        # Skip API, health, assets, and favicon routes
        if (path.startswith("api/") or path == "health" 
            or path.startswith("assets/") or path == "favicon.ico"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        return FileResponse(str(STATIC_DIR / "index.html"))

    if IS_RENDER and RENDER_EXTERNAL_URL:
        logger.info(f"Frontend URL: {RENDER_EXTERNAL_URL}/")
    else:
        logger.info(f"Frontend URL: http://{HOST}:{PORT}/")


# ─── Entry Point ──────────────────────────────────────────

def get_application() -> FastAPI:
    """Return the FastAPI application."""
    return app


if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting server on {HOST}:{PORT}")
    uvicorn.run(
        "backend.main:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level=LOG_LEVEL.lower(),
    )
