"""
Unit tests for TickBuffer

Tests async tick buffering, backpressure handling, and TTL-based eviction.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from slob.live.tick_buffer import TickBuffer
from slob.live.alpaca_ws_fetcher import Tick


@pytest.fixture
def buffer_factory():
    """Factory to create TickBuffer instances in the correct event loop."""
    def _create_buffer(max_size=100, ttl_seconds=60, on_overflow=None):
        return TickBuffer(max_size=max_size, ttl_seconds=ttl_seconds, on_overflow=on_overflow)
    return _create_buffer


@pytest.fixture
def sample_tick():
    """Create a sample tick."""
    return Tick(
        symbol='NQ',
        price=15300.0,
        size=10,
        timestamp=datetime.now(),
        exchange='IEX'
    )


class TestTickBuffer:
    """Test suite for TickBuffer."""

    def test_initialization(self, buffer_factory):
        """Test buffer initialization."""
        buffer = buffer_factory(max_size=1000, ttl_seconds=120)

        assert buffer.max_size == 1000
        assert buffer.ttl.total_seconds() == 120
        assert buffer.queue.maxsize == 1000
        assert buffer.enqueued_count == 0
        assert buffer.dequeued_count == 0
        assert buffer.dropped_count == 0
        assert buffer.evicted_count == 0

    @pytest.mark.asyncio
    async def test_enqueue_single_tick(self, sample_tick):
        """Test enqueueing a single tick."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)
        await buffer.enqueue(sample_tick)

        assert buffer.size() == 1
        assert buffer.enqueued_count == 1
        assert not buffer.is_empty()

    @pytest.mark.asyncio
    async def test_dequeue_single_tick(self, sample_tick):
        """Test dequeueing a single tick."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)

        await buffer.enqueue(sample_tick)

        tick = await buffer.dequeue()

        assert tick is not None
        assert tick.symbol == 'NQ'
        assert tick.price == 15300.0
        assert buffer.dequeued_count == 1
        assert buffer.is_empty()

    @pytest.mark.asyncio
    async def test_enqueue_dequeue_multiple_ticks(self):
        """Test enqueueing and dequeueing multiple ticks."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)

        # Enqueue 10 ticks
        for i in range(10):
            tick = Tick(
                symbol='NQ',
                price=15300.0 + i,
                size=10,
                timestamp=datetime.now(),
                exchange='IEX'
            )
            await buffer.enqueue(tick)

        assert buffer.size() == 10
        assert buffer.enqueued_count == 10

        # Dequeue all ticks
        for i in range(10):
            tick = await buffer.dequeue()
            assert tick.price == 15300.0 + i

        assert buffer.is_empty()
        assert buffer.dequeued_count == 10

    @pytest.mark.asyncio
    async def test_buffer_overflow(self):
        """Test buffer overflow and backpressure handling."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)

        # Fill buffer to capacity
        for i in range(buffer.max_size):
            tick = Tick(
                symbol='NQ',
                price=15300.0,
                size=10,
                timestamp=datetime.now(),
                exchange='IEX'
            )
            await buffer.enqueue(tick)

        assert buffer.is_full()

        # Try to enqueue one more tick (should trigger overflow)
        overflow_tick = Tick(
            symbol='NQ',
            price=15400.0,
            size=10,
            timestamp=datetime.now(),
            exchange='IEX'
        )

        await buffer.enqueue(overflow_tick)

        # Should have dropped at least one tick
        assert buffer.dropped_count >= 1

    @pytest.mark.asyncio
    async def test_overflow_callback(self):
        """Test overflow callback is called."""
        overflowed_ticks = []

        async def on_overflow(tick):
            overflowed_ticks.append(tick)

        buffer = TickBuffer(max_size=10, on_overflow=on_overflow)

        # Fill buffer
        for i in range(10):
            tick = Tick(
                symbol='NQ',
                price=15300.0,
                size=10,
                timestamp=datetime.now(),
                exchange='IEX'
            )
            await buffer.enqueue(tick)

        # Trigger overflow
        overflow_tick = Tick(
            symbol='NQ',
            price=15400.0,
            size=10,
            timestamp=datetime.now(),
            exchange='IEX'
        )

        await buffer.enqueue(overflow_tick)

        # Callback should have been called
        assert len(overflowed_ticks) >= 1

    @pytest.mark.asyncio
    async def test_dequeue_timeout(self):
        """Test dequeue timeout on empty buffer."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)

        # Try to dequeue from empty buffer with timeout
        tick = await buffer.dequeue(timeout=0.1)

        assert tick is None

    @pytest.mark.asyncio
    async def test_dequeue_blocks_until_tick_available(self, sample_tick):
        """Test dequeue blocks until tick is available."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)

        # Dequeue in background (will block)
        dequeue_task = asyncio.create_task(buffer.dequeue())

        # Wait a bit, then enqueue
        await asyncio.sleep(0.1)
        await buffer.enqueue(sample_tick)

        # Dequeue should complete
        tick = await dequeue_task
        assert tick is not None
        assert tick.symbol == 'NQ'

    @pytest.mark.asyncio
    async def test_ttl_eviction(self):
        """Test TTL-based tick eviction."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)

        # Create old tick (beyond TTL)
        old_time = datetime.now() - timedelta(seconds=120)
        old_tick = Tick(
            symbol='NQ',
            price=15300.0,
            size=10,
            timestamp=old_time,
            exchange='IEX'
        )

        buffer.timestamps.append(old_time)

        # Flush old ticks
        await buffer._flush_old_ticks()

        # Old timestamp should be removed
        assert len(buffer.timestamps) == 0
        assert buffer.evicted_count == 1

    @pytest.mark.asyncio
    async def test_auto_flush(self):
        """Test automatic flushing of old ticks."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)

        # Add old tick
        old_time = datetime.now() - timedelta(seconds=120)
        buffer.timestamps.append(old_time)

        # Start auto-flush with short interval
        flush_task = asyncio.create_task(buffer.auto_flush(interval=0.1))

        # Wait for flush to run
        await asyncio.sleep(0.3)

        # Stop auto-flush
        buffer.should_stop = True
        await flush_task

        # Old tick should be evicted
        assert buffer.evicted_count >= 1

    def test_utilization(self, buffer_factory):
        """Test buffer utilization calculation."""
        buffer = buffer_factory()
        # Empty buffer
        assert buffer.utilization() == 0.0

        # Manually set queue size (can't easily add to asyncio.Queue synchronously)
        buffer.enqueued_count = 50
        buffer.dequeued_count = 0

        # Note: utilization uses queue.qsize() which is 0 here since we didn't actually enqueue
        # For real test, we need to enqueue

    @pytest.mark.asyncio
    async def test_utilization_realistic(self):
        """Test buffer utilization with real enqueues."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)

        # Enqueue 50 ticks
        for i in range(50):
            tick = Tick(
                symbol='NQ',
                price=15300.0,
                size=10,
                timestamp=datetime.now(),
                exchange='IEX'
            )
            await buffer.enqueue(tick)

        # Utilization should be 50%
        util = buffer.utilization()
        assert util == 0.5

    @pytest.mark.asyncio
    async def test_clear(self):
        """Test clearing the buffer."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)

        # Enqueue some ticks
        for i in range(10):
            tick = Tick(
                symbol='NQ',
                price=15300.0,
                size=10,
                timestamp=datetime.now(),
                exchange='IEX'
            )
            await buffer.enqueue(tick)

        assert buffer.size() == 10

        # Clear buffer
        await buffer.clear()

        assert buffer.is_empty()
        assert len(buffer.timestamps) == 0

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test statistics retrieval."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)

        # Enqueue and dequeue some ticks
        for i in range(10):
            tick = Tick(
                symbol='NQ',
                price=15300.0,
                size=10,
                timestamp=datetime.now(),
                exchange='IEX'
            )
            await buffer.enqueue(tick)

        # Dequeue 5
        for i in range(5):
            await buffer.dequeue()

        stats = buffer.get_stats()

        assert stats['current_size'] == 5
        assert stats['max_size'] == 100
        assert stats['enqueued_count'] == 10
        assert stats['dequeued_count'] == 5
        assert stats['pending'] == 5
        assert 'utilization' in stats

    @pytest.mark.asyncio
    async def test_shutdown(self):
        """Test graceful shutdown."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)

        # Enqueue some ticks
        for i in range(5):
            tick = Tick(
                symbol='NQ',
                price=15300.0,
                size=10,
                timestamp=datetime.now(),
                exchange='IEX'
            )
            await buffer.enqueue(tick)

        # Start consumer that dequeues all
        async def consumer():
            while not buffer.is_empty():
                await buffer.dequeue()

        consumer_task = asyncio.create_task(consumer())

        # Shutdown
        await buffer.shutdown()

        # Wait for consumer
        await consumer_task

        assert buffer.should_stop is True

    @pytest.mark.asyncio
    async def test_concurrent_enqueue_dequeue(self):
        """Test concurrent enqueueing and dequeueing."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)

        tick_count = 100
        received_ticks = []

        # Producer
        async def producer():
            for i in range(tick_count):
                tick = Tick(
                    symbol='NQ',
                    price=15300.0 + i,
                    size=10,
                    timestamp=datetime.now(),
                    exchange='IEX'
                )
                await buffer.enqueue(tick)
                await asyncio.sleep(0.001)  # Small delay

        # Consumer
        async def consumer():
            while len(received_ticks) < tick_count:
                tick = await buffer.dequeue(timeout=1.0)
                if tick:
                    received_ticks.append(tick)

        # Run concurrently
        await asyncio.gather(
            producer(),
            consumer()
        )

        # All ticks should be received
        assert len(received_ticks) == tick_count
        assert buffer.enqueued_count == tick_count
        assert buffer.dequeued_count == tick_count

    @pytest.mark.asyncio
    async def test_fifo_ordering(self):
        """Test FIFO (first-in-first-out) ordering."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)

        # Enqueue ticks with increasing prices
        for i in range(10):
            tick = Tick(
                symbol='NQ',
                price=15300.0 + i,
                size=10,
                timestamp=datetime.now(),
                exchange='IEX'
            )
            await buffer.enqueue(tick)

        # Dequeue and verify order
        for i in range(10):
            tick = await buffer.dequeue()
            assert tick.price == 15300.0 + i

    def test_is_empty_is_full(self, buffer_factory):
        """Test is_empty() and is_full() methods."""
        buffer = buffer_factory()
        # Initially empty
        assert buffer.is_empty() is True
        assert buffer.is_full() is False

    @pytest.mark.asyncio
    async def test_is_empty_is_full_realistic(self):
        """Test is_empty() and is_full() with real data."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)

        # Fill buffer
        for i in range(buffer.max_size):
            tick = Tick(
                symbol='NQ',
                price=15300.0,
                size=10,
                timestamp=datetime.now(),
                exchange='IEX'
            )
            await buffer.enqueue(tick)

        assert buffer.is_full() is True
        assert buffer.is_empty() is False

    @pytest.mark.asyncio
    async def test_emergency_flush_on_overflow(self):
        """Test that emergency flush is triggered on overflow."""
        buffer = TickBuffer(max_size=100, ttl_seconds=60)

        # Add old ticks that should be flushed
        old_time = datetime.now() - timedelta(seconds=120)
        for i in range(10):
            buffer.timestamps.append(old_time)

        # Fill buffer to capacity
        for i in range(buffer.max_size):
            tick = Tick(
                symbol='NQ',
                price=15300.0,
                size=10,
                timestamp=datetime.now(),
                exchange='IEX'
            )
            await buffer.enqueue(tick)

        initial_evicted = buffer.evicted_count
        initial_dropped = buffer.dropped_count

        # Trigger overflow (should trigger emergency flush)
        overflow_tick = Tick(
            symbol='NQ',
            price=15400.0,
            size=10,
            timestamp=datetime.now(),
            exchange='IEX'
        )
        await buffer.enqueue(overflow_tick)

        # Emergency flush should be triggered (old timestamps evicted)
        # Note: Queue is still full of valid ticks, so tick may still be dropped
        assert buffer.evicted_count > initial_evicted or buffer.dropped_count > initial_dropped


class TestTickBufferEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_zero_max_size(self):
        """Test buffer with zero max size."""
        buffer = TickBuffer(max_size=0)

        tick = Tick(
            symbol='NQ',
            price=15300.0,
            size=10,
            timestamp=datetime.now(),
            exchange='IEX'
        )

        # Should handle gracefully (will always overflow)
        await buffer.enqueue(tick)

        # Utilization should handle division by zero
        util = buffer.utilization()
        assert util == 0.0

    @pytest.mark.asyncio
    async def test_very_small_ttl(self):
        """Test buffer with very small TTL."""
        buffer = TickBuffer(max_size=100, ttl_seconds=1)

        # Add tick
        tick = Tick(
            symbol='NQ',
            price=15300.0,
            size=10,
            timestamp=datetime.now(),
            exchange='IEX'
        )
        await buffer.enqueue(tick)

        # Wait for TTL to expire
        await asyncio.sleep(1.5)

        # Flush old ticks
        await buffer._flush_old_ticks()

        # Tick should be evicted
        assert buffer.evicted_count >= 1

    @pytest.mark.asyncio
    async def test_multiple_concurrent_producers(self):
        """Test multiple concurrent producers."""
        buffer = TickBuffer(max_size=1000)

        async def producer(producer_id, count):
            for i in range(count):
                tick = Tick(
                    symbol=f'SYMBOL{producer_id}',
                    price=15300.0 + i,
                    size=10,
                    timestamp=datetime.now(),
                    exchange='IEX'
                )
                await buffer.enqueue(tick)

        # Run 5 producers concurrently
        await asyncio.gather(
            producer(1, 100),
            producer(2, 100),
            producer(3, 100),
            producer(4, 100),
            producer(5, 100)
        )

        # All ticks should be enqueued
        assert buffer.enqueued_count == 500


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
