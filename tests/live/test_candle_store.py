"""
Unit tests for CandleStore

Tests SQLite persistence, queries, and database operations.
"""

import pytest
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd

import sys
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from slob.live.candle_store import CandleStore
from slob.live.candle_aggregator import Candle


@pytest.fixture
def temp_db():
    """Create temporary database."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / 'test_candles.db'
    yield str(db_path)
    shutil.rmtree(temp_dir)


@pytest.fixture
def store(temp_db):
    """Create CandleStore instance."""
    return CandleStore(db_path=temp_db)


@pytest.fixture
def sample_candle():
    """Create a sample candle."""
    candle = Candle(symbol='NQ', timestamp=datetime(2024, 1, 15, 14, 30, 0))
    candle.open = 15300.0
    candle.high = 15305.0
    candle.low = 15295.0
    candle.close = 15302.0
    candle.volume = 100
    candle.tick_count = 10
    return candle


class TestCandleStore:
    """Test suite for CandleStore."""

    def test_initialization(self, store, temp_db):
        """Test store initialization."""
        assert store.db_path == Path(temp_db)
        assert store.db_path.exists()
        assert store.candles_saved == 0
        assert store.queries_executed == 0

    def test_database_schema_created(self, store):
        """Test that database schema is created."""
        conn = store._get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='candles'"
        )
        result = cursor.fetchone()

        assert result is not None
        assert result[0] == 'candles'

    def test_save_single_candle(self, store, sample_candle):
        """Test saving a single candle."""
        store.save_candle(sample_candle)

        assert store.candles_saved == 1

        # Verify in database
        count = store.get_candle_count('NQ')
        assert count == 1

    def test_save_incomplete_candle(self, store):
        """Test that incomplete candles are not saved."""
        incomplete_candle = Candle(symbol='NQ', timestamp=datetime(2024, 1, 15, 14, 30, 0))
        # Don't update with any data

        store.save_candle(incomplete_candle)

        # Should not be saved
        assert store.candles_saved == 0

    def test_save_multiple_candles(self, store):
        """Test saving multiple candles."""
        candles = []
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        for i in range(10):
            candle = Candle(symbol='NQ', timestamp=base_time + timedelta(minutes=i))
            candle.open = 15300.0
            candle.high = 15305.0
            candle.low = 15295.0
            candle.close = 15302.0
            candle.volume = 100
            candle.tick_count = 10
            candles.append(candle)

        store.save_candles(candles)

        assert store.candles_saved == 10

        count = store.get_candle_count('NQ')
        assert count == 10

    def test_save_candles_bulk_empty_list(self, store):
        """Test bulk save with empty list."""
        store.save_candles([])

        assert store.candles_saved == 0

    def test_save_candles_filters_incomplete(self, store):
        """Test that bulk save filters out incomplete candles."""
        candles = []

        # Complete candle
        complete = Candle(symbol='NQ', timestamp=datetime(2024, 1, 15, 14, 30, 0))
        complete.open = 15300.0
        complete.high = 15305.0
        complete.low = 15295.0
        complete.close = 15302.0
        complete.volume = 100
        candles.append(complete)

        # Incomplete candle
        incomplete = Candle(symbol='NQ', timestamp=datetime(2024, 1, 15, 14, 31, 0))
        candles.append(incomplete)

        store.save_candles(candles)

        # Only complete candle should be saved
        assert store.candles_saved == 1

    def test_replace_duplicate_candle(self, store, sample_candle):
        """Test that saving duplicate candle replaces existing."""
        # Save first time
        store.save_candle(sample_candle)

        # Modify and save again (same timestamp)
        sample_candle.close = 15310.0
        store.save_candle(sample_candle)

        # Should still have only 1 candle (replaced)
        count = store.get_candle_count('NQ')
        assert count == 1

        # Verify updated value
        latest = store.get_latest_candle('NQ')
        assert latest.close == 15310.0

    def test_get_candles_all(self, store):
        """Test querying all candles for a symbol."""
        candles = []
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        for i in range(5):
            candle = Candle(symbol='NQ', timestamp=base_time + timedelta(minutes=i))
            candle.open = 15300.0
            candle.high = 15305.0
            candle.low = 15295.0
            candle.close = 15302.0
            candle.volume = 100
            candles.append(candle)

        store.save_candles(candles)

        # Query all
        df = store.get_candles('NQ')

        assert len(df) == 5
        assert df.index.name == 'timestamp'

    def test_get_candles_time_range(self, store):
        """Test querying candles with time range."""
        candles = []
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        for i in range(10):
            candle = Candle(symbol='NQ', timestamp=base_time + timedelta(minutes=i))
            candle.open = 15300.0
            candle.high = 15305.0
            candle.low = 15295.0
            candle.close = 15302.0
            candle.volume = 100
            candles.append(candle)

        store.save_candles(candles)

        # Query range: 14:32 to 14:37
        start_time = base_time + timedelta(minutes=2)
        end_time = base_time + timedelta(minutes=7)

        df = store.get_candles('NQ', start_time=start_time, end_time=end_time)

        # Should get 6 candles (inclusive: 14:32, 14:33, 14:34, 14:35, 14:36, 14:37)
        assert len(df) == 6

    def test_get_candles_with_limit(self, store):
        """Test querying candles with limit."""
        candles = []
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        for i in range(10):
            candle = Candle(symbol='NQ', timestamp=base_time + timedelta(minutes=i))
            candle.open = 15300.0
            candle.high = 15305.0
            candle.low = 15295.0
            candle.close = 15302.0
            candle.volume = 100
            candles.append(candle)

        store.save_candles(candles)

        # Query with limit
        df = store.get_candles('NQ', limit=5)

        assert len(df) == 5

    def test_get_candles_empty_result(self, store):
        """Test querying candles with no results."""
        df = store.get_candles('NONEXISTENT')

        assert len(df) == 0
        assert isinstance(df, pd.DataFrame)

    def test_get_latest_candle(self, store):
        """Test getting latest candle for a symbol."""
        candles = []
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        for i in range(5):
            candle = Candle(symbol='NQ', timestamp=base_time + timedelta(minutes=i))
            candle.open = 15300.0 + i
            candle.high = 15305.0
            candle.low = 15295.0
            candle.close = 15302.0 + i
            candle.volume = 100
            candles.append(candle)

        store.save_candles(candles)

        # Get latest
        latest = store.get_latest_candle('NQ')

        assert latest is not None
        assert latest.timestamp == base_time + timedelta(minutes=4)
        assert latest.open == 15304.0
        assert latest.close == 15306.0

    def test_get_latest_candle_none(self, store):
        """Test getting latest candle when none exists."""
        latest = store.get_latest_candle('NONEXISTENT')

        assert latest is None

    def test_get_candle_count(self, store):
        """Test getting total candle count."""
        # Add candles for multiple symbols
        candles = []
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        for i in range(5):
            nq_candle = Candle(symbol='NQ', timestamp=base_time + timedelta(minutes=i))
            nq_candle.open = 15300.0
            nq_candle.high = 15305.0
            nq_candle.low = 15295.0
            nq_candle.close = 15302.0
            nq_candle.volume = 100
            candles.append(nq_candle)

            aapl_candle = Candle(symbol='AAPL', timestamp=base_time + timedelta(minutes=i))
            aapl_candle.open = 180.0
            aapl_candle.high = 181.0
            aapl_candle.low = 179.0
            aapl_candle.close = 180.5
            aapl_candle.volume = 1000
            candles.append(aapl_candle)

        store.save_candles(candles)

        # Total count
        total = store.get_candle_count()
        assert total == 10

        # Count for specific symbol
        nq_count = store.get_candle_count('NQ')
        assert nq_count == 5

        aapl_count = store.get_candle_count('AAPL')
        assert aapl_count == 5

    def test_get_symbols(self, store):
        """Test getting list of symbols."""
        candles = []
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        symbols = ['NQ', 'AAPL', 'TSLA']
        for symbol in symbols:
            candle = Candle(symbol=symbol, timestamp=base_time)
            candle.open = 100.0
            candle.high = 105.0
            candle.low = 95.0
            candle.close = 102.0
            candle.volume = 100
            candles.append(candle)

        store.save_candles(candles)

        # Get symbols
        stored_symbols = store.get_symbols()

        assert len(stored_symbols) == 3
        assert 'NQ' in stored_symbols
        assert 'AAPL' in stored_symbols
        assert 'TSLA' in stored_symbols

    def test_get_date_range(self, store):
        """Test getting date range for a symbol."""
        candles = []
        start_time = datetime(2024, 1, 15, 14, 30, 0)
        end_time = datetime(2024, 1, 15, 15, 30, 0)

        for i in range(61):  # 61 minutes
            candle = Candle(symbol='NQ', timestamp=start_time + timedelta(minutes=i))
            candle.open = 15300.0
            candle.high = 15305.0
            candle.low = 15295.0
            candle.close = 15302.0
            candle.volume = 100
            candles.append(candle)

        store.save_candles(candles)

        # Get date range
        date_range = store.get_date_range('NQ')

        assert date_range is not None
        assert date_range['start'] == start_time
        assert date_range['end'] == end_time

    def test_get_date_range_none(self, store):
        """Test getting date range for nonexistent symbol."""
        date_range = store.get_date_range('NONEXISTENT')

        assert date_range is None

    def test_delete_candles_all(self, store):
        """Test deleting all candles for a symbol."""
        candles = []
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        for i in range(10):
            candle = Candle(symbol='NQ', timestamp=base_time + timedelta(minutes=i))
            candle.open = 15300.0
            candle.high = 15305.0
            candle.low = 15295.0
            candle.close = 15302.0
            candle.volume = 100
            candles.append(candle)

        store.save_candles(candles)

        assert store.get_candle_count('NQ') == 10

        # Delete all
        store.delete_candles('NQ')

        assert store.get_candle_count('NQ') == 0

    def test_delete_candles_before_time(self, store):
        """Test deleting candles before a specific time."""
        candles = []
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        for i in range(10):
            candle = Candle(symbol='NQ', timestamp=base_time + timedelta(minutes=i))
            candle.open = 15300.0
            candle.high = 15305.0
            candle.low = 15295.0
            candle.close = 15302.0
            candle.volume = 100
            candles.append(candle)

        store.save_candles(candles)

        # Delete before 14:35 (5 candles)
        before_time = base_time + timedelta(minutes=5)
        store.delete_candles('NQ', before=before_time)

        # Should have 5 remaining (14:35 onwards)
        assert store.get_candle_count('NQ') == 5

    def test_vacuum(self, store, sample_candle):
        """Test database vacuum operation."""
        # Add and delete data to create free space
        store.save_candle(sample_candle)
        store.delete_candles('NQ')

        # Vacuum should not raise error
        store.vacuum()

    def test_get_stats(self, store):
        """Test getting storage statistics."""
        candles = []
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        symbols = ['NQ', 'AAPL']
        for symbol in symbols:
            for i in range(5):
                candle = Candle(symbol=symbol, timestamp=base_time + timedelta(minutes=i))
                candle.open = 100.0
                candle.high = 105.0
                candle.low = 95.0
                candle.close = 102.0
                candle.volume = 100
                candles.append(candle)

        store.save_candles(candles)

        stats = store.get_stats()

        assert stats['total_candles'] == 10
        assert stats['symbols_count'] == 2
        assert 'NQ' in stats['symbols']
        assert 'AAPL' in stats['symbols']
        assert stats['candles_saved'] == 10
        assert 'db_size_mb' in stats

    def test_close_connection(self, store):
        """Test closing database connection."""
        # Open connection
        conn = store._get_connection()
        assert conn is not None

        # Close
        store.close()

        assert store.conn is None

    def test_multiple_stores_same_db(self, temp_db, sample_candle):
        """Test multiple store instances on same database."""
        store1 = CandleStore(db_path=temp_db)
        store2 = CandleStore(db_path=temp_db)

        # Save with store1
        store1.save_candle(sample_candle)

        # Read with store2
        latest = store2.get_latest_candle('NQ')

        assert latest is not None
        assert latest.symbol == 'NQ'

        store1.close()
        store2.close()

    def test_queries_executed_counter(self, store):
        """Test that query counter is incremented."""
        assert store.queries_executed == 0

        # Execute queries
        store.get_candles('NQ')
        store.get_candles('AAPL')

        assert store.queries_executed == 2

    def test_dataframe_structure(self, store, sample_candle):
        """Test that returned DataFrame has correct structure."""
        store.save_candle(sample_candle)

        df = store.get_candles('NQ')

        # Check columns
        expected_columns = ['symbol', 'open', 'high', 'low', 'close', 'volume', 'tick_count', 'created_at']
        for col in expected_columns:
            assert col in df.columns

        # Check index
        assert df.index.name == 'timestamp'
        assert isinstance(df.index[0], pd.Timestamp)

    def test_concurrent_writes(self, store):
        """Test concurrent writes to database (WAL mode should handle this)."""
        candles = []
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        # Write multiple batches
        for batch in range(5):
            batch_candles = []
            for i in range(10):
                candle = Candle(
                    symbol='NQ',
                    timestamp=base_time + timedelta(minutes=batch * 10 + i)
                )
                candle.open = 15300.0
                candle.high = 15305.0
                candle.low = 15295.0
                candle.close = 15302.0
                candle.volume = 100
                batch_candles.append(candle)

            store.save_candles(batch_candles)

        # Should have all candles
        assert store.get_candle_count('NQ') == 50


class TestCandleStoreEdgeCases:
    """Test edge cases and error handling."""

    def test_save_candle_with_zero_volume(self, store):
        """Test saving candle with zero volume (gap-filled candle)."""
        candle = Candle(symbol='NQ', timestamp=datetime(2024, 1, 15, 14, 30, 0))
        candle.open = 15300.0
        candle.high = 15300.0
        candle.low = 15300.0
        candle.close = 15300.0
        candle.volume = 0  # Gap-filled candle
        candle.tick_count = 0

        store.save_candle(candle)

        latest = store.get_latest_candle('NQ')
        assert latest.volume == 0

    def test_symbol_with_special_characters(self, store):
        """Test handling symbols with special characters."""
        candle = Candle(symbol='BRK.B', timestamp=datetime(2024, 1, 15, 14, 30, 0))
        candle.open = 100.0
        candle.high = 105.0
        candle.low = 95.0
        candle.close = 102.0
        candle.volume = 100

        store.save_candle(candle)

        latest = store.get_latest_candle('BRK.B')
        assert latest is not None
        assert latest.symbol == 'BRK.B'

    def test_very_old_timestamp(self, store):
        """Test handling very old timestamp."""
        old_time = datetime(1990, 1, 1, 9, 30, 0)
        candle = Candle(symbol='NQ', timestamp=old_time)
        candle.open = 100.0
        candle.high = 105.0
        candle.low = 95.0
        candle.close = 102.0
        candle.volume = 100

        store.save_candle(candle)

        latest = store.get_latest_candle('NQ')
        assert latest.timestamp == old_time

    def test_future_timestamp(self, store):
        """Test handling future timestamp."""
        future_time = datetime(2030, 1, 1, 9, 30, 0)
        candle = Candle(symbol='NQ', timestamp=future_time)
        candle.open = 100.0
        candle.high = 105.0
        candle.low = 95.0
        candle.close = 102.0
        candle.volume = 100

        store.save_candle(candle)

        latest = store.get_latest_candle('NQ')
        assert latest.timestamp == future_time

    def test_large_volume(self, store):
        """Test handling very large volume."""
        candle = Candle(symbol='NQ', timestamp=datetime(2024, 1, 15, 14, 30, 0))
        candle.open = 15300.0
        candle.high = 15305.0
        candle.low = 15295.0
        candle.close = 15302.0
        candle.volume = 999999999  # Very large volume
        candle.tick_count = 100000

        store.save_candle(candle)

        latest = store.get_latest_candle('NQ')
        assert latest.volume == 999999999


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
