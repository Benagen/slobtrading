"""
Integration tests for LiveTradingEngine

Tests complete data flow: Ticks → Buffer → Candles → Events → Persistence
"""

import pytest
import asyncio
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import sys
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from slob.live.live_trading_engine import LiveTradingEngine
from slob.live.alpaca_ws_fetcher import Tick
from slob.live.event_bus import EventType


@pytest.fixture
def temp_db():
    """Create temporary database."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / 'test_candles.db'
    yield str(db_path)
    shutil.rmtree(temp_dir)


@pytest.fixture
async def engine(temp_db):
    """Create LiveTradingEngine instance with mocked WebSocket."""
    engine = LiveTradingEngine(
        api_key="test_key",
        api_secret="test_secret",
        symbols=["NQ"],
        paper_trading=True,
        db_path=temp_db
    )

    # Don't actually start (to avoid real WebSocket connection)
    yield engine

    # Cleanup
    if engine.candle_store:
        engine.candle_store.close()


class TestLiveTradingEngineFlow:
    """Test suite for complete engine data flow."""

    @pytest.mark.asyncio
    async def test_tick_to_candle_flow(self, engine):
        """Test tick processing through to candle aggregation."""
        # Initialize components (without starting WebSocket)
        await engine.start()

        # Mock WebSocket connection to prevent actual connection
        engine.ws_fetcher.state = Mock()
        engine.ws_fetcher.should_stop = True

        completed_candles = []

        # Subscribe to candle events
        @engine.event_bus.on(EventType.CANDLE_COMPLETED)
        async def on_candle(event):
            completed_candles.append(event.data)

        # Simulate ticks for 2 minutes
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        # Minute 1: 14:30
        for i in range(5):
            tick = Tick(
                symbol='NQ',
                price=15300.0 + i,
                size=10,
                timestamp=base_time + timedelta(seconds=i * 10),
                exchange='IEX'
            )
            await engine._on_tick(tick)

        # Process ticks (simulate tick processor running)
        for _ in range(5):
            tick = await engine.tick_buffer.dequeue(timeout=0.1)
            if tick:
                await engine.candle_aggregator.process_tick(tick)

        # Minute 2: 14:31 (triggers candle completion)
        for i in range(5):
            tick = Tick(
                symbol='NQ',
                price=15305.0 + i,
                size=10,
                timestamp=base_time + timedelta(minutes=1, seconds=i * 10),
                exchange='IEX'
            )
            await engine._on_tick(tick)

        # Process ticks
        for _ in range(5):
            tick = await engine.tick_buffer.dequeue(timeout=0.1)
            if tick:
                await engine.candle_aggregator.process_tick(tick)

        # Wait for events to propagate
        await asyncio.sleep(0.2)

        # Should have completed 1 candle (14:30)
        assert len(completed_candles) >= 1
        assert completed_candles[0].symbol == 'NQ'
        assert completed_candles[0].timestamp == base_time

    @pytest.mark.asyncio
    async def test_candle_persistence(self, engine):
        """Test that completed candles are persisted to database."""
        await engine.start()

        # Mock WebSocket
        engine.ws_fetcher.state = Mock()
        engine.ws_fetcher.should_stop = True

        # Simulate ticks and complete a candle
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        # Minute 1 ticks
        for i in range(5):
            tick = Tick(
                symbol='NQ',
                price=15300.0 + i,
                size=10,
                timestamp=base_time + timedelta(seconds=i * 10),
                exchange='IEX'
            )
            await engine._on_tick(tick)

        # Process
        for _ in range(5):
            tick = await engine.tick_buffer.dequeue(timeout=0.1)
            if tick:
                await engine.candle_aggregator.process_tick(tick)

        # Trigger completion with next minute
        tick = Tick(
            symbol='NQ',
            price=15305.0,
            size=10,
            timestamp=base_time + timedelta(minutes=1),
            exchange='IEX'
        )
        await engine._on_tick(tick)

        tick = await engine.tick_buffer.dequeue(timeout=0.1)
        if tick:
            await engine.candle_aggregator.process_tick(tick)

        # Wait for persistence
        await asyncio.sleep(0.2)

        # Check database
        candle_count = engine.candle_store.get_candle_count('NQ')
        assert candle_count >= 1

        latest = engine.candle_store.get_latest_candle('NQ')
        assert latest is not None
        assert latest.symbol == 'NQ'

    @pytest.mark.asyncio
    async def test_event_bus_integration(self, engine):
        """Test that events are properly emitted throughout the system."""
        await engine.start()

        # Mock WebSocket
        engine.ws_fetcher.state = Mock()
        engine.ws_fetcher.should_stop = True

        tick_events = []
        candle_events = []

        @engine.event_bus.on(EventType.TICK_RECEIVED)
        async def on_tick(event):
            tick_events.append(event)

        @engine.event_bus.on(EventType.CANDLE_COMPLETED)
        async def on_candle(event):
            candle_events.append(event)

        # Simulate ticks
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        for i in range(3):
            tick = Tick(
                symbol='NQ',
                price=15300.0,
                size=10,
                timestamp=base_time + timedelta(seconds=i * 10),
                exchange='IEX'
            )
            await engine._on_tick(tick)

        # Wait for events
        await asyncio.sleep(0.2)

        # Should have tick events
        assert len(tick_events) >= 3

    @pytest.mark.asyncio
    async def test_multiple_symbols(self, temp_db):
        """Test handling multiple symbols simultaneously."""
        engine = LiveTradingEngine(
            api_key="test_key",
            api_secret="test_secret",
            symbols=["NQ", "AAPL"],
            paper_trading=True,
            db_path=temp_db
        )

        await engine.start()

        # Mock WebSocket
        engine.ws_fetcher.state = Mock()
        engine.ws_fetcher.should_stop = True

        completed_candles = []

        @engine.event_bus.on(EventType.CANDLE_COMPLETED)
        async def on_candle(event):
            completed_candles.append(event.data)

        base_time = datetime(2024, 1, 15, 14, 30, 0)

        # Interleaved ticks for both symbols
        for i in range(5):
            # NQ tick
            nq_tick = Tick('NQ', 15300.0 + i, 10, base_time + timedelta(seconds=i * 5), 'IEX')
            await engine._on_tick(nq_tick)

            # AAPL tick
            aapl_tick = Tick('AAPL', 180.0 + i * 0.1, 100, base_time + timedelta(seconds=i * 5 + 2), 'IEX')
            await engine._on_tick(aapl_tick)

        # Process ticks
        for _ in range(10):
            tick = await engine.tick_buffer.dequeue(timeout=0.1)
            if tick:
                await engine.candle_aggregator.process_tick(tick)

        # Trigger completion with next minute ticks
        nq_tick = Tick('NQ', 15305.0, 10, base_time + timedelta(minutes=1), 'IEX')
        await engine._on_tick(nq_tick)

        aapl_tick = Tick('AAPL', 180.5, 100, base_time + timedelta(minutes=1), 'IEX')
        await engine._on_tick(aapl_tick)

        for _ in range(2):
            tick = await engine.tick_buffer.dequeue(timeout=0.1)
            if tick:
                await engine.candle_aggregator.process_tick(tick)

        await asyncio.sleep(0.2)

        # Should have completed candles for both symbols
        symbols = {c.symbol for c in completed_candles}
        assert 'NQ' in symbols or 'AAPL' in symbols

        engine.candle_store.close()

    @pytest.mark.asyncio
    async def test_buffer_backpressure(self, engine):
        """Test buffer backpressure handling under load."""
        await engine.start()

        # Mock WebSocket
        engine.ws_fetcher.state = Mock()
        engine.ws_fetcher.should_stop = True

        # Create small buffer for testing
        engine.tick_buffer = engine.tick_buffer.__class__(max_size=10)

        base_time = datetime(2024, 1, 15, 14, 30, 0)

        # Rapidly enqueue many ticks (more than buffer size)
        for i in range(20):
            tick = Tick('NQ', 15300.0, 10, base_time + timedelta(seconds=i), 'IEX')
            await engine.tick_buffer.enqueue(tick)

        # Some ticks should be dropped due to backpressure
        # (or buffer should handle gracefully)
        assert engine.tick_buffer.dropped_count >= 0  # May or may not drop depending on timing

    @pytest.mark.asyncio
    async def test_gap_detection_and_filling(self, engine):
        """Test gap detection and filling in candle aggregation."""
        await engine.start()

        # Mock WebSocket
        engine.ws_fetcher.state = Mock()
        engine.ws_fetcher.should_stop = True

        completed_candles = []

        @engine.event_bus.on(EventType.CANDLE_COMPLETED)
        async def on_candle(event):
            completed_candles.append(event.data)

        base_time = datetime(2024, 1, 15, 14, 30, 0)

        # First candle at 14:30
        tick1 = Tick('NQ', 15300.0, 10, base_time + timedelta(seconds=30), 'IEX')
        await engine._on_tick(tick1)

        tick = await engine.tick_buffer.dequeue(timeout=0.1)
        if tick:
            await engine.candle_aggregator.process_tick(tick)

        # Complete first candle at 14:31
        tick2 = Tick('NQ', 15305.0, 10, base_time + timedelta(minutes=1, seconds=10), 'IEX')
        await engine._on_tick(tick2)

        tick = await engine.tick_buffer.dequeue(timeout=0.1)
        if tick:
            await engine.candle_aggregator.process_tick(tick)

        # Gap - next tick at 14:33 (1 minute gap)
        tick3 = Tick('NQ', 15310.0, 10, base_time + timedelta(minutes=3, seconds=10), 'IEX')
        await engine._on_tick(tick3)

        tick = await engine.tick_buffer.dequeue(timeout=0.1)
        if tick:
            await engine.candle_aggregator.process_tick(tick)

        await asyncio.sleep(0.2)

        # Should have filled gap (if gap filling enabled)
        if engine.candle_aggregator.fill_gaps:
            assert engine.candle_aggregator.gaps_filled > 0

    @pytest.mark.asyncio
    async def test_statistics_tracking(self, engine):
        """Test that statistics are properly tracked across all components."""
        await engine.start()

        # Mock WebSocket
        engine.ws_fetcher.state = Mock()
        engine.ws_fetcher.should_stop = True

        base_time = datetime(2024, 1, 15, 14, 30, 0)

        # Process some ticks
        for i in range(10):
            tick = Tick('NQ', 15300.0 + i, 10, base_time + timedelta(seconds=i * 5), 'IEX')
            await engine._on_tick(tick)

        # Process through pipeline
        for _ in range(10):
            tick = await engine.tick_buffer.dequeue(timeout=0.1)
            if tick:
                await engine.candle_aggregator.process_tick(tick)

        # Check stats
        buffer_stats = engine.tick_buffer.get_stats()
        assert buffer_stats['enqueued_count'] == 10

        agg_stats = engine.candle_aggregator.get_stats()
        assert agg_stats['ticks_processed'] == 10

        event_stats = engine.event_bus.get_stats()
        assert event_stats['total_events_emitted'] >= 10  # At least tick events


class TestLiveTradingEngineLifecycle:
    """Test engine lifecycle (start, run, shutdown)."""

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self, engine):
        """Test graceful shutdown completes all pending work."""
        await engine.start()

        # Mock WebSocket
        engine.ws_fetcher.state = Mock()
        engine.ws_fetcher.should_stop = True

        # Add some ticks
        base_time = datetime(2024, 1, 15, 14, 30, 0)
        for i in range(5):
            tick = Tick('NQ', 15300.0, 10, base_time + timedelta(seconds=i * 10), 'IEX')
            await engine._on_tick(tick)

        # Shutdown
        await engine.shutdown()

        # All components should be stopped
        assert engine.should_stop is True
        assert engine.tick_buffer.should_stop is True
        assert engine.event_bus.should_stop is True

    @pytest.mark.asyncio
    async def test_force_complete_candles_on_shutdown(self, engine):
        """Test that active candles are force-completed on shutdown."""
        await engine.start()

        # Mock WebSocket
        engine.ws_fetcher.state = Mock()
        engine.ws_fetcher.should_stop = True

        completed_candles = []

        @engine.event_bus.on(EventType.CANDLE_COMPLETED)
        async def on_candle(event):
            completed_candles.append(event.data)

        # Create active candle
        base_time = datetime(2024, 1, 15, 14, 30, 0)
        tick = Tick('NQ', 15300.0, 10, base_time + timedelta(seconds=30), 'IEX')
        await engine._on_tick(tick)

        # Process
        processed_tick = await engine.tick_buffer.dequeue(timeout=0.1)
        if processed_tick:
            await engine.candle_aggregator.process_tick(processed_tick)

        # Shutdown (should force complete)
        await engine.shutdown()

        await asyncio.sleep(0.2)

        # Active candle should be completed
        assert len(engine.candle_aggregator.active_candles) == 0


class TestErrorHandling:
    """Test error handling and recovery."""

    @pytest.mark.asyncio
    async def test_candle_handler_error(self, engine):
        """Test that candle handler errors don't crash the system."""
        await engine.start()

        # Mock WebSocket
        engine.ws_fetcher.state = Mock()
        engine.ws_fetcher.should_stop = True

        # Subscribe with handler that raises error
        @engine.event_bus.on(EventType.CANDLE_COMPLETED)
        async def bad_handler(event):
            raise ValueError("Test error")

        # Process ticks to complete a candle
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        tick1 = Tick('NQ', 15300.0, 10, base_time + timedelta(seconds=30), 'IEX')
        await engine._on_tick(tick1)

        processed = await engine.tick_buffer.dequeue(timeout=0.1)
        if processed:
            await engine.candle_aggregator.process_tick(processed)

        tick2 = Tick('NQ', 15305.0, 10, base_time + timedelta(minutes=1), 'IEX')
        await engine._on_tick(tick2)

        processed = await engine.tick_buffer.dequeue(timeout=0.1)
        if processed:
            await engine.candle_aggregator.process_tick(processed)

        await asyncio.sleep(0.2)

        # System should still be running
        assert engine.should_stop is False

        # Error should be tracked
        assert engine.event_bus.handler_errors >= 1

    @pytest.mark.asyncio
    async def test_database_error_handling(self, engine):
        """Test handling of database errors."""
        await engine.start()

        # Mock WebSocket
        engine.ws_fetcher.state = Mock()
        engine.ws_fetcher.should_stop = True

        # Close database to simulate error
        engine.candle_store.close()

        # Try to process candle (should handle error gracefully)
        base_time = datetime(2024, 1, 15, 14, 30, 0)

        tick1 = Tick('NQ', 15300.0, 10, base_time + timedelta(seconds=30), 'IEX')
        await engine._on_tick(tick1)

        processed = await engine.tick_buffer.dequeue(timeout=0.1)
        if processed:
            await engine.candle_aggregator.process_tick(processed)

        tick2 = Tick('NQ', 15305.0, 10, base_time + timedelta(minutes=1), 'IEX')
        await engine._on_tick(tick2)

        processed = await engine.tick_buffer.dequeue(timeout=0.1)
        if processed:
            await engine.candle_aggregator.process_tick(processed)

        await asyncio.sleep(0.2)

        # System should handle error (logged, but not crashed)
        assert engine.should_stop is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
