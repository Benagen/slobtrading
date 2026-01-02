"""
Event Bus

Typed event dispatcher for the live trading system.
Allows components to publish and subscribe to events asynchronously.
"""

import asyncio
import logging
from typing import Callable, Dict, List, Any, Optional
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Event types in the live trading system."""

    # Data events
    TICK_RECEIVED = "tick_received"
    CANDLE_COMPLETED = "candle_completed"

    # Setup events
    SETUP_DETECTED = "setup_detected"
    SETUP_INVALIDATED = "setup_invalidated"

    # Trading events
    ORDER_PLACED = "order_placed"
    ORDER_FILLED = "order_filled"
    ORDER_REJECTED = "order_rejected"
    ORDER_CANCELLED = "order_cancelled"

    # Position events
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"

    # System events
    WEBSOCKET_CONNECTED = "websocket_connected"
    WEBSOCKET_DISCONNECTED = "websocket_disconnected"
    CIRCUIT_BREAKER_TRIGGERED = "circuit_breaker_triggered"
    SAFE_MODE_ENTERED = "safe_mode_entered"

    # ML Shadow Mode events
    ML_SHADOW_PREDICTION = "ml_shadow_prediction"


@dataclass
class Event:
    """Base event class."""

    event_type: EventType
    timestamp: datetime
    data: Any

    def __repr__(self):
        return f"Event(type={self.event_type.value}, timestamp={self.timestamp}, data={self.data})"


class EventBus:
    """
    Async event dispatcher for the live trading system.

    Features:
    - Typed event registration
    - Multiple handlers per event type
    - Async and sync handler support
    - Error isolation (failed handlers don't affect others)
    - Statistics tracking
    - Optional event history

    Usage:
        bus = EventBus()

        # Register handler
        @bus.on(EventType.CANDLE_COMPLETED)
        async def handle_candle(event):
            print(f"Candle: {event.data}")

        # Or register directly
        bus.subscribe(EventType.CANDLE_COMPLETED, handle_candle)

        # Emit event
        await bus.emit(EventType.CANDLE_COMPLETED, candle_data)
    """

    def __init__(
        self,
        enable_history: bool = False,
        max_history_size: int = 1000
    ):
        """
        Initialize event bus.

        Args:
            enable_history: Store event history (default: False)
            max_history_size: Max events to keep in history
        """
        self.enable_history = enable_history
        self.max_history_size = max_history_size

        # Event handlers: {EventType: [handler_func, ...]}
        self.handlers: Dict[EventType, List[Callable]] = {}

        # Event history (if enabled)
        self.history: List[Event] = []

        # Statistics
        self.events_emitted = 0
        self.events_by_type: Dict[EventType, int] = {et: 0 for et in EventType}
        self.handler_errors = 0

        # Control flags
        self.should_stop = False

        # Background task tracking
        self._pending_tasks: set = set()

    def subscribe(self, event_type: EventType, handler: Callable):
        """
        Subscribe to an event type.

        Args:
            event_type: Type of event to listen for
            handler: Callback function (async or sync)

        Example:
            bus.subscribe(EventType.CANDLE_COMPLETED, handle_candle)
        """
        if event_type not in self.handlers:
            self.handlers[event_type] = []

        self.handlers[event_type].append(handler)

        logger.debug(
            f"Subscribed handler '{handler.__name__}' to {event_type.value} "
            f"(total handlers: {len(self.handlers[event_type])})"
        )

    def unsubscribe(self, event_type: EventType, handler: Callable):
        """
        Unsubscribe from an event type.

        Args:
            event_type: Event type
            handler: Handler to remove
        """
        if event_type in self.handlers:
            try:
                self.handlers[event_type].remove(handler)
                logger.debug(f"Unsubscribed handler '{handler.__name__}' from {event_type.value}")
            except ValueError:
                logger.warning(f"Handler '{handler.__name__}' not found for {event_type.value}")

    def on(self, event_type: EventType):
        """
        Decorator for subscribing to events.

        Args:
            event_type: Type of event to listen for

        Example:
            @bus.on(EventType.CANDLE_COMPLETED)
            async def handle_candle(event):
                print(event.data)
        """
        def decorator(handler: Callable):
            self.subscribe(event_type, handler)
            return handler
        return decorator

    async def emit(
        self,
        event_type: EventType,
        data: Any,
        timestamp: Optional[datetime] = None
    ):
        """
        Emit an event to all subscribers.

        Args:
            event_type: Type of event
            data: Event data (tick, candle, setup, etc.)
            timestamp: Event timestamp (default: now)

        Example:
            await bus.emit(EventType.CANDLE_COMPLETED, candle)
        """
        if self.should_stop:
            return

        # Create event
        event = Event(
            event_type=event_type,
            timestamp=timestamp or datetime.now(),
            data=data
        )

        # Update statistics
        self.events_emitted += 1
        self.events_by_type[event_type] += 1

        # Store in history
        if self.enable_history:
            self.history.append(event)

            # Trim history if needed
            if len(self.history) > self.max_history_size:
                self.history = self.history[-self.max_history_size:]

        # Get handlers
        handlers = self.handlers.get(event_type, [])

        if not handlers:
            logger.debug(f"No handlers for {event_type.value}")
            return

        # Call all handlers
        logger.debug(f"Emitting {event_type.value} to {len(handlers)} handlers")

        for handler in handlers:
            # Run each handler in background to avoid blocking
            task = asyncio.create_task(self._safe_call_handler(handler, event))
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)

    async def _safe_call_handler(self, handler: Callable, event: Event):
        """
        Safely call event handler with error handling.

        Args:
            handler: Handler function
            event: Event to pass to handler
        """
        try:
            # Check if handler is async or sync
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                # Run sync handler in executor to avoid blocking
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, handler, event)

        except Exception as e:
            self.handler_errors += 1
            logger.error(
                f"Error in handler '{handler.__name__}' for {event.event_type.value}: {e}",
                exc_info=True
            )

    async def emit_and_wait(
        self,
        event_type: EventType,
        data: Any,
        timestamp: Optional[datetime] = None
    ):
        """
        Emit event and wait for all handlers to complete.

        Use this when you need to ensure handlers have finished
        before continuing (e.g., critical events).

        Args:
            event_type: Type of event
            data: Event data
            timestamp: Event timestamp (default: now)
        """
        if self.should_stop:
            return

        # Create event
        event = Event(
            event_type=event_type,
            timestamp=timestamp or datetime.now(),
            data=data
        )

        # Update statistics
        self.events_emitted += 1
        self.events_by_type[event_type] += 1

        # Store in history
        if self.enable_history:
            self.history.append(event)
            if len(self.history) > self.max_history_size:
                self.history = self.history[-self.max_history_size:]

        # Get handlers
        handlers = self.handlers.get(event_type, [])

        if not handlers:
            return

        # Call all handlers and wait for completion
        tasks = []
        for handler in handlers:
            tasks.append(self._safe_call_handler(handler, event))

        await asyncio.gather(*tasks, return_exceptions=True)

    def get_handler_count(self, event_type: EventType) -> int:
        """
        Get number of handlers for an event type.

        Args:
            event_type: Event type

        Returns:
            Number of registered handlers
        """
        return len(self.handlers.get(event_type, []))

    def get_event_history(
        self,
        event_type: Optional[EventType] = None,
        limit: int = 100
    ) -> List[Event]:
        """
        Get event history.

        Args:
            event_type: Filter by event type (None = all events)
            limit: Max events to return

        Returns:
            List of events (most recent first)
        """
        if not self.enable_history:
            logger.warning("Event history not enabled")
            return []

        events = self.history

        # Filter by type if specified
        if event_type:
            events = [e for e in events if e.event_type == event_type]

        # Return most recent events
        return list(reversed(events[-limit:]))

    def get_stats(self) -> Dict:
        """
        Get event bus statistics.

        Returns:
            Dict with stats
        """
        return {
            'total_events_emitted': self.events_emitted,
            'handler_errors': self.handler_errors,
            'events_by_type': {
                et.value: count
                for et, count in self.events_by_type.items()
                if count > 0
            },
            'handler_counts': {
                et.value: len(handlers)
                for et, handlers in self.handlers.items()
            },
            'history_size': len(self.history) if self.enable_history else 0
        }

    def clear_handlers(self, event_type: Optional[EventType] = None):
        """
        Clear event handlers.

        Args:
            event_type: Clear handlers for specific type (None = clear all)
        """
        if event_type:
            self.handlers[event_type] = []
            logger.info(f"Cleared handlers for {event_type.value}")
        else:
            self.handlers.clear()
            logger.info("Cleared all event handlers")

    def clear_history(self):
        """Clear event history."""
        self.history.clear()
        logger.info("Event history cleared")

    async def shutdown(self):
        """Shutdown event bus gracefully."""
        logger.info("Shutting down event bus")

        self.should_stop = True

        # Wait for all pending event handlers to complete
        if self._pending_tasks:
            logger.info(f"Waiting for {len(self._pending_tasks)} pending event handlers...")
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
            logger.info("All pending event handlers completed")

        logger.info(f"✅ Event bus shutdown complete. Final stats: {self.get_stats()}")
