"""
Tests for DataAggregator.

Run with: pytest tests/test_data_aggregator.py -v
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
import tempfile
import shutil

from slob.data import DataAggregator, CacheManager, BaseDataFetcher


@pytest.fixture
def temp_cache_dir():
    """Create temporary cache directory"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def sample_m1_data():
    """Create sample M1 data"""
    dates = pd.date_range('2024-01-15 15:30', periods=100, freq='1min', tz='Europe/Stockholm')

    np.random.seed(42)
    data = []
    base_price = 16000

    for i in range(100):
        base_price += np.random.randn() * 10
        open_price = base_price + np.random.randn() * 2
        close_price = open_price + np.random.randn() * 5
        high_price = max(open_price, close_price) + np.abs(np.random.randn() * 3)
        low_price = min(open_price, close_price) - np.abs(np.random.randn() * 3)

        data.append({
            'Open': open_price,
            'High': high_price,
            'Low': low_price,
            'Close': close_price,
            'Volume': np.random.randint(1000, 10000)
        })

    return pd.DataFrame(data, index=dates)


@pytest.fixture
def sample_m5_data():
    """Create sample M5 data"""
    dates = pd.date_range('2024-01-15 15:30', periods=20, freq='5min', tz='Europe/Stockholm')

    np.random.seed(42)
    data = []
    base_price = 16000

    for i in range(20):
        base_price += np.random.randn() * 20
        open_price = base_price + np.random.randn() * 5
        close_price = open_price + np.random.randn() * 15
        high_price = max(open_price, close_price) + np.abs(np.random.randn() * 10)
        low_price = min(open_price, close_price) - np.abs(np.random.randn() * 10)

        data.append({
            'Open': open_price,
            'High': high_price,
            'Low': low_price,
            'Close': close_price,
            'Volume': np.random.randint(5000, 50000)
        })

    return pd.DataFrame(data, index=dates)


@pytest.fixture
def mock_fetcher_success(sample_m1_data):
    """Create mock fetcher that succeeds"""
    fetcher = Mock(spec=BaseDataFetcher)
    fetcher.name = "mock_success"
    fetcher.fetch_ohlcv.return_value = sample_m1_data
    fetcher.check_availability.return_value = True
    fetcher.get_rate_limit.return_value = (30, 2000)
    return fetcher


@pytest.fixture
def mock_fetcher_fail():
    """Create mock fetcher that fails"""
    fetcher = Mock(spec=BaseDataFetcher)
    fetcher.name = "mock_fail"
    fetcher.fetch_ohlcv.side_effect = ValueError("M1 not available")
    fetcher.check_availability.return_value = True  # Returns True but fetch fails
    fetcher.get_rate_limit.return_value = (30, 2000)
    return fetcher


@pytest.fixture
def mock_fetcher_m5_only(sample_m5_data):
    """Create mock fetcher that only provides M5 data"""
    fetcher = Mock(spec=BaseDataFetcher)
    fetcher.name = "mock_m5_only"

    def fetch_side_effect(symbol, start, end, interval):
        if interval == "1m":
            raise ValueError("M1 not available")
        elif interval == "5m":
            return sample_m5_data
        else:
            raise ValueError(f"{interval} not available")

    fetcher.fetch_ohlcv.side_effect = fetch_side_effect
    fetcher.check_availability.return_value = False  # M1 not available
    fetcher.get_rate_limit.return_value = (30, 2000)
    return fetcher


class TestDataAggregator:
    """Test suite for DataAggregator"""

    def test_initialization(self, mock_fetcher_success, temp_cache_dir):
        """Test aggregator initialization"""
        agg = DataAggregator(
            fetchers=[mock_fetcher_success],
            cache_dir=temp_cache_dir,
            use_cache=True
        )

        assert len(agg.fetchers) == 1
        assert agg.use_cache is True
        assert agg.cache is not None

    def test_initialization_no_cache(self, mock_fetcher_success):
        """Test aggregator without cache"""
        agg = DataAggregator(
            fetchers=[mock_fetcher_success],
            use_cache=False
        )

        assert agg.use_cache is False

    def test_fetch_m1_success(self, mock_fetcher_success, temp_cache_dir):
        """Test successful M1 fetch"""
        agg = DataAggregator(
            fetchers=[mock_fetcher_success],
            cache_dir=temp_cache_dir
        )

        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 17, 10)

        result = agg.fetch_data("NQ=F", start, end, "1m")

        assert result is not None
        assert 'data' in result
        assert result['source'] == 'mock_success'
        assert result['interval'] == '1m'
        assert result['synthetic'] is False
        assert result['cache_hit'] is False
        assert len(result['data']) > 0

    def test_fetch_with_cache_hit(self, mock_fetcher_success, temp_cache_dir):
        """Test cache hit on second fetch"""
        agg = DataAggregator(
            fetchers=[mock_fetcher_success],
            cache_dir=temp_cache_dir
        )

        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 17, 10)

        # First fetch (should cache)
        result1 = agg.fetch_data("NQ=F", start, end, "1m")
        assert result1['cache_hit'] is False

        # Second fetch (should hit cache)
        result2 = agg.fetch_data("NQ=F", start, end, "1m")
        assert result2['cache_hit'] is True
        assert result2['source'] == 'cache'

        # Mock should only be called once
        assert mock_fetcher_success.fetch_ohlcv.call_count == 1

    def test_force_refresh_bypasses_cache(self, mock_fetcher_success, temp_cache_dir):
        """Test force_refresh bypasses cache"""
        agg = DataAggregator(
            fetchers=[mock_fetcher_success],
            cache_dir=temp_cache_dir
        )

        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 17, 10)

        # First fetch
        result1 = agg.fetch_data("NQ=F", start, end, "1m")
        assert result1['cache_hit'] is False

        # Force refresh (should bypass cache)
        result2 = agg.fetch_data("NQ=F", start, end, "1m", force_refresh=True)
        assert result2['cache_hit'] is False

        # Mock should be called twice
        assert mock_fetcher_success.fetch_ohlcv.call_count == 2

    def test_fallback_to_next_fetcher(self, mock_fetcher_fail, mock_fetcher_success, temp_cache_dir):
        """Test fallback to next fetcher when first fails"""
        agg = DataAggregator(
            fetchers=[mock_fetcher_fail, mock_fetcher_success],
            cache_dir=temp_cache_dir
        )

        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 17, 10)

        result = agg.fetch_data("NQ=F", start, end, "1m")

        # Should succeed with second fetcher
        assert result['source'] == 'mock_success'
        assert result['cache_hit'] is False

        # Both fetchers should have been tried
        assert mock_fetcher_fail.fetch_ohlcv.called
        assert mock_fetcher_success.fetch_ohlcv.called

    def test_synthetic_m1_generation(self, mock_fetcher_m5_only, temp_cache_dir):
        """Test synthetic M1 generation from M5 data"""
        agg = DataAggregator(
            fetchers=[mock_fetcher_m5_only],
            cache_dir=temp_cache_dir
        )

        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 17, 10)

        result = agg.fetch_data("NQ=F", start, end, "1m")

        assert result is not None
        assert result['synthetic'] is True
        assert result['interval'] == '1m'
        assert 'Synthetic' in result['data'].columns
        assert result['data']['Synthetic'].all()

        # Should have 5x more rows than M5 data
        assert len(result['data']) == 20 * 5  # 20 M5 candles → 100 M1 candles

    def test_all_sources_fail(self, mock_fetcher_fail, temp_cache_dir):
        """Test error when all sources fail"""
        agg = DataAggregator(
            fetchers=[mock_fetcher_fail],
            cache_dir=temp_cache_dir
        )

        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 17, 10)

        with pytest.raises(ValueError, match="Could not fetch"):
            agg.fetch_data("NQ=F", start, end, "1m")

    def test_fetch_m5_directly(self, mock_fetcher_m5_only, temp_cache_dir):
        """Test fetching M5 data directly (not for synthetic generation)"""
        agg = DataAggregator(
            fetchers=[mock_fetcher_m5_only],
            cache_dir=temp_cache_dir
        )

        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 17, 10)

        result = agg.fetch_data("NQ=F", start, end, "5m")

        assert result is not None
        assert result['interval'] == '5m'
        assert result['synthetic'] is False
        assert len(result['data']) == 20

    def test_cache_stats(self, mock_fetcher_success, temp_cache_dir):
        """Test getting cache statistics"""
        agg = DataAggregator(
            fetchers=[mock_fetcher_success],
            cache_dir=temp_cache_dir
        )

        # Fetch some data to populate cache
        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 17, 10)
        agg.fetch_data("NQ=F", start, end, "1m")

        stats = agg.get_cache_stats()

        assert stats['cache_enabled'] is True
        assert stats['total_entries'] >= 1

    def test_cache_stats_disabled(self, mock_fetcher_success):
        """Test cache stats when cache is disabled"""
        agg = DataAggregator(
            fetchers=[mock_fetcher_success],
            use_cache=False
        )

        stats = agg.get_cache_stats()
        assert stats['cache_enabled'] is False

    def test_clear_cache_expired(self, mock_fetcher_success, temp_cache_dir):
        """Test clearing expired cache entries"""
        agg = DataAggregator(
            fetchers=[mock_fetcher_success],
            cache_dir=temp_cache_dir
        )

        cleared = agg.clear_cache(expired_only=True)
        assert cleared >= 0

    def test_clear_cache_all(self, mock_fetcher_success, temp_cache_dir):
        """Test clearing all cache entries"""
        agg = DataAggregator(
            fetchers=[mock_fetcher_success],
            cache_dir=temp_cache_dir
        )

        # Fetch some data
        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 17, 10)
        agg.fetch_data("NQ=F", start, end, "1m")

        # Clear all
        cleared = agg.clear_cache(expired_only=False)
        assert cleared == -1  # Indicates all cleared

    def test_metadata_tracking(self, mock_fetcher_success, temp_cache_dir):
        """Test metadata tracking in result"""
        agg = DataAggregator(
            fetchers=[mock_fetcher_success],
            cache_dir=temp_cache_dir
        )

        start = datetime(2024, 1, 15, 15, 30)
        end = datetime(2024, 1, 15, 17, 10)

        result = agg.fetch_data("NQ=F", start, end, "1m")

        assert 'metadata' in result
        metadata = result['metadata']

        assert metadata['symbol'] == 'NQ=F'
        assert metadata['start'] == start
        assert metadata['end'] == end
        assert metadata['requested_interval'] == '1m'
        assert 'attempts' in metadata
        assert len(metadata['attempts']) > 0

    def test_repr(self, mock_fetcher_success):
        """Test string representation"""
        agg = DataAggregator(
            fetchers=[mock_fetcher_success],
            use_cache=True
        )

        repr_str = repr(agg)
        assert "DataAggregator" in repr_str
        assert "mock_success" in repr_str
        assert "cache=enabled" in repr_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
