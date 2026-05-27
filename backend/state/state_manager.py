"""
state_manager.py - Persistent state tracking for the trading bot.
Tracks: current position, last processed candle, daily PnL, consecutive losses.
All state survives restarts via the database.
"""
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.database.db import (
    config_get, config_set, get_open_trades,
    get_daily_pnl, is_daily_loss_limit_hit,
    is_candle_processed, mark_candle_processed,
    get_last_processed_candle,
)
from backend.config import (
    POSITION_SIZE_USDT, MAX_COINS_PER_TRADE,
    MAX_CONSECUTIVE_LOSSES, MAX_DAILY_LOSS_USDT,
    FIXED_COINS,
)


class PositionState:
    """
    Tracks the current trading position.
    All state is stored in the database 'config' table for persistence.
    """
    
    @staticmethod
    def is_in_trade() -> bool:
        """Check if there's an active position."""
        trades = get_open_trades()
        return len(trades) > 0
    
    @staticmethod
    def get_active_trades() -> list:
        """Get all currently open trades."""
        return get_open_trades()
    
    @staticmethod
    def get_last_processed_btc_candle() -> Optional[str]:
        """Get the last BTC candle that was checked for triggers."""
        return get_last_processed_candle('BTCUSDT')
    
    @staticmethod
    def mark_btc_candle_processed(timestamp_ist: str):
        """Mark a BTC candle as processed (prevents duplicate triggers)."""
        mark_candle_processed('BTCUSDT', timestamp_ist)
    
    @staticmethod
    def is_btc_candle_processed(timestamp_ist: str) -> bool:
        """Check if a BTC candle was already processed."""
        return is_candle_processed('BTCUSDT', timestamp_ist)


class RiskState:
    """
    Tracks risk metrics: daily PnL, consecutive losses, circuit breakers.
    """
    
    @staticmethod
    def get_today_pnl() -> float:
        """Get today's PnL in USDT."""
        return get_daily_pnl()
    
    @staticmethod
    def is_daily_loss_limit_hit() -> bool:
        """Check if today's losses exceed the daily limit."""
        return is_daily_loss_limit_hit(MAX_DAILY_LOSS_USDT)
    
    @staticmethod
    def get_consecutive_losses() -> int:
        """Get the number of consecutive losses."""
        val = config_get("consecutive_losses", "0")
        return int(val)
    
    @staticmethod
    def record_loss():
        """Record a loss and increment consecutive counter."""
        current = RiskState.get_consecutive_losses()
        config_set("consecutive_losses", str(current + 1))
    
    @staticmethod
    def record_win():
        """Record a win and reset consecutive counter."""
        config_set("consecutive_losses", "0")
    
    @staticmethod
    def is_circuit_breaker_active() -> bool:
        """Check if circuit breaker is triggered (too many consecutive losses)."""
        consec = RiskState.get_consecutive_losses()
        return consec >= MAX_CONSECUTIVE_LOSSES
    
    @staticmethod
    def reset_circuit_breaker():
        """Reset circuit breaker (e.g., at start of new day)."""
        config_set("consecutive_losses", "0")
        config_set("circuit_breaker_date", "")
    
    @staticmethod
    def check_and_reset_daily():
        """Check if a new day has started and reset daily counters if so."""
        now_utc = datetime.now(timezone.utc)
        ist_now = now_utc + timedelta(hours=5.5)
        today_str = ist_now.strftime("%Y-%m-%d")
        
        last_date = config_get("last_trading_date", "")
        if last_date != today_str:
            # New day - reset daily counters
            config_set("last_trading_date", today_str)
            config_set("daily_trades", "0")
            # Don't reset consecutive losses - those persist across days
    
    @staticmethod
    def get_daily_trades() -> int:
        """Get the number of trades today."""
        val = config_get("daily_trades", "0")
        return int(val)
    
    @staticmethod
    def increment_daily_trades():
        """Increment the daily trade counter."""
        current = RiskState.get_daily_trades()
        config_set("daily_trades", str(current + 1))
    
    @staticmethod
    def is_max_daily_trades_reached(max_trades: int = 10) -> bool:
        """Check if max daily trades reached."""
        return RiskState.get_daily_trades() >= max_trades


class WeeklyScanState:
    """
    Tracks the weekly coin scan state.
    """
    
    @staticmethod
    def get_trading_coins() -> list:
        """Get the current list of trading coins (fixed + dynamic)."""
        dynamic = config_get("dynamic_coins", "[]")
        try:
            dynamic_coins = json.loads(dynamic)
        except (json.JSONDecodeError, TypeError):
            dynamic_coins = []
        
        all_coins = list(FIXED_COINS) + dynamic_coins
        return all_coins
    
    @staticmethod
    def set_dynamic_coins(coins: list):
        """Save the dynamically selected coins from weekly scan."""
        config_set("dynamic_coins", json.dumps(coins))
    
    @staticmethod
    def needs_scan() -> bool:
        """
        Check if a weekly scan is needed.
        Returns True if no scan result for this week.
        """
        from backend.database.db import get_latest_scan
        scan = get_latest_scan()
        if not scan:
            return True
        
        # Check if the latest scan is from this week
        now_utc = datetime.now(timezone.utc)
        ist_now = now_utc + timedelta(hours=5.5)
        this_monday = (ist_now - timedelta(days=ist_now.weekday())).strftime("%Y-%m-%d")
        
        return scan['week_start'] != this_monday


# ─── Convenience Functions ─────────────────────────────────

def get_bot_status() -> dict:
    """
    Get comprehensive bot status for dashboard API.
    """
    active_trades = PositionState.get_active_trades()
    
    return {
        'in_trade': len(active_trades) > 0,
        'active_trades': len(active_trades),
        'trade_details': active_trades,
        'today_pnl': RiskState.get_today_pnl(),
        'daily_loss_limit_hit': RiskState.is_daily_loss_limit_hit(),
        'consecutive_losses': RiskState.get_consecutive_losses(),
        'circuit_breaker_active': RiskState.is_circuit_breaker_active(),
        'daily_trades': RiskState.get_daily_trades(),
        'trading_coins': WeeklyScanState.get_trading_coins(),
        'last_processed_candle': PositionState.get_last_processed_btc_candle(),
        'needs_scan': WeeklyScanState.needs_scan(),
    }


def reset_all_state():
    """Reset all state (for testing or manual reset)."""
    RiskState.reset_circuit_breaker()
    config_set("daily_trades", "0")
    config_set("dynamic_coins", "[]")
    config_set("last_trading_date", "")
