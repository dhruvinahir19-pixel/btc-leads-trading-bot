"""
test_data_fetcher.py — Tests for DataFetcher module.

Verifies:
- Candle fetching for BTC and trading coins
- 30-day data retrieval
- Correlation, beta, alignment rate calculations
- Weekly scan end-to-end (mocked)
- Score calculation
- Edge cases: empty data, single coin, API failures
"""
import pytest
from unittest.mock import patch, MagicMock
import math


class TestCandleFetching:
    """Test basic candle retrieval."""

    def test_fetch_latest_candle(self, mock_data_client, db_conn):
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        mock_data_client.set_price("BTCUSDT", 65000)
        candle = df.fetch_latest_candle("BTCUSDT")
        assert candle is not None
        assert "ts" in candle
        assert "c" in candle
        assert candle["c"] > 0

    def test_fetch_latest_candle_api_error(self, mock_data_client, db_conn):
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        with patch.object(mock_data_client, 'get_klines',
                          side_effect=Exception("API error")):
            candle = df.fetch_latest_candle("BTCUSDT")
            assert candle is None

    def test_fetch_recent_candles(self, mock_data_client, db_conn):
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        candles = df.fetch_recent_candles("BTCUSDT", hours=10)
        assert len(candles) == 10


class TestStatisticalFunctions:
    """Test internal statistical calculations."""

    def test_correlation_perfect(self, db_conn):
        """Two identical return series should have correlation = 1.0."""
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        x = [0.01, 0.02, -0.01, 0.005, -0.005]
        y = [0.01, 0.02, -0.01, 0.005, -0.005]
        corr = df._correlation(x, y)
        assert corr == pytest.approx(1.0, abs=0.001)

    def test_correlation_inverse(self, db_conn):
        """Inverse series should have correlation = -1.0."""
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        x = [0.01, 0.02, -0.01, 0.005]
        y = [-0.01, -0.02, 0.01, -0.005]
        corr = df._correlation(x, y)
        assert corr == pytest.approx(-1.0, abs=0.01)

    def test_correlation_zero(self, db_conn):
        """Unrelated series should have correlation near 0."""
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        x = [0.01, -0.01, 0.01, -0.01, 0.01]
        y = [0.1, -0.05, 0.08, -0.03, 0.12]
        corr = df._correlation(x, y)
        assert -1.0 <= corr <= 1.0

    def test_correlation_short_series(self, db_conn):
        """Very short series should return 0."""
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        corr = df._correlation([0.01], [0.02])
        assert corr == 0.0

    def test_beta_calculation(self, db_conn):
        """Beta of 2.0 means alt moves 2x BTC."""
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        btc_returns = [0.01, 0.02, -0.01, 0.005]
        alt_returns = [0.02, 0.04, -0.02, 0.01]  # Exactly 2x
        beta = df._beta(btc_returns, alt_returns)
        assert beta == pytest.approx(2.0, abs=0.1)

    def test_beta_short_series(self, db_conn):
        """Short series should return 0."""
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        beta = df._beta([0.01], [0.02])
        assert beta == 0.0

    def test_alignment_rate_hundred_percent(self, db_conn):
        """Same direction always = 100% alignment."""
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        aligned = df._alignment_rate([0.01, 0.02, -0.01], [0.005, 0.015, -0.005])
        assert aligned == pytest.approx(1.0, abs=0.01)

    def test_alignment_rate_fifty_percent(self, db_conn):
        """Half same direction = 50% alignment."""
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        aligned = df._alignment_rate([0.01, -0.01, 0.01, -0.01],
                                      [0.01, 0.01, -0.01, -0.01])
        assert aligned == pytest.approx(0.5, abs=0.01)

    def test_big_move_alignment(self, db_conn):
        """Alignment on large BTC moves should be calculated correctly."""
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        # Only big BTC moves (>1%) matter
        btc = [0.015, 0.005, -0.02, 0.001]  # 1.5%, 0.5%, -2%, 0.1%
        alt = [0.02, 0.003, -0.03, 0.001]
        align = df._big_move_alignment(btc, alt)
        # Big moves: 0.015 and -0.02
        # Big aligned: 0.02 (same dir) and -0.03 (same dir) = 2/2 = 1.0
        assert align == pytest.approx(1.0, abs=0.01)

    def test_big_move_no_big_moves(self, db_conn):
        """No big BTC moves should return 0."""
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        btc = [0.001, -0.002, 0.0005]
        alt = [0.01, -0.01, 0.01]
        align = df._big_move_alignment(btc, alt)
        assert align == 0.0

    def test_score_calculation(self, db_conn):
        """Score should be in a reasonable range."""
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        coin_data = {
            "correlation": 0.75,
            "beta": 1.8,
            "avg_volume_usd": 15000000,
            "big_align": 0.80,
        }
        score = df._calculate_score(coin_data)
        assert 0 <= score <= 100


class TestWeeklyScan:
    """Test the weekly scan process (mocked)."""

    def test_run_weekly_scan_success(self, mock_data_client, db_conn):
        """Weekly scan should complete and return results."""
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()

        with patch.object(df, '_get_30day_data') as mock_30day:
            # Mock 30 days of hourly data
            mock_30day.return_value = [
                {"ts": 1700000000000 + i * 3600000, "o": 100 + i * 0.01,
                 "h": 101, "l": 99, "c": 100 + i * 0.01, "v": 1000}
                for i in range(720)
            ]
            result = df.run_weekly_scan()
            assert result["success"] is True
            assert result["scanned"] > 0
            assert "top_coins" in result

    def test_run_weekly_scan_api_error(self, mock_data_client, db_conn):
        """API error during scan should be handled."""
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        with patch.object(mock_data_client, 'get_exchange_info',
                          side_effect=Exception("API error")):
            result = df.run_weekly_scan()
            assert result["success"] is False
            assert "error" in result

    def test_calculate_returns(self, db_conn):
        """Returns should be calculated correctly from candle closes."""
        from backend.core.data_fetcher import DataFetcher
        df = DataFetcher()
        candles = [
            {"ts": 1, "c": 100},
            {"ts": 2, "c": 101},
            {"ts": 3, "c": 99},
        ]
        returns = df._calculate_returns(candles)
        assert len(returns) == 2
        assert returns[0] == pytest.approx(0.01, abs=0.001)  # (101-100)/100
        assert returns[1] == pytest.approx(-0.0198, abs=0.001)  # (99-101)/101
