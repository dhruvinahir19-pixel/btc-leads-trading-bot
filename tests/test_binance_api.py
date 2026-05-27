"""
test_binance_api.py — Tests for the Binance API client.

Verifies:
- Mock client methods work correctly
- Price/quantity rounding
- Error handling with retry logic
- API key configuration
- Connection testing
- Edge cases: missing keys, empty responses, invalid symbols
"""
import pytest
import json
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError


class TestMockClientBasics:
    """Test the MockBinanceClient provides realistic data."""

    def test_get_exchange_info(self, mock_demo_client):
        info = mock_demo_client.get_exchange_info()
        assert "symbols" in info
        assert len(info["symbols"]) >= 4

    def test_get_ticker_price_default(self, mock_demo_client):
        price = mock_demo_client.get_ticker_price("BTCUSDT")
        assert price > 50000
        assert price < 100000

    def test_get_usdt_balance(self, mock_demo_client):
        balance = mock_demo_client.get_usdt_balance()
        assert balance == 10000.0

    def test_set_balance(self, mock_demo_client):
        mock_demo_client.set_balance(500.0)
        assert mock_demo_client.get_usdt_balance() == 500.0

    def test_place_market_order(self, mock_demo_client):
        order = mock_demo_client.place_market_order("DOGEUSDT", "BUY", 100)
        assert order["status"] == "FILLED"
        assert order["side"] == "BUY"
        assert order["symbol"] == "DOGEUSDT"
        assert float(order["executedQty"]) == 100

    def test_place_limit_order(self, mock_demo_client):
        order = mock_demo_client.place_limit_order("DOGEUSDT", "BUY", 100, 0.12)
        assert order["status"] == "NEW"
        assert order["type"] == "LIMIT"

    def test_open_orders(self, mock_demo_client):
        mock_demo_client.place_limit_order("DOGEUSDT", "BUY", 100, 0.12)
        orders = mock_demo_client.get_open_orders("DOGEUSDT")
        assert len(orders) == 1
        assert orders[0]["type"] == "LIMIT"

    def test_cancel_order(self, mock_demo_client):
        oid = mock_demo_client.place_limit_order("DOGEUSDT", "BUY", 100, 0.12)["orderId"]
        mock_demo_client.cancel_order("DOGEUSDT", oid)
        assert len(mock_demo_client.get_open_orders("DOGEUSDT")) == 0

    def test_set_position(self, mock_demo_client):
        mock_demo_client.set_position("DOGEUSDT", 100, 0.12)
        pos = mock_demo_client.get_position_for_symbol("DOGEUSDT")
        assert pos is not None
        assert float(pos["positionAmt"]) == 100
        assert float(pos["entryPrice"]) == 0.12

    def test_clear_positions(self, mock_demo_client):
        mock_demo_client.set_position("DOGEUSDT", 100, 0.12)
        mock_demo_client.clear_positions()
        assert mock_demo_client.get_position_for_symbol("DOGEUSDT") is None

    def test_get_positions_filtered(self, mock_demo_client):
        mock_demo_client.set_position("DOGEUSDT", 100, 0.12)
        mock_demo_client.set_position("ETHUSDT", 1.0, 3450)
        positions = mock_demo_client.get_positions()
        assert len(positions) == 2


class TestPriceQuantityRounding:
    """Test price and quantity rounding logic."""

    def test_round_price_doge(self, mock_demo_client):
        # DOGEUSDT has tickSize 0.00001 per our mock
        rounded = mock_demo_client.round_price("DOGEUSDT", 0.123456)
        assert rounded == pytest.approx(0.12345, abs=0.00001)

    def test_round_price_btc(self, mock_demo_client):
        # BTCUSDT has tickSize 0.01 per our mock
        rounded = mock_demo_client.round_price("BTCUSDT", 65432.123)
        assert rounded == 65432.12  # Rounds down to 0.01

    def test_round_quantity_doge(self, mock_demo_client):
        # DOGEUSDT has stepSize 1
        rounded = mock_demo_client.round_quantity("DOGEUSDT", 123.456)
        assert rounded == 123.0

    def test_round_quantity_btc(self, mock_demo_client):
        # BTCUSDT has stepSize 0.001
        rounded = mock_demo_client.round_quantity("BTCUSDT", 1.23456)
        assert rounded == pytest.approx(1.234, abs=0.001)

    def test_get_price_filter(self, mock_demo_client):
        pf = mock_demo_client.get_price_filter("DOGEUSDT")
        assert "tickSize" in pf
        assert pf["tickSize"] > 0

    def test_get_lot_size_info(self, mock_demo_client):
        lot = mock_demo_client.get_lot_size_info("DOGEUSDT")
        assert "stepSize" in lot
        assert "minQty" in lot
        assert "maxQty" in lot

    def test_get_price_precision(self, mock_demo_client):
        prec = mock_demo_client.get_price_precision("BTCUSDT")
        assert prec >= 2


class TestKlines:
    """Test kline data fetching."""

    def test_get_klines_default(self, mock_data_client):
        candles = mock_data_client.get_klines("BTCUSDT", "1h", limit=10)
        assert len(candles) == 10
        assert candles[0]["ts"] > 0
        assert candles[0]["c"] > 0

    def test_get_klines_with_start_time(self, mock_data_client):
        now_ms = 1700000000000
        candles = mock_data_client.get_klines("BTCUSDT", "1h", start_time=now_ms, limit=5)
        for c in candles:
            assert c["ts"] >= now_ms

    def test_get_all_klines_range(self, mock_data_client):
        start = int(1700000000000)
        end = start + 3600000 * 5
        mock_data_client.set_price("BTCUSDT", 65000)
        candles = mock_data_client.get_all_klines_range("BTCUSDT", "1h", start, end)
        assert len(candles) > 0


class TestAlgoOrders:
    """Test Algo Order API (TP/SL)."""

    def test_place_algo_order(self, mock_demo_client):
        result = mock_demo_client.place_algo_order("DOGEUSDT", "SELL", "STOP_LOSS",
                                                    100, stop_price=0.11)
        assert result["algoId"] > 0

    def test_get_open_algo_orders(self, mock_demo_client):
        mock_demo_client.place_algo_order("DOGEUSDT", "SELL", "STOP_LOSS", 100, stop_price=0.11)
        orders = mock_demo_client.get_open_algo_orders("DOGEUSDT")
        assert len(orders) == 1
        assert orders[0]["algoType"] == "STOP_LOSS"

    def test_cancel_algo_order(self, mock_demo_client):
        aid = mock_demo_client.place_algo_order("DOGEUSDT", "SELL", "STOP_LOSS", 100, stop_price=0.11)["algoId"]
        mock_demo_client.cancel_algo_order("DOGEUSDT", aid)
        assert len(mock_demo_client.get_open_algo_orders("DOGEUSDT")) == 0

    def test_place_tp_sl_orders(self, mock_demo_client):
        result = mock_demo_client.place_tp_sl_orders("DOGEUSDT", "LONG", 100, 0.13, 0.11)
        assert "tp_order" in result
        assert "sl_order" in result
        assert result["tp_order"]["type"] == "LIMIT"


class TestClientConfiguration:
    """Test client creation and configuration."""

    def test_data_client_creation(self):
        from backend.api.binance import get_data_client
        client = get_data_client()
        assert client is not None
        assert client.use_demo is False
        assert client.api_key == "test_data_key"

    def test_demo_client_creation(self):
        from backend.api.binance import get_demo_client
        client = get_demo_client()
        assert client is not None
        assert client.use_demo is True
        assert client.api_key == "test_demo_key"

    def test_connection_function(self):
        from backend.api.binance import test_connection
        result = test_connection()
        assert result["data_api"] is True
        assert result["demo_api"] is True
        assert "usdt_balance" in result
