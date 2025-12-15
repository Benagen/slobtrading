"""
Tests for YFinanceFetcher.

Run with: pytest tests/test_yfinance_fetcher.py -v
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from slob.data import YFinanceFetcher


@pytest.fixture
def fetcher():
    """Create YFinanceFetcher instance"""
    return YFinanceFetcher()


@pytest.fixture
def sample_yf_data():
    """Create sample data that mimics yfinance output"""
    dates = pd.date_range('2024-01-15 15:30', periods=100, freq='1min', tz='UTC')
    dates = dates.tz_convert('Europe/Stockholm')

    np.random.seed(42)

    # Generate valid OHLC data
    data = []
    base_price = 16000

    for i in range(100):
        # Random walk for close
        base_price += np.random.randn() * 10

        # Open near previous close
        open_price = base_price + np.random.randn() * 2
        close_price = open_price + np.random.randn() * 5

        # High is max of open/close plus some random amount
        high_price = max(open_price, close_price) + np.abs(np.random.randn() * 3)

        # Low is min of open/close minus some random amount
        low_price = min(open_price, close_price) - np.abs(np.random.randn() * 3)

        data.append({
            'Open': open_price,
            'High': high_price,
            'Low': low_price,
            'Close': close_price,
            'Volume': np.random.randint(1000, 10000)
        })

    df = pd.DataFrame(data, index=dates)
    return df


class TestYFinanceFetcher:
    """Test suite for YFinanceFetcher"""

    def test_initialization(self, fetcher):
        """Test fetcher initialization"""
        assert fetcher.name == "yfinance"
        assert fetcher.request_count == 0
        assert fetcher.last_request_time is None
        assert fetcher.MAX_RETRIES == 3
        assert fetcher.BACKOFF_FACTOR == 2

    def test_get_rate_limit(self, fetcher):
        """Test rate limit information"""
        per_min, per_day = fetcher.get_rate_limit()
        assert per_min == 30
        assert per_day == 2000

    def test_get_available_intervals(self, fetcher):
        """Test available intervals"""
        intervals = fetcher.get_available_intervals()
        assert '1m' in intervals
        assert '5m' in intervals
        assert '1h' in intervals
        assert '1d' in intervals

    def test_get_max_period(self, fetcher):
        """Test max period for different intervals"""
        assert fetcher.get_max_period('1m') == 7
        assert fetcher.get_max_period('5m') == 60
        assert fetcher.get_max_period('1d') == 36500

    def test_check_availability_recent_m1(self, fetcher):
        """Test availability check for recent M1 data (should be available)"""
        start = datetime.now() - timedelta(days=5)
        end = datetime.now()

        available = fetcher.check_availability("NQ=F", start, end, "1m")
        assert available is True

    def test_check_availability_old_m1(self, fetcher):
        """Test availability check for old M1 data (should be unavailable)"""
        start = datetime.now() - timedelta(days=60)
        end = datetime.now() - timedelta(days=59)

        available = fetcher.check_availability("NQ=F", start, end, "1m")
        assert available is False

    def test_check_availability_future_date(self, fetcher):
        """Test availability check for future date (should be unavailable)"""
        start = datetime.now() + timedelta(days=1)
        end = datetime.now() + timedelta(days=2)

        available = fetcher.check_availability("NQ=F", start, end, "1m")
        assert available is False

    def test_check_availability_m5(self, fetcher):
        """Test availability check for M5 data (should be available)"""
        start = datetime.now() - timedelta(days=30)
        end = datetime.now()

        available = fetcher.check_availability("NQ=F", start, end, "5m")
        assert available is True

    @patch('yfinance.Ticker')
    def test_fetch_ohlcv_success(self, mock_ticker, fetcher, sample_yf_data):
        """Test successful data fetch"""
        # Mock yfinance Ticker
        mock_instance = MagicMock()
        mock_instance.history.return_value = sample_yf_data
        mock_ticker.return_value = mock_instance

        # Fetch data
        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 17, 10)

        df = fetcher.fetch_ohlcv("NQ=F", start, end, "1m")

        # Verify
        assert df is not None
        assert len(df) == 100
        assert list(df.columns) == ['Open', 'High', 'Low', 'Close', 'Volume']
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.tz is not None  # Should be timezone-aware
        assert fetcher.request_count == 1

    @patch('yfinance.Ticker')
    def test_fetch_ohlcv_empty_data(self, mock_ticker, fetcher):
        """Test fetch with empty data returned"""
        # Mock yfinance to return empty DataFrame
        mock_instance = MagicMock()
        mock_instance.history.return_value = pd.DataFrame()
        mock_ticker.return_value = mock_instance

        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 17, 10)

        # Should raise ValueError after retries
        with pytest.raises(ValueError, match="Failed to fetch"):
            fetcher.fetch_ohlcv("NQ=F", start, end, "1m")

    @patch('yfinance.Ticker')
    def test_fetch_ohlcv_retry_logic(self, mock_ticker, fetcher, sample_yf_data):
        """Test retry logic with eventual success"""
        # Mock yfinance to fail twice, then succeed
        mock_instance = MagicMock()
        mock_instance.history.side_effect = [
            Exception("Network error"),
            Exception("Timeout"),
            sample_yf_data
        ]
        mock_ticker.return_value = mock_instance

        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 17, 10)

        # Should succeed on third attempt
        df = fetcher.fetch_ohlcv("NQ=F", start, end, "1m")

        assert df is not None
        assert len(df) == 100
        assert mock_instance.history.call_count == 3

    @patch('yfinance.Ticker')
    def test_fetch_ohlcv_all_retries_fail(self, mock_ticker, fetcher):
        """Test all retries failing"""
        # Mock yfinance to always fail
        mock_instance = MagicMock()
        mock_instance.history.side_effect = Exception("Persistent error")
        mock_ticker.return_value = mock_instance

        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 17, 10)

        # Should raise ValueError after all retries
        with pytest.raises(ValueError, match="Failed to fetch"):
            fetcher.fetch_ohlcv("NQ=F", start, end, "5m")

        # Should have tried MAX_RETRIES times
        assert mock_instance.history.call_count == fetcher.MAX_RETRIES

    @patch('yfinance.Ticker')
    def test_fetch_ohlcv_m1_fallback_to_m5(self, mock_ticker, fetcher, sample_yf_data):
        """Test automatic fallback from M1 to M5"""
        mock_instance = MagicMock()

        # M1 always fails, M5 succeeds
        def history_side_effect(*args, **kwargs):
            if kwargs.get('interval') == '1m':
                raise Exception("M1 not available")
            else:
                # Return M5 data (resample to 5min)
                m5_data = sample_yf_data.resample('5min').agg({
                    'Open': 'first',
                    'High': 'max',
                    'Low': 'min',
                    'Close': 'last',
                    'Volume': 'sum'
                }).dropna()
                return m5_data

        mock_instance.history.side_effect = history_side_effect
        mock_ticker.return_value = mock_instance

        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 17, 10)

        # Request M1, should fallback to M5
        df = fetcher.fetch_ohlcv("NQ=F", start, end, "1m")

        assert df is not None
        assert len(df) > 0
        # Should have called history multiple times (retries + fallback)
        assert mock_instance.history.call_count >= 4  # 3 M1 retries + 1 M5

    @patch('yfinance.Ticker')
    def test_data_validation(self, mock_ticker, fetcher):
        """Test data validation catches invalid data"""
        # Create invalid data (High < Close)
        dates = pd.date_range('2024-01-15 15:30', periods=10, freq='1min', tz='UTC')
        dates = dates.tz_convert('Europe/Stockholm')

        invalid_df = pd.DataFrame({
            'Open': [100] * 10,
            'High': [99] * 10,  # Invalid: High < Close
            'Low': [98] * 10,
            'Close': [101] * 10,
            'Volume': [1000] * 10
        }, index=dates)

        mock_instance = MagicMock()
        mock_instance.history.return_value = invalid_df
        mock_ticker.return_value = mock_instance

        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 16, 0)

        # Should raise ValueError due to validation failure
        with pytest.raises(ValueError):
            fetcher.fetch_ohlcv("NQ=F", start, end, "1m")

    @patch('yfinance.Ticker')
    def test_rate_limiting(self, mock_ticker, fetcher, sample_yf_data):
        """Test rate limiting between requests"""
        mock_instance = MagicMock()
        mock_instance.history.return_value = sample_yf_data
        mock_ticker.return_value = mock_instance

        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 16, 0)

        # First request
        start_time = datetime.now()
        fetcher.fetch_ohlcv("NQ=F", start, end, "1m")

        # Second request (should have rate limiting delay)
        fetcher.fetch_ohlcv("NQ=F", start, end, "1m")
        elapsed = (datetime.now() - start_time).total_seconds()

        # Should have taken at least 2 seconds due to rate limiting
        assert elapsed >= 2.0

    def test_repr(self, fetcher):
        """Test string representation"""
        repr_str = repr(fetcher)
        assert "YFinanceFetcher" in repr_str
        assert "requests=0" in repr_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
