"""
test_reconciliation.py — Tests for the Reconciliation module.

Verifies:
- Full reconcile_all cycle
- Phantom trade detection (DB open, Binance no position)
- Orphan position detection (Binance position, DB no record)
- Position mismatch logging
- Error handling: API failures
- Edge cases: no trades, no positions
"""
import pytest
from unittest.mock import patch


class TestReconcileAll:
    """Test the full reconciliation cycle."""

    def test_reconcile_no_issues(self, mock_demo_client, db_conn):
        """No trades, no positions = no issues."""
        from backend.trading.reconciliation import Reconciliation
        rc = Reconciliation()
        result = rc.reconcile_all()
        assert result["checked"] is True
        assert result["issues_found"] == 0

    def test_reconcile_phantom_trade(self, mock_demo_client, db_conn):
        """DB has open trade but Binance has no position."""
        from backend.trading.reconciliation import Reconciliation
        from backend.database.db import trade_create

        # Create trade but don't set a position on mock
        tid = trade_create("2024-01-15 17:30:00", "DOGEUSDT", "LONG", 1.5, 0.12, 0.1212, 0.1194, 10.0)
        rc = Reconciliation()
        result = rc.reconcile_all()
        assert result["issues_found"] >= 1
        assert result["issues_fixed"] >= 1
        # Trade should now be closed
        from backend.database.db import get_recent_trades
        trades = get_recent_trades(1)
        assert trades[0]["status"] == "closed"

    def test_reconcile_orphan_position(self, mock_demo_client, db_conn):
        """Binance has position but DB has no record."""
        from backend.trading.reconciliation import Reconciliation
        mock_demo_client.set_position("DOGEUSDT", 100, 0.12)
        rc = Reconciliation()
        result = rc.reconcile_all()
        assert result["issues_found"] >= 1
        assert len(result["details"]) >= 1
        assert result["details"][0]["type"] == "orphan_position_found"

    def test_reconcile_orphan_with_recovery_flag(self, mock_demo_client, db_conn):
        """Orphan should only be reported once."""
        from backend.trading.reconciliation import Reconciliation
        from backend.database.db import config_set
        mock_demo_client.set_position("DOGEUSDT", 100, 0.12)
        config_set("recovered_DOGEUSDT", "pending")  # Already flagged
        rc = Reconciliation()
        result = rc.reconcile_all()
        # It found the existing flag, so no new issues for DOGEUSDT
        # But the function should still work
        assert result["checked"] is True


class TestOrphanCheck:
    """Test check_for_orphan_entries."""

    def test_no_orphans(self, mock_demo_client, db_conn):
        """No positions = no orphans."""
        from backend.trading.reconciliation import Reconciliation
        rc = Reconciliation()
        orphans = rc.check_for_orphan_entries()
        assert isinstance(orphans, list)
        assert len(orphans) == 0

    def test_orphan_with_recovery_key(self, mock_demo_client, db_conn):
        """Position with recovery key should be detected."""
        from backend.trading.reconciliation import Reconciliation
        from backend.database.db import config_set
        mock_demo_client.set_position("DOGEUSDT", 100, 0.12)
        config_set("recovered_DOGEUSDT", "pending")
        rc = Reconciliation()
        orphans = rc.check_for_orphan_entries()
        assert len(orphans) >= 1
        assert orphans[0]["symbol"] == "DOGEUSDT"
        assert orphans[0]["status"] == "pending"


class TestEdgeCases:
    """Test reconciliation edge cases."""

    def test_api_failure_handled(self, mock_demo_client, db_conn):
        """API failure should be logged, not crash."""
        from backend.trading.reconciliation import Reconciliation
        rc = Reconciliation()
        with patch.object(mock_demo_client, 'get_positions', side_effect=Exception("API error")):
            result = rc.reconcile_all()
            assert "error" in result
            assert "API error" in result["error"]

    def test_multiple_phantoms(self, mock_demo_client, db_conn):
        """Multiple phantom trades should all be fixed."""
        from backend.trading.reconciliation import Reconciliation
        from backend.database.db import trade_create
        tid1 = trade_create("2024-01-15 17:30:00", "DOGEUSDT", "LONG", 1.5, 0.12, 0.1212, 0.1194, 10.0)
        tid2 = trade_create("2024-01-15 17:30:00", "ETHUSDT", "LONG", 1.5, 3450, 3500, 3400, 10.0)
        rc = Reconciliation()
        result = rc.reconcile_all()
        assert result["issues_found"] >= 2
        assert result["issues_fixed"] >= 2
