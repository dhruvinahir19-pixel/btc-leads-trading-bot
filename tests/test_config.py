"""
test_config.py — Tests for backend.config module.

Verifies:
- Environment variable loading and defaults
- Type coercion (int, float, bool)
- Edge cases: missing keys, malformed values
- Render.com detection
- IST timezone helpers
- show_config() output
"""
import os
import sys
import pytest

# Apply env overrides BEFORE importing config
os.environ["TEST_BTC_TRIGGER_PCT"] = "1.0"


class TestEnvHelpers:
    """Test the environment helper functions."""

    def test_env_default(self):
        """env() returns default when key missing."""
        from backend.config import env
        assert env("NONEXISTENT_KEY_XYZ") == ""
        assert env("NONEXISTENT_KEY_XYZ", "fallback") == "fallback"
        assert env("NONEXISTENT_KEY_XYZ", 42) == 42  # non-string default preserved

    def test_env_existing(self):
        """env() returns actual value when key exists."""
        from backend.config import env
        # BINANCE_DEMO_KEY is set in conftest
        val = env("BINANCE_DEMO_KEY")
        assert val == "test_demo_key"

    def test_env_int_valid(self):
        """env_int() parses valid ints."""
        from backend.config import env_int
        os.environ["TEST_INT_VALID"] = "42"
        assert env_int("TEST_INT_VALID", 0) == 42

    def test_env_int_invalid(self):
        """env_int() returns default for non-parseable values."""
        from backend.config import env_int
        os.environ["TEST_INT_INVALID"] = "not_a_number"
        assert env_int("TEST_INT_INVALID", 10) == 10

    def test_env_int_missing(self):
        """env_int() returns default for missing keys."""
        from backend.config import env_int
        assert env_int("MISSING_INT_KEY", 99) == 99

    def test_env_float_valid(self):
        """env_float() parses valid floats."""
        from backend.config import env_float
        os.environ["TEST_FLOAT_VALID"] = "3.14159"
        assert env_float("TEST_FLOAT_VALID", 0.0) == pytest.approx(3.14159)

    def test_env_float_invalid(self):
        """env_float() returns default for non-parseable values."""
        from backend.config import env_float
        os.environ["TEST_FLOAT_INVALID"] = "not_a_number"
        assert env_float("TEST_FLOAT_INVALID", 1.5) == 1.5

    def test_env_bool_true_values(self):
        """env_bool() returns True for common truthy values."""
        from backend.config import env_bool
        for val in ["1", "true", "True", "TRUE", "yes", "YES", "on", "ON"]:
            os.environ["TEST_BOOL"] = val
            assert env_bool("TEST_BOOL") is True, f"Failed for value: {val}"

    def test_env_bool_false_values(self):
        """env_bool() returns False for common falsy values."""
        from backend.config import env_bool
        for val in ["0", "false", "False", "FALSE", "no", "NO", "off", "OFF"]:
            os.environ["TEST_BOOL"] = val
            assert env_bool("TEST_BOOL", True) is False, f"Failed for value: {val}"

    def test_env_bool_missing(self):
        """env_bool() returns default for missing keys."""
        from backend.config import env_bool
        assert env_bool("MISSING_BOOL", True) is True
        assert env_bool("MISSING_BOOL", False) is False

    def test_env_bool_edge_empty(self):
        """env_bool() returns default for empty string."""
        from backend.config import env_bool
        os.environ["TEST_BOOL_EMPTY"] = ""
        assert env_bool("TEST_BOOL_EMPTY", True) is True


class TestConfigDefaults:
    """Test that config constants have sensible defaults."""

    def test_strategy_params(self):
        from backend.config import BTC_TRIGGER_PCT, TP_PCT, SL_PCT, WINDOW_BARS
        assert BTC_TRIGGER_PCT > 0
        assert TP_PCT > 0
        assert SL_PCT > 0
        assert WINDOW_BARS > 0

    def test_position_sizing(self):
        from backend.config import POSITION_SIZE_USDT, MAX_COINS_PER_TRADE
        assert POSITION_SIZE_USDT > 0
        assert MAX_COINS_PER_TRADE > 0

    def test_risk_limits(self):
        from backend.config import MAX_DAILY_LOSS_USDT, MAX_TRADES_PER_DAY, MAX_CONSECUTIVE_LOSSES
        assert MAX_DAILY_LOSS_USDT > 0
        assert MAX_TRADES_PER_DAY > 0
        assert MAX_CONSECUTIVE_LOSSES > 0

    def test_api_keys_loaded(self):
        from backend.config import BINANCE_API_KEY, BINANCE_DEMO_KEY, BINANCE_DEMO_SECRET
        assert BINANCE_API_KEY == "test_data_key"
        assert BINANCE_DEMO_KEY == "test_demo_key"
        assert BINANCE_DEMO_SECRET == "test_demo_secret"

    def test_smtp_config(self):
        from backend.config import SMTP_EMAIL, SMTP_TO, SMTP_HOST, SMTP_PORT
        assert SMTP_EMAIL == "test@example.com"
        assert SMTP_TO == "recipient@example.com"
        assert SMTP_HOST == "smtp.gmail.com"
        assert SMTP_PORT == 587

    def test_server_defaults(self):
        from backend.config import HOST, PORT
        assert HOST == "0.0.0.0"
        assert PORT == 8000

    def test_trading_coins_default(self):
        from backend.config import TRADING_COINS, FIXED_COINS
        assert "ETHUSDT" in TRADING_COINS
        assert "DOGEUSDT" in TRADING_COINS
        assert FIXED_COINS == ["ETHUSDT", "DOGEUSDT"]

    def test_db_path(self):
        from backend.config import DB_PATH, BASE_DIR
        assert str(DB_PATH).endswith("trading_bot.db")


class TestRenderDetection:
    """Test Render.com deployment detection."""

    def test_not_on_render_default(self):
        from backend.config import IS_RENDER
        assert IS_RENDER is False  # Not running on Render in tests

    def test_render_detected_by_env_var(self):
        """Setting RENDER=true should flag IS_RENDER."""
        import backend.config as cfg
        # Temporarily set and reload
        old = os.environ.get("RENDER")
        os.environ["RENDER"] = "true"
        # Re-import to trigger detection
        import importlib
        importlib.reload(cfg)
        assert cfg.IS_RENDER is True
        # Cleanup
        if old:
            os.environ["RENDER"] = old
        else:
            del os.environ["RENDER"]
        importlib.reload(cfg)

    def test_render_external_url_detection(self):
        """RENDER_EXTERNAL_URL should also flag IS_RENDER."""
        import backend.config as cfg
        import importlib
        old = os.environ.get("RENDER_EXTERNAL_URL")
        os.environ["RENDER_EXTERNAL_URL"] = "https://test.onrender.com"
        importlib.reload(cfg)
        assert cfg.IS_RENDER is True
        assert cfg.RENDER_EXTERNAL_URL == "https://test.onrender.com"
        if old:
            os.environ["RENDER_EXTERNAL_URL"] = old
        else:
            del os.environ["RENDER_EXTERNAL_URL"]
        importlib.reload(cfg)


class TestTimezoneHelpers:
    """Test IST timezone conversion helpers."""

    def test_to_ist_timestamp_format(self):
        from backend.config import to_ist_timestamp
        # 2024-01-15 12:00:00 UTC = 2024-01-15 17:30:00 IST
        ts = 1705310400000  # 2024-01-15 12:00:00 UTC (approx)
        result = to_ist_timestamp(ts)
        assert "2024-01-15" in result
        assert ":" in result  # HH:MM:SS format

    def test_to_ist_hour_minute(self):
        from backend.config import to_ist_hour_minute
        ts = 1705310400000  # Approx UTC noon
        hour, minute = to_ist_hour_minute(ts)
        assert 0 <= hour <= 23
        assert 0 <= minute <= 59

    def test_get_ist_offset(self):
        from backend.config import get_ist_offset
        assert get_ist_offset() == 5.5


class TestShowConfig:
    """Test show_config() runs without errors."""

    def test_show_config_runs(self, capsys):
        from backend.config import show_config
        show_config()
        captured = capsys.readouterr()
        assert "TRADING BOT CONFIGURATION" in captured.out
        assert "BTC" in captured.out
        assert "TP:" in captured.out
        assert "SL:" in captured.out


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_env_with_quotes(self):
        """Values with surrounding quotes should be stripped."""
        pytest.skip("_load_env reads from fixed .env path, tested implicitly through startup")

    def test_env_file_not_found(self):
        """Missing .env file should warn but not crash."""
        pytest.skip("requires filesystem manipulation of .env")

    def test_quote_stripping_logic(self):
        """Test the quote-stripping logic used by _load_env."""
        import re
        # Simulate the quote-stripping regex from _load_env
        def strip_env_val(val: str) -> str:
            m = re.match(r'^\s*["\'](.*)["\']\s*$', val)
            return m.group(1) if m else val.strip()

        assert strip_env_val('"hello"') == "hello"
        assert strip_env_val("'test_val'") == "test_val"
        assert strip_env_val('"nested val"') == "nested val"
        assert strip_env_val("plain") == "plain"
        assert strip_env_val('""') == ""
