"""
test_entry_manager.py — Tests for the EntryManager module.

Verifies:
- Full signal execution flow
- Multiple coin entries
- Overlapping position prevention
- TP/SL placement after entry
- Error handling: risk gate blocks, no prices, all coins in position
"""
import time
import pytest
from unittest.mock import patch, MagicMock
from backend.config import POSITION_SIZE_USDT, MAX_COINS_PER_TRADE


class TestExecuteSignal:
    """Test execute_signal flow."""

    @patch('time.sleep', return_value=None)
    def test_execute_signal_success(self, mock_sleep, mock_demo_client, mock_data_client, db_conn):
        """Happy path: signal executes, coins entered, TP/SL placed."""
        from backend.core.signal import SignalGenerator, Signal
        from backend.trading.entry_manager import EntryManager

        signal = Signal("2024-01-15 17:30:00", "LONG", 1.5, 65000, 0, 0, 0, "")
        em = EntryManager()
        em.order_mgr.client = mock_demo_client  # Ensure same mock reference
        mock_demo_client.set_price("DOGEUSDT", 0.12)
        mock_demo_client.set_price("ETHUSDT", 3450)
        mock_data_client.set_price("DOGEUSDT", 0.12)
        mock_data_client.set_price("ETHUSDT", 3450)

        result = em.execute_signal(signal)
        assert len(result["entries"]) > 0
        assert result["signal_side"] == "LONG"
        for entry in result["entries"]:
            assert entry["trade_id"] > 0
            assert entry["entry_price"] > 0
            assert "tp_price" in entry
            assert "sl_price" in entry

    @patch('time.sleep', return_value=None)
    def test_execute_signal_risk_gate_blocked(self, mock_sleep, mock_demo_client, db_conn):
        """Risk gate should block entry."""
        from backend.core.signal import Signal
        from backend.trading.entry_manager import EntryManager
        from backend.trading.risk_manager import RiskManager

        signal = Signal("2024-01-15 17:30:00", "LONG", 1.5, 65000, 0, 0, 0, "")
        em = EntryManager()

        with patch.object(em.risk_mgr, 'check_entry_gates',
                          return_value={'allowed': False, 'reason': 'Gate: daily_loss_limit', 'gate': 'daily_loss_limit'}):
            result = em.execute_signal(signal)
            assert len(result["entries"]) == 0
            assert len(result["skipped"]) > 0
            assert "daily_loss_limit" in result["skipped"][0]["reason"]

    @patch('time.sleep', return_value=None)
    def test_execute_signal_overlapping_positions(self, mock_sleep, mock_demo_client, mock_data_client, db_conn):
        """Coins already in position should be skipped."""
        from backend.core.signal import Signal
        from backend.trading.entry_manager import EntryManager
        from backend.database.db import trade_create

        # Create an existing open trade for DOGEUSDT
        trade_create("2024-01-15 17:30:00", "DOGEUSDT", "LONG", 1.5, 0.12, 0.13, 0.11, 10.0)

        signal = Signal("2024-01-15 17:30:00", "LONG", 1.5, 65000, 0, 0, 0, "")
        em = EntryManager()
        mock_demo_client.set_price("ETHUSDT", 3450)
        mock_data_client.set_price("ETHUSDT", 3450)

        result = em.execute_signal(signal)
        # DOGEUSDT should be skipped, ETHUSDT should be entered
        skipped_coins = [s.get("coin") for s in result["skipped"]]
        assert "DOGEUSDT" in skipped_coins or "already" in str(result["skipped"])

    @patch('time.sleep', return_value=None)
    def test_execute_signal_empty_prices(self, mock_sleep, mock_demo_client, db_conn):
        """If no entry prices can be fetched, should return with skipped."""
        from backend.core.signal import Signal, SignalGenerator
        from backend.trading.entry_manager import EntryManager

        signal = Signal("2024-01-15 17:30:00", "LONG", 1.5, 65000, 0, 0, 0, "")
        em = EntryManager()

        with patch.object(em.signal_gen, 'get_entry_prices', return_value={}):
            result = em.execute_signal(signal)
            assert len(result["entries"]) == 0
            assert len(result["skipped"]) > 0

    @patch('time.sleep', return_value=None)
    def test_execute_signal_short(self, mock_sleep, mock_demo_client, mock_data_client, db_conn):
        """SHORT signal should work correctly with inverted TP/SL."""
        from backend.core.signal import Signal
        from backend.trading.entry_manager import EntryManager

        signal = Signal("2024-01-15 17:30:00", "SHORT", -1.5, 63000, 0, 0, 0, "")
        em = EntryManager()
        mock_demo_client.set_price("DOGEUSDT", 0.12)
        mock_data_client.set_price("DOGEUSDT", 0.12)

        result = em.execute_signal(signal)
        assert result["signal_side"] == "SHORT"
        # If entries happened, verify TP < SL for SHORT
        for entry in result["entries"]:
            assert entry["tp_price"] < entry["sl_price"]

    @patch('time.sleep', return_value=None)
    def test_execute_signal_result_structure(self, mock_sleep, mock_demo_client, mock_data_client, db_conn):
        """Verify result dict has all expected keys."""
        from backend.core.signal import Signal
        from backend.trading.entry_manager import EntryManager

        signal = Signal("2024-01-15 17:30:00", "LONG", 1.5, 65000, 0, 0, 0, "")
        em = EntryManager()
        mock_demo_client.set_price("DOGEUSDT", 0.12)
        mock_data_client.set_price("DOGEUSDT", 0.12)

        result = em.execute_signal(signal)
        expected_keys = {"signal_time", "signal_side", "btc_return_pct", "entries", "failed", "skipped"}
        assert expected_keys.issubset(set(result.keys()))
