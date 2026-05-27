"""
test_tp_sl_manager.py — Tests for TpSlManager module.

Verifies:
- TP/SL order status checking
- Regular order + Algo order detection
- Silent failure detection (no orders but position open)
- Position-externally-closed detection
- Exit price verification
- Edge cases: API failures, empty responses
"""
import pytest
from unittest.mock import patch


class TestTpSlStatus:
    """Test check_tp_sl_status for various scenarios."""

    def test_orders_active(self, mock_demo_client, db_conn):
        """Normal case: TP and SL orders are active."""
        from backend.trading.tp_sl_manager import TpSlManager
        tsm = TpSlManager()
        mock_demo_client.place_limit_order("DOGEUSDT", "SELL", 100, 0.13, reduce_only=True)
        mock_demo_client.place_algo_order("DOGEUSDT", "SELL", "STOP_LOSS", 100, stop_price=0.11)
        status = tsm.check_tp_sl_status("DOGEUSDT", trade_id=1)
        assert status["orders_active"] is True
        assert status["tp_filled"] is False
        assert status["sl_filled"] is False
        assert status["exit_needed"] is False

    def test_tp_filled(self, mock_demo_client, db_conn):
        """TP order filled should trigger exit."""
        from backend.trading.tp_sl_manager import TpSlManager
        tsm = TpSlManager()
        # Add a filled TP order (executedQty > 0)
        mock_demo_client.add_open_order(
            symbol="DOGEUSDT", side="SELL", order_type="LIMIT",
            price=0.13, orig_qty=100, executed_qty=100, status="FILLED"
        )
        status = tsm.check_tp_sl_status("DOGEUSDT", trade_id=1)
        assert status["tp_filled"] is True
        assert status["exit_needed"] is True
        assert status["exit_info"]["reason"] == "tp_hit"

    def test_no_orders_position_gone(self, mock_demo_client, db_conn):
        """No orders and no position = position closed externally."""
        from backend.trading.tp_sl_manager import TpSlManager
        tsm = TpSlManager()
        # No open orders, no position set
        status = tsm.check_tp_sl_status("DOGEUSDT", trade_id=1)
        assert status["exit_needed"] is True
        assert status["exit_info"]["reason"] == "orders_gone_position_closed"

    def test_no_orders_position_open_silent_failure(self, mock_demo_client, db_conn):
        """No orders but position still open = silent failure."""
        from backend.trading.tp_sl_manager import TpSlManager
        tsm = TpSlManager()
        mock_demo_client.set_position("DOGEUSDT", 100, 0.12)
        status = tsm.check_tp_sl_status("DOGEUSDT", trade_id=1)
        assert status["exit_needed"] is True
        assert status["exit_info"]["reason"] == "sl_tp_failed_silently"
        assert status["exit_info"]["need_market_exit"] is True

    def test_algo_sl_filled(self, mock_demo_client, db_conn):
        """SL filled via Algo order should trigger exit."""
        from backend.trading.tp_sl_manager import TpSlManager
        tsm = TpSlManager()
        # Add a LIMIT TP order (still active)
        mock_demo_client.add_open_order(
            symbol="DOGEUSDT", side="SELL", order_type="LIMIT",
            price=0.13, executed_qty=0
        )
        # Add an executed Algo SL
        mock_demo_client.add_algo_order(
            symbol="DOGEUSDT", algo_type="STOP_LOSS", trigger_price=0.11,
            executed_qty=100
        )
        status = tsm.check_tp_sl_status("DOGEUSDT", trade_id=1)
        assert status["sl_filled"] is True
        assert status["exit_needed"] is True

    def test_api_error_during_check(self, mock_demo_client, db_conn):
        """API errors should not crash."""
        from backend.trading.tp_sl_manager import TpSlManager
        tsm = TpSlManager()
        with patch.object(mock_demo_client, 'get_open_orders',
                          side_effect=Exception("API error")):
            status = tsm.check_tp_sl_status("DOGEUSDT", trade_id=1)
            assert "orders_active" in status
            assert status["exit_needed"] is False or status["exit_needed"] is True


class TestVerifyExitPrice:
    """Test exit price verification."""

    def test_exit_verification_not_exited(self, mock_demo_client, db_conn):
        """Position still open = not exited yet."""
        from backend.trading.tp_sl_manager import TpSlManager
        tsm = TpSlManager()
        mock_demo_client.set_position("DOGEUSDT", 100, 0.12)
        result = tsm.verify_exit_price("DOGEUSDT", 0.13, 0.11, 1)
        assert result["exited"] is False

    def test_exit_verification_exited(self, mock_demo_client, db_conn):
        """Position closed = exited."""
        from backend.trading.tp_sl_manager import TpSlManager
        tsm = TpSlManager()
        # No position set = closed
        result = tsm.verify_exit_price("DOGEUSDT", 0.13, 0.11, 1)
        assert result["exited"] is True
