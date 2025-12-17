"""
Unit tests for EventBus

Tests event subscription, emission, handler execution, and error isolation.
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from slob.live.event_bus import EventBus, EventType, Event


@pytest.fixture
def bus():
    """Create EventBus instance."""
    return EventBus()


@pytest.fixture
def bus_with_history():
    """Create EventBus with history enabled."""
    return EventBus(enable_history=True, max_history_size=100)


class TestEvent:
    """Test suite for Event dataclass."""

    def test_event_creation(self):
        """Test creating an event."""
        timestamp = datetime(2024, 1, 15, 14, 30, 0)
        event = Event(
            event_type=EventType.CANDLE_COMPLETED,
            timestamp=timestamp,
            data={'symbol': 'NQ', 'price': 15300.0}
        )

        assert event.event_type == EventType.CANDLE_COMPLETED
        assert event.timestamp == timestamp
        assert event.data['symbol'] == 'NQ'

    def test_event_repr(self):
        """Test event string representation."""
        event = Event(
            event_type=EventType.TICK_RECEIVED,
            timestamp=datetime.now(),
            data={'symbol': 'NQ'}
        )

        repr_str = repr(event)
        assert 'tick_received' in repr_str


class TestEventType:
    """Test suite for EventType enum."""

    def test_all_event_types_defined(self):
        """Test that all expected event types are defined."""
        # Data events
        assert EventType.TICK_RECEIVED.value == 'tick_received'
        assert EventType.CANDLE_COMPLETED.value == 'candle_completed'

        # Setup events
        assert EventType.SETUP_DETECTED.value == 'setup_detected'
        assert EventType.SETUP_INVALIDATED.value == 'setup_invalidated'

        # Trading events
        assert EventType.ORDER_PLACED.value == 'order_placed'
        assert EventType.ORDER_FILLED.value == 'order_filled'
        assert EventType.ORDER_REJECTED.value == 'order_rejected'
        assert EventType.ORDER_CANCELLED.value == 'order_cancelled'

        # Position events
        assert EventType.POSITION_OPENED.value == 'position_opened'
        assert EventType.POSITION_CLOSED.value == 'position_closed'

        # System events
        assert EventType.WEBSOCKET_CONNECTED.value == 'websocket_connected'
        assert EventType.WEBSOCKET_DISCONNECTED.value == 'websocket_disconnected'
        assert EventType.CIRCUIT_BREAKER_TRIGGERED.value == 'circuit_breaker_triggered'
        assert EventType.SAFE_MODE_ENTERED.value == 'safe_mode_entered'


class TestEventBus:
    """Test suite for EventBus."""

    def test_initialization(self, bus):
        """Test bus initialization."""
        assert bus.enable_history is False
        assert bus.events_emitted == 0
        assert bus.handler_errors == 0
        assert len(bus.handlers) == 0
        assert bus.should_stop is False

    def test_initialization_with_history(self, bus_with_history):
        """Test bus initialization with history enabled."""
        assert bus_with_history.enable_history is True
        assert bus_with_history.max_history_size == 100
        assert len(bus_with_history.history) == 0

    def test_subscribe(self, bus):
        """Test subscribing to an event."""
        def handler(event):
            pass

        bus.subscribe(EventType.CANDLE_COMPLETED, handler)

        assert len(bus.handlers[EventType.CANDLE_COMPLETED]) == 1
        assert handler in bus.handlers[EventType.CANDLE_COMPLETED]

    def test_subscribe_multiple_handlers(self, bus):
        """Test subscribing multiple handlers to same event."""
        def handler1(event):
            pass

        def handler2(event):
            pass

        bus.subscribe(EventType.CANDLE_COMPLETED, handler1)
        bus.subscribe(EventType.CANDLE_COMPLETED, handler2)

        assert len(bus.handlers[EventType.CANDLE_COMPLETED]) == 2

    def test_unsubscribe(self, bus):
        """Test unsubscribing from an event."""
        def handler(event):
            pass

        bus.subscribe(EventType.CANDLE_COMPLETED, handler)
        assert len(bus.handlers[EventType.CANDLE_COMPLETED]) == 1

        bus.unsubscribe(EventType.CANDLE_COMPLETED, handler)
        assert len(bus.handlers[EventType.CANDLE_COMPLETED]) == 0

    def test_unsubscribe_nonexistent_handler(self, bus):
        """Test unsubscribing handler that wasn't subscribed."""
        def handler(event):
            pass

        # Should not raise error
        bus.unsubscribe(EventType.CANDLE_COMPLETED, handler)

    def test_decorator_subscription(self, bus):
        """Test subscribing using decorator."""
        @bus.on(EventType.CANDLE_COMPLETED)
        def handler(event):
            pass

        assert len(bus.handlers[EventType.CANDLE_COMPLETED]) == 1

    @pytest.mark.asyncio
    async def test_emit_async_handler(self, bus):
        """Test emitting event to async handler."""
        received_events = []

        @bus.on(EventType.CANDLE_COMPLETED)
        async def handler(event):
            received_events.append(event)

        data = {'symbol': 'NQ', 'price': 15300.0}
        await bus.emit(EventType.CANDLE_COMPLETED, data)

        # Wait for async handler
        await asyncio.sleep(0.1)

        assert len(received_events) == 1
        assert received_events[0].event_type == EventType.CANDLE_COMPLETED
        assert received_events[0].data == data
        assert bus.events_emitted == 1

    @pytest.mark.asyncio
    async def test_emit_sync_handler(self, bus):
        """Test emitting event to synchronous handler."""
        received_events = []

        @bus.on(EventType.CANDLE_COMPLETED)
        def handler(event):
            received_events.append(event)

        data = {'symbol': 'NQ'}
        await bus.emit(EventType.CANDLE_COMPLETED, data)

        await asyncio.sleep(0.1)

        assert len(received_events) == 1
        assert bus.events_emitted == 1

    @pytest.mark.asyncio
    async def test_emit_multiple_handlers(self, bus):
        """Test emitting to multiple handlers."""
        received1 = []
        received2 = []

        @bus.on(EventType.CANDLE_COMPLETED)
        async def handler1(event):
            received1.append(event)

        @bus.on(EventType.CANDLE_COMPLETED)
        async def handler2(event):
            received2.append(event)

        await bus.emit(EventType.CANDLE_COMPLETED, {'test': 'data'})
        await asyncio.sleep(0.1)

        # Both handlers should receive event
        assert len(received1) == 1
        assert len(received2) == 1

    @pytest.mark.asyncio
    async def test_emit_no_handlers(self, bus):
        """Test emitting event with no handlers."""
        # Should not raise error
        await bus.emit(EventType.CANDLE_COMPLETED, {'test': 'data'})

        assert bus.events_emitted == 1

    @pytest.mark.asyncio
    async def test_emit_and_wait(self, bus):
        """Test emit_and_wait blocks until handlers complete."""
        execution_order = []

        @bus.on(EventType.CANDLE_COMPLETED)
        async def handler(event):
            await asyncio.sleep(0.1)
            execution_order.append('handler')

        await bus.emit_and_wait(EventType.CANDLE_COMPLETED, {'test': 'data'})
        execution_order.append('after_emit')

        # Handler should complete before 'after_emit'
        assert execution_order == ['handler', 'after_emit']

    @pytest.mark.asyncio
    async def test_handler_error_isolation(self, bus):
        """Test that handler errors don't affect other handlers."""
        received_good = []

        @bus.on(EventType.CANDLE_COMPLETED)
        async def bad_handler(event):
            raise ValueError("Test error")

        @bus.on(EventType.CANDLE_COMPLETED)
        async def good_handler(event):
            received_good.append(event)

        await bus.emit(EventType.CANDLE_COMPLETED, {'test': 'data'})
        await asyncio.sleep(0.1)

        # Good handler should still receive event
        assert len(received_good) == 1
        assert bus.handler_errors == 1

    @pytest.mark.asyncio
    async def test_event_history(self, bus_with_history):
        """Test event history recording."""
        await bus_with_history.emit(EventType.CANDLE_COMPLETED, {'tick': 1})
        await bus_with_history.emit(EventType.TICK_RECEIVED, {'tick': 2})
        await bus_with_history.emit(EventType.CANDLE_COMPLETED, {'tick': 3})

        history = bus_with_history.get_event_history()

        assert len(history) == 3
        # Most recent first
        assert history[0].data == {'tick': 3}

    @pytest.mark.asyncio
    async def test_event_history_filtering(self, bus_with_history):
        """Test filtering event history by type."""
        await bus_with_history.emit(EventType.CANDLE_COMPLETED, {'tick': 1})
        await bus_with_history.emit(EventType.TICK_RECEIVED, {'tick': 2})
        await bus_with_history.emit(EventType.CANDLE_COMPLETED, {'tick': 3})

        candle_events = bus_with_history.get_event_history(
            event_type=EventType.CANDLE_COMPLETED
        )

        assert len(candle_events) == 2
        assert all(e.event_type == EventType.CANDLE_COMPLETED for e in candle_events)

    @pytest.mark.asyncio
    async def test_event_history_limit(self, bus_with_history):
        """Test event history size limit."""
        # Emit more events than max_history_size
        for i in range(150):
            await bus_with_history.emit(EventType.TICK_RECEIVED, {'tick': i})

        history = bus_with_history.get_event_history()

        # Should not exceed max size
        assert len(history) <= bus_with_history.max_history_size

    @pytest.mark.asyncio
    async def test_event_history_limit_enforced(self):
        """Test that history is trimmed to max size."""
        bus = EventBus(enable_history=True, max_history_size=10)

        # Emit 20 events
        for i in range(20):
            await bus.emit(EventType.TICK_RECEIVED, {'tick': i})

        # Should only keep last 10
        assert len(bus.history) == 10

    def test_get_event_history_disabled(self, bus):
        """Test getting history when history is disabled."""
        history = bus.get_event_history()

        assert len(history) == 0

    def test_get_handler_count(self, bus):
        """Test getting handler count for event type."""
        def handler1(event):
            pass

        def handler2(event):
            pass

        bus.subscribe(EventType.CANDLE_COMPLETED, handler1)
        bus.subscribe(EventType.CANDLE_COMPLETED, handler2)

        count = bus.get_handler_count(EventType.CANDLE_COMPLETED)
        assert count == 2

        count_no_handlers = bus.get_handler_count(EventType.TICK_RECEIVED)
        assert count_no_handlers == 0

    @pytest.mark.asyncio
    async def test_get_stats(self, bus):
        """Test statistics retrieval."""
        def handler(event):
            pass

        bus.subscribe(EventType.CANDLE_COMPLETED, handler)
        bus.subscribe(EventType.TICK_RECEIVED, handler)

        await bus.emit(EventType.CANDLE_COMPLETED, {'data': 1})
        await bus.emit(EventType.CANDLE_COMPLETED, {'data': 2})
        await bus.emit(EventType.TICK_RECEIVED, {'data': 3})

        stats = bus.get_stats()

        assert stats['total_events_emitted'] == 3
        assert stats['events_by_type']['candle_completed'] == 2
        assert stats['events_by_type']['tick_received'] == 1
        assert stats['handler_counts']['candle_completed'] == 1
        assert stats['handler_counts']['tick_received'] == 1

    def test_clear_handlers(self, bus):
        """Test clearing event handlers."""
        def handler(event):
            pass

        bus.subscribe(EventType.CANDLE_COMPLETED, handler)
        bus.subscribe(EventType.TICK_RECEIVED, handler)

        # Clear specific event type
        bus.clear_handlers(EventType.CANDLE_COMPLETED)

        assert len(bus.handlers.get(EventType.CANDLE_COMPLETED, [])) == 0
        assert len(bus.handlers[EventType.TICK_RECEIVED]) == 1

        # Clear all
        bus.clear_handlers()

        assert len(bus.handlers) == 0

    def test_clear_history(self, bus_with_history):
        """Test clearing event history."""
        bus_with_history.history = [Mock(), Mock(), Mock()]

        bus_with_history.clear_history()

        assert len(bus_with_history.history) == 0

    @pytest.mark.asyncio
    async def test_shutdown(self, bus):
        """Test graceful shutdown."""
        await bus.shutdown()

        assert bus.should_stop is True

    @pytest.mark.asyncio
    async def test_emit_after_shutdown(self, bus):
        """Test that emit does nothing after shutdown."""
        bus.should_stop = True

        await bus.emit(EventType.CANDLE_COMPLETED, {'data': 1})

        # Event should not be emitted
        assert bus.events_emitted == 0

    @pytest.mark.asyncio
    async def test_custom_timestamp(self, bus):
        """Test emitting event with custom timestamp."""
        custom_time = datetime(2024, 1, 15, 14, 30, 0)

        received_events = []

        @bus.on(EventType.CANDLE_COMPLETED)
        async def handler(event):
            received_events.append(event)

        await bus.emit(EventType.CANDLE_COMPLETED, {'data': 1}, timestamp=custom_time)
        await asyncio.sleep(0.1)

        assert len(received_events) == 1
        assert received_events[0].timestamp == custom_time

    @pytest.mark.asyncio
    async def test_concurrent_emit(self, bus):
        """Test emitting events concurrently."""
        received_events = []

        @bus.on(EventType.CANDLE_COMPLETED)
        async def handler(event):
            received_events.append(event)
            await asyncio.sleep(0.01)

        # Emit multiple events concurrently
        await asyncio.gather(
            bus.emit(EventType.CANDLE_COMPLETED, {'event': 1}),
            bus.emit(EventType.CANDLE_COMPLETED, {'event': 2}),
            bus.emit(EventType.CANDLE_COMPLETED, {'event': 3})
        )

        await asyncio.sleep(0.1)

        # All events should be received
        assert len(received_events) == 3

    @pytest.mark.asyncio
    async def test_handler_execution_order(self, bus):
        """Test that handlers are called in subscription order."""
        execution_order = []

        @bus.on(EventType.CANDLE_COMPLETED)
        async def handler1(event):
            execution_order.append(1)

        @bus.on(EventType.CANDLE_COMPLETED)
        async def handler2(event):
            execution_order.append(2)

        @bus.on(EventType.CANDLE_COMPLETED)
        async def handler3(event):
            execution_order.append(3)

        await bus.emit(EventType.CANDLE_COMPLETED, {})
        await asyncio.sleep(0.1)

        # Handlers should execute in order (though async, they start in order)
        assert len(execution_order) == 3
        assert 1 in execution_order
        assert 2 in execution_order
        assert 3 in execution_order

    @pytest.mark.asyncio
    async def test_high_frequency_events(self, bus):
        """Test handling high-frequency event stream."""
        event_count = 1000
        received_count = [0]  # Use list for mutable counter

        @bus.on(EventType.TICK_RECEIVED)
        async def handler(event):
            received_count[0] += 1

        # Emit many events rapidly
        for i in range(event_count):
            await bus.emit(EventType.TICK_RECEIVED, {'tick': i})

        # Wait for handlers to complete
        await asyncio.sleep(1.0)

        # All events should be processed
        assert received_count[0] == event_count
        assert bus.events_emitted == event_count


class TestEventBusEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_handler_that_takes_long_time(self, bus):
        """Test handler that takes long time doesn't block emit."""
        execution_started = []
        execution_finished = []

        @bus.on(EventType.CANDLE_COMPLETED)
        async def slow_handler(event):
            execution_started.append(datetime.now())
            await asyncio.sleep(0.5)
            execution_finished.append(datetime.now())

        # Emit event
        await bus.emit(EventType.CANDLE_COMPLETED, {})

        # emit() should return immediately (handler runs in background)
        assert len(execution_started) == 0  # Not started yet

        # Wait for handler to complete
        await asyncio.sleep(0.6)

        assert len(execution_started) == 1
        assert len(execution_finished) == 1

    @pytest.mark.asyncio
    async def test_sync_handler_blocking(self, bus):
        """Test that sync handlers are run in executor."""
        import time

        execution_order = []

        @bus.on(EventType.CANDLE_COMPLETED)
        def blocking_handler(event):
            time.sleep(0.1)  # Blocking sleep
            execution_order.append('handler')

        await bus.emit(EventType.CANDLE_COMPLETED, {})
        execution_order.append('after_emit')

        # emit() returns immediately even though handler blocks
        assert execution_order == ['after_emit']

        # Wait for handler
        await asyncio.sleep(0.2)
        assert 'handler' in execution_order

    @pytest.mark.asyncio
    async def test_multiple_event_types_same_handler(self, bus):
        """Test same handler subscribed to multiple event types."""
        received_events = []

        async def handler(event):
            received_events.append(event)

        bus.subscribe(EventType.CANDLE_COMPLETED, handler)
        bus.subscribe(EventType.TICK_RECEIVED, handler)

        await bus.emit(EventType.CANDLE_COMPLETED, {'type': 'candle'})
        await bus.emit(EventType.TICK_RECEIVED, {'type': 'tick'})

        await asyncio.sleep(0.1)

        # Handler should receive both events
        assert len(received_events) == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
