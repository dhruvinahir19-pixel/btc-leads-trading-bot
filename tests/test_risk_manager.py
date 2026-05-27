"""
test_risk_manager.py — Tests for the RiskManager module.

Verifies:
- All 5 entry gates: daily loss, circuit breaker, max trades, trading hours, balance
- Edge cases: overnight hours, exactly at boundaries
- get_risk_status() output
- Risk alerts fire correctly
"""
import pytest
import os
from unittest.mock import patch, MagicMock, PropertyMock


class TestEntryGates:
    """Test each risk gate independently."""

    def test_entry_allowed_by_default(self, mock_demo_client, db_conn):
        from backend.trading.risk_manager import RiskManager
        rm = RiskManager()
        mock_demo_client.set_balance(1000.0)
        result = rm.check_entry_gates()
        assert result["allowed"] is True

    def test_gate_daily_loss_limit(self, db_conn):
        from backend.trading.risk_manager import RiskManager
        from backend.state.state_manager import RiskState
        from backend.config import MAX_DAILY_LOSS_USDT
        rm = RiskManager()
        # Create trades that exceed daily loss
        with patch.object(RiskState, 'is_daily_loss_limit_hit', return_value=True):
            result = rm.check_entry_gates()
            assert result["allowed"] is False
            assert result["gate"] == "daily_loss_limit"

    def test_gate_circuit_breaker(self, db_conn):
        from backend.trading.risk_manager import RiskManager
        from backend.state.state_manager import RiskState
        rm = RiskManager()
        with patch.object(RiskState, 'is_circuit_breaker_active', return_value=True):
            result = rm.check_entry_gates()
            assert result["allowed"] is False
            assert result["gate"] == "circuit_breaker"

    def test_gate_max_daily_trades(self, db_conn):
        from backend.trading.risk_manager import RiskManager
        from backend.state.state_manager import RiskState
        from backend.config import MAX_TRADES_PER_DAY
        rm = RiskManager()
        with patch.object(RiskState, 'is_max_daily_trades_reached', return_value=True):
            result = rm.check_entry_gates()
            assert result["allowed"] is False
            assert result["gate"] == "max_daily_trades"

    def test_gate_trading_hours_outside(self, db_conn):
        """Simulate being outside trading hours."""
        from backend.trading.risk_manager import RiskManager
        rm = RiskManager()
        from backend.config import TRADE_START_HOUR, TRADE_END_HOUR

        # Patch _within_trading_hours to return False
        with patch.object(RiskManager, '_within_trading_hours', return_value=False):
            result = rm.check_entry_gates()
            assert result["allowed"] is False
            assert result["gate"] == "trading_hours"

    def test_gate_insufficient_balance(self, mock_demo_client, db_conn):
        from backend.trading.risk_manager import RiskManager
        rm = RiskManager()
        mock_demo_client.set_balance(5.0)  # Very low balance
        with patch.object(RiskManager, '_within_trading_hours', return_value=True):
            result = rm.check_entry_gates()
            assert result["allowed"] is False
            assert result["gate"] == "insufficient_balance"


class TestCircuitBreaker:
    """Test circuit breaker behavior end-to-end."""

    def test_circuit_breaker_activates_after_consecutive_losses(self, db_conn):
        from backend.trading.risk_manager import RiskManager
        from backend.state.state_manager import RiskState
        from backend.config import MAX_CONSECUTIVE_LOSSES
        rm = RiskManager()
        for _ in range(MAX_CONSECUTIVE_LOSSES):
            RiskState.record_loss()
        assert RiskState.is_circuit_breaker_active() is True
        result = rm.check_entry_gates()
        assert result["allowed"] is False

    def test_circuit_breaker_resets_after_win(self, db_conn):
        from backend.state.state_manager import RiskState
        from backend.config import MAX_CONSECUTIVE_LOSSES
        for _ in range(MAX_CONSECUTIVE_LOSSES - 1):
            RiskState.record_loss()
        assert RiskState.is_circuit_breaker_active() is False
        RiskState.record_win()
        assert RiskState.get_consecutive_losses() == 0


class TestTradingHours:
    """Test trading hours logic."""

    def test_within_hours_normal(self):
        from backend.trading.risk_manager import RiskManager
        from backend.config import TRADE_START_HOUR, TRADE_END_HOUR
        # Default is 0-23, so should always be within hours
        assert TRADE_START_HOUR == 0
        assert TRADE_END_HOUR == 23
        result = RiskManager._within_trading_hours()
        assert result is True

    def test_outside_narrow_window(self):
        from backend.trading.risk_manager import RiskManager
        import backend.trading.risk_manager as risk_module
        from datetime import datetime, timezone, timedelta
        # Patch the imported constants in risk_manager module
        with patch.object(risk_module, 'TRADE_START_HOUR', 9), \
             patch.object(risk_module, 'TRADE_END_HOUR', 17), \
             patch('backend.trading.risk_manager.datetime') as mock_dt:
            mock_now = datetime(2024, 1, 15, 20, 0, 0, tzinfo=timezone.utc)
            mock_dt.now.return_value = mock_now
            mock_dt.timezone = timezone
            # IST = UTC + 5:30, so 20:00 UTC = 01:30 IST next day
            # With TRADE_START_HOUR=9 and TRADE_END_HOUR=17, hour 1 is outside
            result = RiskManager._within_trading_hours()
            assert result is False

    def test_overnight_hours(self):
        """Test overnight window (e.g., 22:00 to 06:00)."""
        from backend.trading.risk_manager import RiskManager
        import backend.trading.risk_manager as risk_module
        from datetime import datetime, timezone
        # 23:00 UTC = 04:30 IST next day - should be within 22-06
        with patch.object(risk_module, 'TRADE_START_HOUR', 22), \
             patch.object(risk_module, 'TRADE_END_HOUR', 6), \
             patch('backend.trading.risk_manager.datetime') as mock_dt:
            mock_now = datetime(2024, 1, 15, 23, 0, 0, tzinfo=timezone.utc)
            mock_dt.now.return_value = mock_now
            mock_dt.timezone = timezone
            result = RiskManager._within_trading_hours()
            assert result is True

    def test_at_exact_boundary_start(self):
        """Test exactly at start hour boundary."""
        from backend.trading.risk_manager import RiskManager
        import backend.trading.risk_manager as risk_module
        from datetime import datetime, timezone, timedelta
        # 03:30 UTC = 09:00 IST
        with patch.object(risk_module, 'TRADE_START_HOUR', 9), \
             patch.object(risk_module, 'TRADE_END_HOUR', 17), \
             patch('backend.trading.risk_manager.datetime') as mock_dt:
            mock_now = datetime(2024, 1, 15, 3, 30, 0, tzinfo=timezone.utc)
            mock_dt.now.return_value = mock_now
            mock_dt.timezone = timezone
            result = RiskManager._within_trading_hours()
            assert result is True


class TestRiskStatus:
    """Test get_risk_status() output."""

    def test_risk_status_structure(self, mock_demo_client, db_conn):
        from backend.trading.risk_manager import RiskManager
        rm = RiskManager()
        status = rm.get_risk_status()
        expected_keys = {"in_trade", "daily_trade_count", "daily_pnl",
                         "max_daily_loss", "consecutive_losses",
                         "max_consecutive_losses", "circuit_breaker_triggered",
                         "can_trade", "trade_window_open", "balance_ok"}
        assert expected_keys.issubset(set(status.keys()))

    def test_risk_status_can_trade_default(self, mock_demo_client, db_conn):
        from backend.trading.risk_manager import RiskManager
        rm = RiskManager()
        mock_demo_client.set_balance(1000.0)
        status = rm.get_risk_status()
        assert status["can_trade"] is True
        assert status["balance_ok"] is True
