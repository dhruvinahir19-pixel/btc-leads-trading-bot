"""
test_state_manager.py — Tests for state management module.

Verifies:
- PositionState tracking (in_trade, active trades, candle processing)
- RiskState tracking (daily PnL, consecutive losses, circuit breaker)
- WeeklyScanState (trading coins, dynamic coin merging, scan-needed detection)
- Edge cases: no trades, state reset, daily boundary
"""
import pytest


class TestPositionState:
    """Test PositionState class."""

    def test_not_in_trade_by_default(self, db_conn):
        from backend.state.state_manager import PositionState
        assert PositionState.is_in_trade() is False

    def test_in_trade_with_open_trades(self, db_conn):
        from backend.state.state_manager import PositionState
        from tests.conftest import seed_trade
        seed_trade(db_conn, status="open", coin="DOGEUSDT", entry_price=0.12,
                   tp_price=0.1212, sl_price=0.1194, position_size=10.0)
        assert PositionState.is_in_trade() is True

    def test_not_in_trade_after_close(self, db_conn):
        from backend.state.state_manager import PositionState
        from tests.conftest import seed_trade
        from backend.database.db import trade_close
        tid = seed_trade(db_conn, status="open", coin="DOGEUSDT", entry_price=0.12,
                         tp_price=0.1212, sl_price=0.1194, position_size=10.0)
        trade_close(tid, exit_price=0.1212, exit_time="2024-01-15 18:00:00",
                     pnl_usdt=0.10, pnl_pct=1.0, exit_reason="tp_hit")
        assert PositionState.is_in_trade() is False

    def test_get_active_trades(self, db_conn):
        from backend.state.state_manager import PositionState
        from tests.conftest import seed_trade
        seed_trade(db_conn, status="open", coin="DOGEUSDT", entry_price=0.12,
                   tp_price=0.1212, sl_price=0.1194, position_size=10.0)
        seed_trade(db_conn, status="open", coin="ETHUSDT", entry_price=3450,
                   tp_price=3500, sl_price=3400, position_size=10.0)
        trades = PositionState.get_active_trades()
        assert len(trades) == 2

    def test_btc_candle_processing(self, db_conn):
        from backend.state.state_manager import PositionState
        assert PositionState.is_btc_candle_processed("2024-01-15 17:30:00") is False
        PositionState.mark_btc_candle_processed("2024-01-15 17:30:00")
        assert PositionState.is_btc_candle_processed("2024-01-15 17:30:00") is True

    def test_duplicate_candle_prevention(self, db_conn):
        from backend.state.state_manager import PositionState
        PositionState.mark_btc_candle_processed("2024-01-15 17:30:00")
        PositionState.mark_btc_candle_processed("2024-01-15 17:30:00")
        assert PositionState.is_btc_candle_processed("2024-01-15 17:30:00") is True

    def test_different_candles_independent(self, db_conn):
        from backend.state.state_manager import PositionState
        PositionState.mark_btc_candle_processed("2024-01-15 17:30:00")
        assert PositionState.is_btc_candle_processed("2024-01-15 18:30:00") is False


class TestRiskState:
    """Test RiskState class."""

    def test_default_no_losses(self, db_conn):
        from backend.state.state_manager import RiskState
        assert RiskState.get_consecutive_losses() == 0

    def test_record_loss(self, db_conn):
        from backend.state.state_manager import RiskState
        RiskState.record_loss()
        assert RiskState.get_consecutive_losses() == 1
        RiskState.record_loss()
        assert RiskState.get_consecutive_losses() == 2

    def test_record_win_resets_losses(self, db_conn):
        from backend.state.state_manager import RiskState
        RiskState.record_loss()
        RiskState.record_loss()
        RiskState.record_win()
        assert RiskState.get_consecutive_losses() == 0

    def test_circuit_breaker_threshold(self, db_conn):
        from backend.state.state_manager import RiskState
        from backend.config import MAX_CONSECUTIVE_LOSSES
        assert RiskState.is_circuit_breaker_active() is False
        for _ in range(MAX_CONSECUTIVE_LOSSES):
            RiskState.record_loss()
        assert RiskState.is_circuit_breaker_active() is True

    def test_circuit_breaker_reset(self, db_conn):
        from backend.state.state_manager import RiskState
        for _ in range(5):
            RiskState.record_loss()
        RiskState.reset_circuit_breaker()
        assert RiskState.is_circuit_breaker_active() is False
        assert RiskState.get_consecutive_losses() == 0

    def test_daily_trades_default(self, db_conn):
        from backend.state.state_manager import RiskState
        assert RiskState.get_daily_trades() == 0

    def test_daily_trades_increment(self, db_conn):
        from backend.state.state_manager import RiskState
        RiskState.increment_daily_trades()
        assert RiskState.get_daily_trades() == 1
        RiskState.increment_daily_trades()
        assert RiskState.get_daily_trades() == 2

    def test_max_daily_trades(self, db_conn):
        from backend.state.state_manager import RiskState
        from backend.config import MAX_TRADES_PER_DAY
        assert RiskState.is_max_daily_trades_reached(MAX_TRADES_PER_DAY) is False
        for _ in range(MAX_TRADES_PER_DAY):
            RiskState.increment_daily_trades()
        assert RiskState.is_max_daily_trades_reached(MAX_TRADES_PER_DAY) is True

    def test_daily_loss_limit(self, db_conn):
        from backend.state.state_manager import RiskState
        from backend.config import MAX_DAILY_LOSS_USDT
        # With no trades, limit should not be hit
        assert RiskState.is_daily_loss_limit_hit() is False

    def test_today_pnl_returns_float(self, db_conn):
        from backend.state.state_manager import RiskState
        pnl = RiskState.get_today_pnl()
        assert isinstance(pnl, float)


class TestWeeklyScanState:
    """Test WeeklyScanState class."""

    def test_trading_coins_defaults_to_fixed(self, db_conn):
        from backend.state.state_manager import WeeklyScanState
        from backend.config import FIXED_COINS
        coins = WeeklyScanState.get_trading_coins()
        for c in FIXED_COINS:
            assert c in coins

    def test_set_and_get_dynamic_coins(self, db_conn):
        from backend.state.state_manager import WeeklyScanState
        WeeklyScanState.set_dynamic_coins(["FARTCOINUSDT", "PEPEUSDT"])
        coins = WeeklyScanState.get_trading_coins()
        assert "FARTCOINUSDT" in coins
        assert "PEPEUSDT" in coins

    def test_dynamic_coins_merge_with_fixed(self, db_conn):
        from backend.state.state_manager import WeeklyScanState
        from backend.config import FIXED_COINS
        WeeklyScanState.set_dynamic_coins(["FARTCOINUSDT"])
        coins = WeeklyScanState.get_trading_coins()
        for c in FIXED_COINS:
            assert c in coins
        assert "FARTCOINUSDT" in coins
        # Order: fixed first, then dynamic
        assert coins[:len(FIXED_COINS)] == FIXED_COINS

    def test_needs_scan_when_no_scan(self, db_conn):
        from backend.state.state_manager import WeeklyScanState
        assert WeeklyScanState.needs_scan() is True

    def test_needs_scan_after_save(self, db_conn):
        from backend.state.state_manager import WeeklyScanState
        from backend.database.db import save_scan_result
        from datetime import datetime, timezone, timedelta
        ist_now = datetime.now(timezone.utc) + timedelta(hours=5.5)
        this_monday = (ist_now - timedelta(days=ist_now.weekday())).strftime("%Y-%m-%d")
        save_scan_result(this_monday, ist_now.strftime("%Y-%m-%d %H:%M:%S"),
                         100, 50, [{"symbol": "ETHUSDT", "correlation": 0.75, "beta": 1.5}],
                         ["ETHUSDT"])
        assert WeeklyScanState.needs_scan() is False


class TestGetBotStatus:
    """Test the convenience get_bot_status function."""

    def test_get_bot_status_default(self, db_conn):
        from backend.state.state_manager import get_bot_status
        status = get_bot_status()
        assert status["in_trade"] is False
        assert status["active_trades"] == 0
        assert "today_pnl" in status
        assert "circuit_breaker_active" in status
        assert "trading_coins" in status

    def test_get_bot_status_with_trades(self, db_conn):
        from backend.state.state_manager import get_bot_status
        from tests.conftest import seed_trade
        seed_trade(db_conn, status="open", coin="DOGEUSDT", entry_price=0.12,
                   tp_price=0.1212, sl_price=0.1194, position_size=10.0)
        status = get_bot_status()
        assert status["in_trade"] is True
        assert status["active_trades"] == 1

    def test_reset_all_state(self, db_conn):
        from backend.state.state_manager import reset_all_state, RiskState, get_bot_status
        RiskState.record_loss()
        RiskState.increment_daily_trades()
        reset_all_state()
        assert RiskState.get_consecutive_losses() == 0
        assert RiskState.get_daily_trades() == 0
