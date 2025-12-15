"""
Tests for CacheManager.

Run with: pytest tests/test_cache_manager.py -v
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import shutil

from slob.data import CacheManager


@pytest.fixture
def temp_cache_dir():
    """Create temporary cache directory"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def cache_manager(temp_cache_dir):
    """Create CacheManager instance with temp directory"""
    return CacheManager(cache_dir=temp_cache_dir)


@pytest.fixture
def sample_data():
    """Create sample OHLCV data"""
    dates = pd.date_range('2024-01-01 09:00', periods=100, freq='1min')

    np.random.seed(42)
    close_prices = 16000 + np.cumsum(np.random.randn(100) * 10)

    df = pd.DataFrame({
        'Open': close_prices + np.random.randn(100) * 5,
        'High': close_prices + np.abs(np.random.randn(100) * 10),
        'Low': close_prices - np.abs(np.random.randn(100) * 10),
        'Close': close_prices,
        'Volume': np.random.randint(1000, 10000, 100)
    }, index=dates)

    return df


class TestCacheManager:
    """Test suite for CacheManager"""

    def test_initialization(self, cache_manager, temp_cache_dir):
        """Test cache manager initialization"""
        assert cache_manager.cache_dir == Path(temp_cache_dir)
        assert cache_manager.raw_dir.exists()
        assert cache_manager.processed_dir.exists()
        assert cache_manager.db_path.exists()

    def test_store_and_retrieve_data(self, cache_manager, sample_data):
        """Test storing and retrieving data"""
        symbol = "NQ=F"
        start = datetime(2024, 1, 1, 9, 0)
        end = datetime(2024, 1, 1, 10, 40)
        interval = "1m"
        source = "yfinance"

        # Store data
        cache_manager.store_data(
            df=sample_data,
            symbol=symbol,
            start=start,
            end=end,
            interval=interval,
            source=source
        )

        # Retrieve data
        cached_df = cache_manager.get_cached_data(
            symbol=symbol,
            start=start,
            end=end,
            interval=interval,
            source=source
        )

        assert cached_df is not None
        assert len(cached_df) == len(sample_data)
        # Check values match (ignore freq attribute which may differ after parquet round-trip)
        pd.testing.assert_frame_equal(cached_df, sample_data, check_freq=False)

    def test_cache_miss(self, cache_manager):
        """Test cache miss returns None"""
        cached_df = cache_manager.get_cached_data(
            symbol="ES=F",
            start=datetime(2024, 1, 1),
            end=datetime(2024, 1, 2),
            interval="1m",
            source="polygon"
        )

        assert cached_df is None

    def test_ttl_expiration(self, cache_manager, sample_data):
        """Test that expired cache returns None"""
        symbol = "NQ=F"
        start = datetime(2024, 1, 1)
        end = datetime(2024, 1, 2)
        interval = "1m"
        source = "yfinance"

        # Store with very short TTL (we'll manipulate this in DB)
        cache_manager.store_data(
            df=sample_data,
            symbol=symbol,
            start=start,
            end=end,
            interval=interval,
            source=source
        )

        # Manually set cache to expired by modifying cached_at timestamp
        import sqlite3
        conn = sqlite3.connect(cache_manager.db_path)
        cursor = conn.cursor()

        # Set cached_at to 2 days ago (older than 24h TTL for M1 data)
        old_time = (datetime.now() - timedelta(days=2)).isoformat()
        cursor.execute(
            "UPDATE cache_metadata SET cached_at = ?",
            (old_time,)
        )
        conn.commit()
        conn.close()

        # Should return None because cache is expired
        cached_df = cache_manager.get_cached_data(
            symbol=symbol,
            start=start,
            end=end,
            interval=interval,
            source=source
        )

        assert cached_df is None

    def test_find_any_source(self, cache_manager, sample_data):
        """Test finding cache from any source"""
        symbol = "NQ=F"
        start = datetime(2024, 1, 1)
        end = datetime(2024, 1, 2)
        interval = "1m"

        # Store with polygon source
        cache_manager.store_data(
            df=sample_data,
            symbol=symbol,
            start=start,
            end=end,
            interval=interval,
            source="polygon"
        )

        # Retrieve with source='any'
        cached_df = cache_manager.get_cached_data(
            symbol=symbol,
            start=start,
            end=end,
            interval=interval,
            source="any"
        )

        assert cached_df is not None
        assert len(cached_df) == len(sample_data)

    def test_cache_stats(self, cache_manager, sample_data):
        """Test cache statistics"""
        # Store some data
        cache_manager.store_data(
            df=sample_data,
            symbol="NQ=F",
            start=datetime(2024, 1, 1),
            end=datetime(2024, 1, 2),
            interval="1m",
            source="yfinance"
        )

        stats = cache_manager.get_cache_stats()

        assert stats['total_entries'] == 1
        assert stats['valid_entries'] == 1
        assert stats['expired_entries'] == 0
        assert stats['total_size_mb'] > 0
        assert len(stats['interval_breakdown']) == 1
        assert stats['interval_breakdown'][0]['interval'] == '1m'

    def test_clear_expired(self, cache_manager, sample_data):
        """Test clearing expired cache entries"""
        # Store data
        cache_manager.store_data(
            df=sample_data,
            symbol="NQ=F",
            start=datetime(2024, 1, 1),
            end=datetime(2024, 1, 2),
            interval="1m",
            source="yfinance"
        )

        # Manually expire it
        import sqlite3
        conn = sqlite3.connect(cache_manager.db_path)
        cursor = conn.cursor()
        old_time = (datetime.now() - timedelta(days=2)).isoformat()
        cursor.execute("UPDATE cache_metadata SET cached_at = ?", (old_time,))
        conn.commit()
        conn.close()

        # Clear expired
        cleared = cache_manager.clear_expired()

        assert cleared == 1

        # Stats should show 0 entries
        stats = cache_manager.get_cache_stats()
        assert stats['total_entries'] == 0

    def test_multiple_intervals(self, cache_manager, sample_data):
        """Test caching multiple intervals"""
        symbol = "NQ=F"
        start = datetime(2024, 1, 1)
        end = datetime(2024, 1, 2)

        # Store M1 data
        cache_manager.store_data(
            df=sample_data,
            symbol=symbol,
            start=start,
            end=end,
            interval="1m",
            source="yfinance"
        )

        # Store M5 data (resample sample_data)
        m5_data = sample_data.resample('5min').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }).dropna()

        cache_manager.store_data(
            df=m5_data,
            symbol=symbol,
            start=start,
            end=end,
            interval="5m",
            source="yfinance"
        )

        # Retrieve both
        m1_cached = cache_manager.get_cached_data(
            symbol=symbol, start=start, end=end, interval="1m", source="yfinance"
        )
        m5_cached = cache_manager.get_cached_data(
            symbol=symbol, start=start, end=end, interval="5m", source="yfinance"
        )

        assert m1_cached is not None
        assert m5_cached is not None
        assert len(m1_cached) == len(sample_data)
        assert len(m5_cached) == len(m5_data)

        # Stats should show 2 entries
        stats = cache_manager.get_cache_stats()
        assert stats['total_entries'] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
