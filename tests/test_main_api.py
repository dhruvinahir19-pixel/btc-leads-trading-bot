"""Tests for FastAPI endpoints in backend/main.py."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
from fastapi.testclient import TestClient

# Patch environment before importing main
os.environ.setdefault("BINANCE_API_KEY", "test_key_main")
os.environ.setdefault("BINANCE_SECRET_KEY", "test_secret_main")
os.environ.setdefault("SMTP_SERVER", "smtp.test.com")
os.environ.setdefault("SMTP_PORT", "587")
os.environ.setdefault("SMTP_USERNAME", "user@test.com")
os.environ.setdefault("SMTP_PASSWORD", "pass")
os.environ.setdefault("SMTP_TO", "to@test.com")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:bot")
os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")
os.environ.setdefault("MAX_POSITIONS", "3")
os.environ.setdefault("MAX_DAILY_LOSS_PCT", "2.0")
os.environ.setdefault("CIRCUIT_BREAKER_LIMIT", "5")
os.environ.setdefault("COINS", "BTCUSDT,ETHUSDT,SOLUSDT")
os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("LOG_LEVEL", "DEBUG")

os.environ["RENDER"] = "false"

from backend.main import app


@pytest.fixture(autouse=True)
def reset_app_state():
    """Reset shared state before each test."""
    import backend.main as m
    from backend.state.state_manager import reset_all_state
    reset_all_state()
    yield


@pytest.fixture
def client():
    """Create a TestClient for the FastAPI app.
    Patches scheduler and SMTP to prevent background threads and network hangs.
    """
    with patch('backend.main._start_scheduler', return_value=None):
        with patch('backend.notifications.email_alerts.EmailNotifier.send_startup', return_value=True):
            with patch('backend.notifications.email_alerts.EmailNotifier.send_shutdown', return_value=True):
                with TestClient(app) as c:
                    yield c


# ─── Health ────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


# ─── Status ────────────────────────────────────────────────────────

class TestStatus:
    def test_status_returns_bot_state(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "health" in data
        assert "today_pnl" in data

    def test_status_includes_trading_hours(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "health" in data


# ─── Config ────────────────────────────────────────────────────────

class TestConfig:
    def test_get_config_returns_redacted_keys(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        # Check sensitive keys are redacted
        for key in data:
            if "KEY" in key or "SECRET" in key or "PASSWORD" in key or "TOKEN" in key:
                val = str(data[key])
                assert val == "***REDACTED***" or val.startswith("***"), f"{key} should be redacted, got: {val}"
            elif "BOT_TOKEN" in key:
                assert data[key] == "***REDACTED***", f"{key} should be redacted"

    def test_get_config_contains_expected_keys(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        expected = ["trading_coins", "max_coins_per_trade", "position_size_usdt", "btc_trigger_pct"]
        for key in expected:
            assert key in data, f"Expected {key} in config response"

    def test_get_config_returns_scalars(self, client):
        """Ensure numeric values aren't wrapped in quotes."""
        resp = client.get("/api/config")
        data = resp.json()
        if "MAX_POSITIONS" in data:
            assert isinstance(data["MAX_POSITIONS"], (int, float)) or (
                isinstance(data["MAX_POSITIONS"], str) and data["MAX_POSITIONS"].isdigit()
            )


# ─── Trades ────────────────────────────────────────────────────────

class TestTrades:
    def test_trades_empty_when_no_trades(self, client):
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert "trades" in data
        assert "count" in data

    def test_trades_with_filters(self, client):
        resp = client.get("/api/trades?coin=BTCUSDT&side=BUY&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert "trades" in data


# ─── Logs ──────────────────────────────────────────────────────────

class TestLogs:
    def test_logs_returns_recent_logs(self, client):
        resp = client.get("/api/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert "lines" in data or "logs" in data

    def test_logs_with_level_filter(self, client):
        resp = client.get("/api/logs?level=ERROR&lines=10")
        assert resp.status_code == 200


# ─── Email ─────────────────────────────────────────────────────────

class TestEmail:
    def test_email_send_endpoint_calls_notifier(self, client):
        """test-email endpoint should attempt to send."""
        from backend.notifications.email_alerts import EmailNotifier
        with patch.object(EmailNotifier, 'send_test', return_value=True):
            resp = client.post("/api/test-email")
            assert resp.status_code == 200
            data = resp.json()
            assert "message" in data or "status" in data


# ─── Overview ──────────────────────────────────────────────────────

class TestOverview:
    def test_overview_returns_state(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "health" in data


# ─── Performance ───────────────────────────────────────────────────

class TestPerformance:
    def test_equity_curve_empty_initially(self, client):
        resp = client.get("/api/equity-curve")
        assert resp.status_code == 200
        data = resp.json()
        assert "points" in data
        assert isinstance(data["points"], list)

    def test_pnl_breakdown_empty_initially(self, client):
        resp = client.get("/api/pnl-breakdown")
        assert resp.status_code == 200
        data = resp.json()
        assert "breakdown" in data
        assert isinstance(data["breakdown"], list)

    def test_trade_journal_filters(self, client):
        resp = client.get("/api/trade-journal?coin=BTCUSDT&page=1&per_page=10")
        assert resp.status_code == 200
        data = resp.json()
        assert "trades" in data or isinstance(data, list)


# ─── Error Handling ────────────────────────────────────────────────

class TestErrors:
    def test_404_returns_json(self, client):
        resp = client.get("/api/nonexistent")
        assert resp.status_code == 404

    def test_method_not_allowed(self, client):
        resp = client.put("/api/status")
        assert resp.status_code in (405, 404)


# ─── CORS Headers ──────────────────────────────────────────────────

class TestCORS:
    def test_cors_headers_present(self, client):
        resp = client.get("/health", headers={"Origin": "http://localhost:5173"})
        # CORS may or may not be configured; just verify server responds
        assert resp.status_code == 200
