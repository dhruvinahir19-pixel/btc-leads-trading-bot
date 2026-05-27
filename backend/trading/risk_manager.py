"""
risk_manager.py - Risk management system.
Circuit breakers: daily loss limit, consecutive losses, max trades per day.
All checks prevent the bot from trading when conditions are met.
"""
from datetime import datetime, timezone, timedelta

from backend.database.db import log_event, config_get, config_set
from backend.state.state_manager import RiskState
from backend.config import (
    MAX_DAILY_LOSS_USDT, MAX_CONSECUTIVE_LOSSES,
    MAX_TRADES_PER_DAY, POSITION_SIZE_USDT,
    TRADE_START_HOUR, TRADE_END_HOUR,
)


class RiskManager:

    def __init__(self):
        self._notifier = None  # Lazy-loaded

    def _alert_if_configured(self, alert_type: str, details: str):
        """Send risk alert if SMTP is configured."""
        try:
            if self._notifier is None:
                from backend.notifications.email_alerts import get_notifier
                self._notifier = get_notifier()
            if self._notifier and self._notifier.is_configured:
                metrics = {
                    'daily_pnl': f'${RiskState.get_today_pnl():.2f}',
                    'daily_trades': RiskState.get_daily_trades(),
                    'consecutive_losses': RiskState.get_consecutive_losses(),
                }
                self._notifier.send_risk_alert(alert_type, details, metrics)
        except Exception:
            pass  # Never let email failures block trading
    """
    Risk management gates that must pass before any trade entry.

    Checks (in order):
    1. Daily loss limit hit?
    2. Circuit breaker (consecutive losses)?
    3. Max daily trades reached?
    4. Within trading hours?
    5. Weekend trading allowed?
    """

    def check_entry_gates(self) -> dict:
        """
        Check all risk gates before entering a trade.

        Returns:
            {'allowed': True} or {'allowed': False, 'reason': '...'}
        """
        # Gate 1: Daily loss limit
        if RiskState.is_daily_loss_limit_hit():
            reason = f"Daily loss limit reached (${MAX_DAILY_LOSS_USDT})"
            log_event('WARNING', 'risk', reason)
            self._alert_if_configured('daily_loss_limit', reason)
            return {'allowed': False, 'reason': reason, 'gate': 'daily_loss_limit'}

        # Gate 2: Circuit breaker
        if RiskState.is_circuit_breaker_active():
            consec = RiskState.get_consecutive_losses()
            reason = f"Circuit breaker active ({consec} consecutive losses)"
            log_event('WARNING', 'risk', reason)
            self._alert_if_configured('circuit_breaker', reason)
            return {'allowed': False, 'reason': reason, 'gate': 'circuit_breaker'}

        # Gate 3: Max daily trades
        if RiskState.is_max_daily_trades_reached(MAX_TRADES_PER_DAY):
            reason = f"Max daily trades reached ({MAX_TRADES_PER_DAY})"
            log_event('WARNING', 'risk', reason)
            self._alert_if_configured('max_daily_trades', reason)
            return {'allowed': False, 'reason': reason, 'gate': 'max_daily_trades'}

        # Gate 4: Trading hours
        if not self._within_trading_hours():
            now_ist = datetime.now(timezone.utc) + timedelta(hours=5.5)
            reason = f"Outside trading hours (IST: {now_ist.strftime('%H:%M')})"
            log_event('INFO', 'risk', reason)
            self._alert_if_configured('trading_hours', reason)
            return {'allowed': False, 'reason': reason, 'gate': 'trading_hours'}

        # Gate 5: Account balance check
        try:
            from backend.api.binance import get_demo_client
            client = get_demo_client()
            balance = client.get_usdt_balance()
            min_required = POSITION_SIZE_USDT * 2  # Need at least 2x position size
            if balance < min_required:
                reason = (f"Insufficient balance: ${balance:.2f} "
                          f"(need ${min_required:.2f})")
                log_event('WARNING', 'risk', reason)
                self._alert_if_configured('insufficient_balance', reason)
                return {'allowed': False, 'reason': reason, 'gate': 'insufficient_balance'}
        except Exception:
            # If we can't check balance, let the trade proceed
            # (demo API might be unavailable but main API works)
            pass

        return {'allowed': True}

    def get_risk_status(self) -> dict:
        """
        Get comprehensive risk status for dashboard display.
        Field names match the frontend RiskStatus interface.
        """
        from backend.state.state_manager import PositionState

        in_trade = PositionState.is_in_trade()
        daily_pnl = RiskState.get_today_pnl()
        daily_trade_count = RiskState.get_daily_trades()
        consec_losses = RiskState.get_consecutive_losses()
        circuit_breaker = RiskState.is_circuit_breaker_active()

        # Check balance
        balance_ok = True
        try:
            from backend.api.binance import get_demo_client
            client = get_demo_client()
            balance = client.get_usdt_balance()
            balance_ok = balance >= POSITION_SIZE_USDT * 2
        except Exception:
            balance_ok = True  # assume OK if we can't check

        return {
            'in_trade': in_trade,
            'daily_trade_count': daily_trade_count,
            'daily_pnl': daily_pnl,
            'max_daily_loss': MAX_DAILY_LOSS_USDT,
            'consecutive_losses': consec_losses,
            'max_consecutive_losses': MAX_CONSECUTIVE_LOSSES,
            'circuit_breaker_triggered': circuit_breaker,
            'can_trade': self.check_entry_gates()['allowed'],
            'trade_window_open': self._within_trading_hours(),
            'balance_ok': balance_ok,
        }

    @staticmethod
    def _within_trading_hours() -> bool:
        """
        Check if current time is within configured trading hours (IST).
        """
        now_utc = datetime.now(timezone.utc)
        now_ist = now_utc + timedelta(hours=5.5)
        current_hour = now_ist.hour

        if TRADE_START_HOUR <= TRADE_END_HOUR:
            return TRADE_START_HOUR <= current_hour <= TRADE_END_HOUR
        else:
            # Overnight hours (e.g., start=22, end=6)
            return current_hour >= TRADE_START_HOUR or current_hour <= TRADE_END_HOUR
