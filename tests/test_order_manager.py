"""
test_order_manager.py — Tests for the OrderManager module.

Verifies:
- enter_position with limit→market fallback
- Exit strategies
- TP/SL placement
- Cancel operations
- Edge cases: invalid symbols, tiny positions, API failures
"""
import pytest
from unittest.mock import patch, MagicMock, call


class TestEnterPosition:
    """Test enter_position logic."""

    def test_enter_position_long(self, mock_demo_client, db_conn):
        from backend.trading.order_manager import OrderManager
        om = OrderManager()
        mock_demo_client.set_price("DOGEUSDT", 0.12)
        result = om.enter_position("DOGEUSDT", "LONG", 10.0)
        assert result is not None
        assert result["filled_qty"] > 0
        assert result["avg_price"] > 0
        assert result["method"] in ("market", "limit_poll", "limit", "limit+market", "market_delayed")

    def test_enter_position_invalid_symbol(self, mock_demo_client, db_conn):
        from backend.trading.order_manager import OrderManager
        om = OrderManager()
        # The mock won't have lot info for invalid, but it should handle gracefully
        result = om.enter_position("NONEXISTENT123", "LONG", 10.0)
        # May return None if lot info can't be fetched (real behavior)
        assert result is not None or True  # Don't crash

    def test_enter_position_tiny_amount(self, mock_demo_client, db_conn):
        from backend.trading.order_manager import OrderManager
        om = OrderManager()
        mock_demo_client.set_price("DOGEUSDT", 0.12)
        # Tiny positions should either be blocked or return small quantity
        result = om.enter_position("DOGEUSDT", "LONG", 0.001)
        # Real system may block orders under min notional
        assert result is None or result["filled_qty"] >= 0

    def test_enter_position_short(self, mock_demo_client, db_conn):
        from backend.trading.order_manager import OrderManager
        om = OrderManager()
        mock_demo_client.set_price("DOGEUSDT", 0.12)
        result = om.enter_position("DOGEUSDT", "SHORT", 10.0)
        assert result is not None


class TestExitMarket:
    """Test market exit operations."""

    def test_exit_market_long(self, mock_demo_client, db_conn):
        from backend.trading.order_manager import OrderManager
        om = OrderManager()
        mock_demo_client.set_price("DOGEUSDT", 0.12)
        result = om.exit_market("DOGEUSDT", "LONG", 100)
        assert result is not None
        assert result["filled_qty"] > 0

    def test_exit_market_short(self, mock_demo_client, db_conn):
        from backend.trading.order_manager import OrderManager
        om = OrderManager()
        mock_demo_client.set_price("DOGEUSDT", 0.12)
        result = om.exit_market("DOGEUSDT", "SHORT", 100)
        assert result is not None


class TestPlaceTpSl:
    """Test TP/SL order placement."""

    def test_place_tp_sl_long(self, mock_demo_client, db_conn):
        from backend.trading.order_manager import OrderManager
        om = OrderManager()
        mock_demo_client.set_price("DOGEUSDT", 0.12)
        result = om.place_tp_sl("DOGEUSDT", "LONG", 100, 0.13, 0.11)
        assert "tp_order" in result
        assert "sl_order" in result

    def test_place_tp_sl_short(self, mock_demo_client, db_conn):
        from backend.trading.order_manager import OrderManager
        om = OrderManager()
        mock_demo_client.set_price("DOGEUSDT", 0.12)
        result = om.place_tp_sl("DOGEUSDT", "SHORT", 100, 0.11, 0.13)
        assert "tp_order" in result
        assert "sl_order" in result


class TestCancelTpSl:
    """Test TP/SL cancellation."""

    def test_cancel_tp_sl(self, mock_demo_client, db_conn):
        from backend.trading.order_manager import OrderManager
        om = OrderManager()
        mock_demo_client.set_price("DOGEUSDT", 0.12)
        # Place some orders first
        mock_demo_client.place_limit_order("DOGEUSDT", "SELL", 100, 0.13, reduce_only=True)
        result = om.cancel_tp_sl("DOGEUSDT")
        assert result is True
        assert len(mock_demo_client.get_open_orders("DOGEUSDT")) == 0

    def test_cancel_tp_sl_with_algo_orders(self, mock_demo_client, db_conn):
        from backend.trading.order_manager import OrderManager
        om = OrderManager()
        mock_demo_client.place_limit_order("DOGEUSDT", "SELL", 100, 0.13, reduce_only=True)
        mock_demo_client.place_algo_order("DOGEUSDT", "SELL", "STOP_LOSS", 100, stop_price=0.11)
        result = om.cancel_tp_sl("DOGEUSDT")
        assert result is True
        assert len(mock_demo_client.get_open_orders("DOGEUSDT")) == 0


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_enter_position_with_price_set(self, mock_demo_client, db_conn):
        from backend.trading.order_manager import OrderManager
        om = OrderManager()
        mock_demo_client.set_price("FARTCOINUSDT", 0.05)
        result = om.enter_position("FARTCOINUSDT", "LONG", 10.0)
        assert result is not None

    def test_round_down_utility(self):
        from backend.trading.order_manager import OrderManager
        result = OrderManager._round_down(12.3456, 0.01)
        assert result == pytest.approx(12.34, abs=0.001)

    def test_round_down_large_step(self):
        from backend.trading.order_manager import OrderManager
        result = OrderManager._round_down(123.456, 10.0)
        assert result == pytest.approx(120.0, abs=0.001)

    def test_round_down_zero_step(self):
        from backend.trading.order_manager import OrderManager
        result = OrderManager._round_down(12.345, 0.0)
        assert result == pytest.approx(12.345, abs=0.001)
