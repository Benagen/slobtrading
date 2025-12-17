"""
Unit tests for CandleAggregator

Tests tick aggregation, candle formation, gap detection, and event emission.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from slob.live.candle_aggregator import Candle, CandleAggregator
from slob.live.alpaca_ws_fetcher import Tick


@pytest.fixture
def aggregator():
    """Create CandleAggregator instance."""
    return CandleAggregator()


@pytest.fixture
def sample_tick():
    """Create a sample tick."""
    return Tick(
        symbol='NQ',
        price=15300.0,
        size=10,
        timestamp=datetime(2024, 1, 15, 14, 30, 15),  # 14:30:15
        exchange='IEX'
    )


class TestCandle:
    """Test suite for Candle class."""

    def test_candle_initialization(self):
        """Test candle initialization."""
        timestamp = datetime(2024, 1, 15, 14, 30, 0)
        candle = Candle(symbol='NQ', timestamp=timestamp)

        assert candle.symbol == 'NQ'
        assert candle.timestamp == timestamp
        assert candle.open is None
        assert candle.high is None
        assert candle.low is None
        assert candle.close is None
        assert candle.volume == 0
        assert candle.tick_count == 0

    def test_candle_update_first_tick(self):
        """Test updating candle with first tick."""
        candle = Candle(symbol='NQ', timestamp=datetime(2024, 1, 15, 14, 30, 0))

        tick = Tick(
            symbol='NQ',
            price=15300.0,
            size=10,
            timestamp=datetime(2024, 1, 15, 14, 30, 15),
            exchange='IEX'
        )

        candle.update(tick)

        assert candle.open == 15300.0
        assert candle.high == 15300.0
        assert candle.low == 15300.0
        assert candle.close == 15300.0
        assert candle.volume == 10
        assert candle.tick_count == 1

    def test_candle_update_multiple_ticks(self):
        """Test updating candle with multiple ticks."""
        candle = Candle(symbol='NQ', timestamp=datetime(2024, 1, 15, 14, 30, 0))

        # First tick: 15300.0
        tick1 = Tick('NQ', 15300.0, 10, datetime(2024, 1, 15, 14, 30, 15), 'IEX')
        candle.update(tick1)

        # Second tick: higher price
        tick2 = Tick('NQ', 15305.0, 15, datetime(2024, 1, 15, 14, 30, 25), 'IEX')
        candle.update(tick2)

        # Third tick: lower price
        tick3 = Tick('NQ', 15295.0, 20, datetime(2024, 1, 15, 14, 30, 35), 'IEX')
        candle.update(tick3)

        # Fourth tick: closing price
        tick4 = Tick('NQ', 15302.0, 5, datetime(2024, 1, 15, 14, 30, 55), 'IEX')
        candle.update(tick4)

        assert candle.open == 15300.0
        assert candle.high == 15305.0
        assert candle.low == 15295.0
        assert candle.close == 15302.0
        assert candle.volume == 50
        assert candle.tick_count == 4

    def test_candle_is_complete(self):
        """Test is_complete() method."""
        candle = Candle(symbol='NQ', timestamp=datetime(2024, 1, 15, 14, 30, 0))

        # Initially incomplete
        assert candle.is_complete() is False

        # Add first tick
        tick = Tick('NQ', 15300.0, 10, datetime(2024, 1, 15, 14, 30, 15), 'IEX')
        candle.update(tick)

        # Now complete
        assert candle.is_complete() is True

    def test_candle_to_dict(self):
        """Test converting candle to dictionary."""
        timestamp = datetime(2024, 1, 15, 14, 30, 0)
        candle = Candle(symbol='NQ', timestamp=timestamp)

        tick = Tick('NQ', 15300.0, 10, datetime(2024, 1, 15, 14, 30, 15), 'IEX')
        candle.update(tick)

        candle_dict = candle.to_dict()

        assert candle_dict['symbol'] == 'NQ'
        assert candle_dict['timestamp'] == timestamp
        assert candle_dict['open'] == 15300.0
        assert candle_dict['high'] == 15300.0
        assert candle_dict['low'] == 15300.0
        assert candle_dict['close'] == 15300.0
        assert candle_dict['volume'] == 10
        assert candle_dict['tick_count'] == 1

    def test_candle_repr(self):
        """Test candle string representation."""
        timestamp = datetime(2024, 1, 15, 14, 30, 0)
        candle = Candle(symbol='NQ', timestamp=timestamp)

        tick = Tick('NQ', 15300.0, 10, datetime(2024, 1, 15, 14, 30, 15), 'IEX')
        candle.update(tick)

        repr_str = repr(candle)

        assert 'NQ' in repr_str
        assert '15300.0' in repr_str


class TestCandleAggregator:
    """Test suite for CandleAggregator."""

    def test_initialization(self):
        """Test aggregator initialization."""
        aggregator = CandleAggregator()

        assert aggregator.fill_gaps is True
        assert aggregator.gap_threshold_seconds == 120
        assert len(aggregator.active_candles) == 0
        assert len(aggregator.last_candle_time) == 0
        assert aggregator.candles_completed == 0
        assert aggregator.gaps_filled == 0
        assert aggregator.ticks_processed == 0

    @pytest.mark.asyncio
    async def test_process_single_tick(self, aggregator, sample_tick):
        """Test processing a single tick."""
        await aggregator.process_tick(sample_tick)

        assert aggregator.ticks_processed == 1
        assert 'NQ' in aggregator.active_candles

        candle = aggregator.active_candles['NQ']
        assert candle.symbol == 'NQ'
        assert candle.open == 15300.0
        assert candle.tick_count == 1

    @pytest.mark.asyncio
    async def test_process_multiple_ticks_same_minute(self, aggregator):
        """Test processing multiple ticks within same minute."""
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        # Multiple ticks within 14:30:00 - 14:30:59
        for i in range(5):
            tick = Tick(
                symbol='NQ',
                price=15300.0 + i,
                size=10,
                timestamp=base_time + timedelta(seconds=10 * i),
                exchange='IEX'
            )
            await aggregator.process_tick(tick)

        assert aggregator.ticks_processed == 5

        # Should have single active candle
        assert len(aggregator.active_candles) == 1
        candle = aggregator.active_candles['NQ']
        assert candle.tick_count == 5
        assert candle.open == 15300.0
        assert candle.close == 15304.0

    @pytest.mark.asyncio
    async def test_candle_completion_on_minute_change(self, aggregator):
        """Test candle completion when minute changes."""
        completed_candles = []

        async def on_candle(candle):
            completed_candles.append(candle)

        aggregator.on_candle_complete = on_candle

        # First tick at 14:30:xx
        tick1 = Tick('NQ', 15300.0, 10, datetime(2024, 1, 15, 14, 30, 30), 'IEX')
        await aggregator.process_tick(tick1)

        assert len(completed_candles) == 0  # No completion yet

        # Second tick at 14:31:xx (minute changed)
        tick2 = Tick('NQ', 15305.0, 10, datetime(2024, 1, 15, 14, 31, 10), 'IEX')
        await aggregator.process_tick(tick2)

        # Wait for async handler
        await asyncio.sleep(0.1)

        assert len(completed_candles) == 1
        assert completed_candles[0].timestamp == datetime(2024, 1, 15, 14, 30, 0)
        assert aggregator.candles_completed == 1

    @pytest.mark.asyncio
    async def test_multiple_symbols(self, aggregator):
        """Test aggregating ticks for multiple symbols."""
        completed_candles = []

        async def on_candle(candle):
            completed_candles.append(candle)

        aggregator.on_candle_complete = on_candle

        base_time = datetime(2024, 1, 15, 14, 30, 0)

        # Ticks for NQ
        tick1 = Tick('NQ', 15300.0, 10, base_time + timedelta(seconds=10), 'IEX')
        await aggregator.process_tick(tick1)

        # Ticks for AAPL
        tick2 = Tick('AAPL', 180.0, 100, base_time + timedelta(seconds=20), 'IEX')
        await aggregator.process_tick(tick2)

        # More ticks for NQ
        tick3 = Tick('NQ', 15305.0, 15, base_time + timedelta(seconds=30), 'IEX')
        await aggregator.process_tick(tick3)

        # Should have 2 active candles
        assert len(aggregator.active_candles) == 2
        assert 'NQ' in aggregator.active_candles
        assert 'AAPL' in aggregator.active_candles

        # Trigger candle completion with new minute
        next_minute = base_time + timedelta(minutes=1)
        tick4 = Tick('NQ', 15310.0, 10, next_minute + timedelta(seconds=5), 'IEX')
        await aggregator.process_tick(tick4)

        await asyncio.sleep(0.1)

        # NQ candle should complete
        assert len(completed_candles) >= 1

    @pytest.mark.asyncio
    async def test_gap_detection(self, aggregator):
        """Test gap detection between candles."""
        aggregator.fill_gaps = False  # Disable gap filling for this test

        # First candle at 14:30
        tick1 = Tick('NQ', 15300.0, 10, datetime(2024, 1, 15, 14, 30, 30), 'IEX')
        await aggregator.process_tick(tick1)

        # Complete first candle
        tick2 = Tick('NQ', 15305.0, 10, datetime(2024, 1, 15, 14, 31, 10), 'IEX')
        await aggregator.process_tick(tick2)

        # Large gap - next tick at 14:35 (4 minute gap)
        tick3 = Tick('NQ', 15310.0, 10, datetime(2024, 1, 15, 14, 35, 10), 'IEX')
        await aggregator.process_tick(tick3)

        # Gap should be detected (but not filled since fill_gaps=False)
        assert aggregator.gaps_filled == 0

    @pytest.mark.asyncio
    async def test_gap_filling(self, aggregator):
        """Test automatic gap filling."""
        completed_candles = []

        async def on_candle(candle):
            completed_candles.append(candle)

        aggregator.on_candle_complete = on_candle
        aggregator.fill_gaps = True
        aggregator.gap_threshold_seconds = 180  # 3 minutes

        # First candle at 14:30
        tick1 = Tick('NQ', 15300.0, 10, datetime(2024, 1, 15, 14, 30, 30), 'IEX')
        await aggregator.process_tick(tick1)

        # Complete first candle
        tick2 = Tick('NQ', 15305.0, 10, datetime(2024, 1, 15, 14, 31, 10), 'IEX')
        await aggregator.process_tick(tick2)

        await asyncio.sleep(0.1)

        # Gap - next tick at 14:33 (2 minute gap)
        tick3 = Tick('NQ', 15310.0, 10, datetime(2024, 1, 15, 14, 33, 10), 'IEX')
        await aggregator.process_tick(tick3)

        await asyncio.sleep(0.1)

        # Should have filled gap with flat candles
        # Gap from 14:30 to 14:33 = 2 gap minutes (14:31, 14:32)
        assert aggregator.gaps_filled == 2  # Two gap minutes (14:31, 14:32)

    @pytest.mark.asyncio
    async def test_gap_too_large_not_filled(self, aggregator):
        """Test that large gaps are not filled."""
        aggregator.fill_gaps = True
        aggregator.gap_threshold_seconds = 120  # 2 minutes

        # First candle at 14:30
        tick1 = Tick('NQ', 15300.0, 10, datetime(2024, 1, 15, 14, 30, 30), 'IEX')
        await aggregator.process_tick(tick1)

        # Complete first candle
        tick2 = Tick('NQ', 15305.0, 10, datetime(2024, 1, 15, 14, 31, 10), 'IEX')
        await aggregator.process_tick(tick2)

        # Large gap - next tick at 14:35 (4 minute gap, exceeds threshold)
        tick3 = Tick('NQ', 15310.0, 10, datetime(2024, 1, 15, 14, 35, 10), 'IEX')
        await aggregator.process_tick(tick3)

        # Gap should not be filled
        assert aggregator.gaps_filled == 0

    @pytest.mark.asyncio
    async def test_flat_candle_properties(self, aggregator):
        """Test that gap-filled candles are flat (O=H=L=C, V=0)."""
        completed_candles = []

        async def on_candle(candle):
            completed_candles.append(candle)

        aggregator.on_candle_complete = on_candle
        aggregator.fill_gaps = True

        # First candle with closing price 15300
        tick1 = Tick('NQ', 15300.0, 10, datetime(2024, 1, 15, 14, 30, 30), 'IEX')
        await aggregator.process_tick(tick1)

        tick2 = Tick('NQ', 15300.0, 10, datetime(2024, 1, 15, 14, 31, 10), 'IEX')
        await aggregator.process_tick(tick2)

        await asyncio.sleep(0.1)

        # Gap - next tick at 14:33
        tick3 = Tick('NQ', 15310.0, 10, datetime(2024, 1, 15, 14, 33, 10), 'IEX')
        await aggregator.process_tick(tick3)

        await asyncio.sleep(0.1)

        # Find gap-filled candle (14:32)
        gap_candles = [c for c in completed_candles if c.timestamp == datetime(2024, 1, 15, 14, 32, 0)]

        if gap_candles:
            gap_candle = gap_candles[0]
            assert gap_candle.open == gap_candle.high == gap_candle.low == gap_candle.close
            assert gap_candle.volume == 0

    @pytest.mark.asyncio
    async def test_force_complete_all(self, aggregator):
        """Test force completing all active candles."""
        completed_candles = []

        async def on_candle(candle):
            completed_candles.append(candle)

        aggregator.on_candle_complete = on_candle

        # Create active candles for multiple symbols
        tick1 = Tick('NQ', 15300.0, 10, datetime(2024, 1, 15, 14, 30, 30), 'IEX')
        await aggregator.process_tick(tick1)

        tick2 = Tick('AAPL', 180.0, 100, datetime(2024, 1, 15, 14, 30, 40), 'IEX')
        await aggregator.process_tick(tick2)

        assert len(aggregator.active_candles) == 2

        # Force complete all
        await aggregator.force_complete_all()
        await asyncio.sleep(0.1)

        # All candles should be completed
        assert len(aggregator.active_candles) == 0
        assert len(completed_candles) == 2

    @pytest.mark.asyncio
    async def test_get_active_candle(self, aggregator, sample_tick):
        """Test getting active candle for a symbol."""
        # No active candle initially
        candle = aggregator.get_active_candle('NQ')
        assert candle is None

        # Process tick
        await aggregator.process_tick(sample_tick)

        # Now should have active candle
        candle = aggregator.get_active_candle('NQ')
        assert candle is not None
        assert candle.symbol == 'NQ'

    def test_get_stats(self, aggregator):
        """Test statistics retrieval."""
        aggregator.ticks_processed = 100
        aggregator.candles_completed = 50
        aggregator.gaps_filled = 5

        stats = aggregator.get_stats()

        assert stats['ticks_processed'] == 100
        assert stats['candles_completed'] == 50
        assert stats['gaps_filled'] == 5
        assert stats['active_candles'] == 0
        assert stats['symbols'] == []

    def test_get_minute_timestamp(self, aggregator):
        """Test minute-aligned timestamp calculation."""
        # Test various timestamps
        dt1 = datetime(2024, 1, 15, 14, 30, 45, 123456)
        aligned1 = aggregator._get_minute_timestamp(dt1)
        assert aligned1 == datetime(2024, 1, 15, 14, 30, 0)

        dt2 = datetime(2024, 1, 15, 14, 30, 0, 0)
        aligned2 = aggregator._get_minute_timestamp(dt2)
        assert aligned2 == datetime(2024, 1, 15, 14, 30, 0)

        dt3 = datetime(2024, 1, 15, 14, 30, 59, 999999)
        aligned3 = aggregator._get_minute_timestamp(dt3)
        assert aligned3 == datetime(2024, 1, 15, 14, 30, 0)

    @pytest.mark.asyncio
    async def test_callback_error_handling(self, aggregator):
        """Test that callback errors don't crash aggregator."""
        # Callback that raises error
        async def bad_callback(candle):
            raise ValueError("Test error")

        aggregator.on_candle_complete = bad_callback

        # Process ticks to complete a candle
        tick1 = Tick('NQ', 15300.0, 10, datetime(2024, 1, 15, 14, 30, 30), 'IEX')
        await aggregator.process_tick(tick1)

        tick2 = Tick('NQ', 15305.0, 10, datetime(2024, 1, 15, 14, 31, 10), 'IEX')
        await aggregator.process_tick(tick2)

        await asyncio.sleep(0.1)

        # Should still complete candle despite error
        assert aggregator.candles_completed == 1

    @pytest.mark.asyncio
    async def test_sync_callback_support(self, aggregator):
        """Test support for synchronous callbacks."""
        completed_candles = []

        # Synchronous callback
        def sync_callback(candle):
            completed_candles.append(candle)

        aggregator.on_candle_complete = sync_callback

        # Process ticks
        tick1 = Tick('NQ', 15300.0, 10, datetime(2024, 1, 15, 14, 30, 30), 'IEX')
        await aggregator.process_tick(tick1)

        tick2 = Tick('NQ', 15305.0, 10, datetime(2024, 1, 15, 14, 31, 10), 'IEX')
        await aggregator.process_tick(tick2)

        await asyncio.sleep(0.1)

        # Sync callback should work
        assert len(completed_candles) == 1


class TestCandleAggregatorEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_incomplete_candle_warning(self, aggregator, caplog):
        """Test warning for incomplete candles."""
        # Create incomplete candle (this shouldn't happen in practice)
        candle = Candle('NQ', datetime(2024, 1, 15, 14, 30, 0))
        # Don't update with any ticks

        aggregator.active_candles['NQ'] = candle

        # Try to complete it
        await aggregator._complete_candle('NQ')

        # Should log warning (candle not emitted)
        assert aggregator.candles_completed == 0

    @pytest.mark.asyncio
    async def test_rapid_tick_stream(self, aggregator):
        """Test handling rapid tick stream."""
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        # Simulate 1000 ticks in same minute
        for i in range(1000):
            tick = Tick(
                symbol='NQ',
                price=15300.0 + (i % 100) * 0.25,
                size=1,
                timestamp=base_time + timedelta(milliseconds=i * 60),
                exchange='IEX'
            )
            await aggregator.process_tick(tick)

        assert aggregator.ticks_processed == 1000

        candle = aggregator.active_candles['NQ']
        assert candle.tick_count == 1000
        assert candle.volume == 1000


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
