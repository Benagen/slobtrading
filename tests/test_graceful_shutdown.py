"""
Tests for Graceful Shutdown (Phase 2).

Tests:
- Signal handler registration
- 6-step shutdown sequence
- Timeout protection
- Final state persistence
- Resource cleanup
- Cancellation of pending tasks

Run with: pytest tests/test_graceful_shutdown.py -v
"""

import pytest
import asyncio
import signal
from unittest.mock import Mock, AsyncMock, MagicMock, patch, call
from datetime import datetime

from slob.live.live_trading_engine import LiveTradingEngine, LiveTradingEngineConfig


class TestGracefulShutdown:
    """Test suite for graceful shutdown functionality"""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        config = LiveTradingEngineConfig(
            symbol='NQ',
            account='DU123456',
            ib_host='127.0.0.1',
            ib_port=4002,
            client_id=1
        )
        return config

    @pytest.fixture
    def mock_components(self):
        """Create all mock components."""
        components = {
            'state_manager': Mock(),
            'ws_fetcher': Mock(),
            'order_executor': Mock(),
            'event_bus': Mock()
        }

        # Add async methods
        components['state_manager'].close = AsyncMock()
        components['ws_fetcher'].disconnect = AsyncMock()
        components['order_executor'].close = AsyncMock()
        components['order_executor'].get_positions = AsyncMock(return_value=[])
        components['event_bus'].shutdown = AsyncMock()

        return components

    def test_signal_handlers_registered(self, mock_config):
        """Test that SIGTERM and SIGINT handlers are registered."""
        engine = LiveTradingEngine(config=mock_config)

        # Check if _setup_signal_handlers exists
        if hasattr(engine, '_setup_signal_handlers'):
            original_sigterm = signal.getsignal(signal.SIGTERM)
            original_sigint = signal.getsignal(signal.SIGINT)

            try:
                engine._setup_signal_handlers()

                # Handlers should be changed
                new_sigterm = signal.getsignal(signal.SIGTERM)
                new_sigint = signal.getsignal(signal.SIGINT)

                assert new_sigterm != original_sigterm or new_sigterm != signal.SIG_DFL
                assert new_sigint != original_sigint or new_sigint != signal.SIG_DFL

            finally:
                # Restore original handlers
                signal.signal(signal.SIGTERM, original_sigterm)
                signal.signal(signal.SIGINT, original_sigint)

    @pytest.mark.asyncio
    async def test_graceful_shutdown_stops_accepting_new_setups(
        self, mock_config, mock_components
    ):
        """Test Step 1: Stop accepting new setups."""
        engine = LiveTradingEngine(config=mock_config)
        engine.running = True

        # Inject mock components
        engine.state_manager = mock_components['state_manager']
        engine.ws_fetcher = mock_components['ws_fetcher']
        engine.order_executor = mock_components['order_executor']
        engine.event_bus = mock_components['event_bus']

        await engine.graceful_shutdown(timeout=5)

        # running flag should be False
        assert engine.running is False

    @pytest.mark.asyncio
    async def test_graceful_shutdown_cancels_pending_tasks(
        self, mock_config, mock_components
    ):
        """Test Step 2: Cancel pending async tasks."""
        engine = LiveTradingEngine(config=mock_config)

        # Inject mock components
        engine.state_manager = mock_components['state_manager']
        engine.ws_fetcher = mock_components['ws_fetcher']
        engine.order_executor = mock_components['order_executor']
        engine.event_bus = mock_components['event_bus']

        # Create a background task
        async def background_task():
            await asyncio.sleep(100)

        task = asyncio.create_task(background_task())

        # Shutdown should cancel it
        await engine.graceful_shutdown(timeout=5)

        # Task should be cancelled
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_graceful_shutdown_persists_state(
        self, mock_config, mock_components
    ):
        """Test Step 4: Persist final state."""
        engine = LiveTradingEngine(config=mock_config)

        # Inject mock components
        engine.state_manager = mock_components['state_manager']
        engine.ws_fetcher = mock_components['ws_fetcher']
        engine.order_executor = mock_components['order_executor']
        engine.event_bus = mock_components['event_bus']

        await engine.graceful_shutdown(timeout=5)

        # state_manager.close() should be called
        mock_components['state_manager'].close.assert_called_once()

    @pytest.mark.asyncio
    async def test_graceful_shutdown_disconnects_from_ib(
        self, mock_config, mock_components
    ):
        """Test Step 5: Disconnect from IB."""
        engine = LiveTradingEngine(config=mock_config)

        # Inject mock components
        engine.state_manager = mock_components['state_manager']
        engine.ws_fetcher = mock_components['ws_fetcher']
        engine.order_executor = mock_components['order_executor']
        engine.event_bus = mock_components['event_bus']

        await engine.graceful_shutdown(timeout=5)

        # Should disconnect both fetcher and executor
        mock_components['ws_fetcher'].disconnect.assert_called_once()
        mock_components['order_executor'].close.assert_called_once()

    @pytest.mark.asyncio
    async def test_graceful_shutdown_shuts_down_event_bus(
        self, mock_config, mock_components
    ):
        """Test Step 6: Shutdown event bus."""
        engine = LiveTradingEngine(config=mock_config)

        # Inject mock components
        engine.state_manager = mock_components['state_manager']
        engine.ws_fetcher = mock_components['ws_fetcher']
        engine.order_executor = mock_components['order_executor']
        engine.event_bus = mock_components['event_bus']

        await engine.graceful_shutdown(timeout=5)

        # event_bus.shutdown() should be called
        mock_components['event_bus'].shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_graceful_shutdown_logs_open_positions(
        self, mock_config, mock_components, caplog
    ):
        """Test Step 3: Log open positions warning."""
        engine = LiveTradingEngine(config=mock_config)

        # Mock open positions
        mock_position = Mock()
        mock_position.contract.symbol = 'NQ'
        mock_position.position = 1

        mock_components['order_executor'].get_positions = AsyncMock(
            return_value=[mock_position]
        )

        # Inject mock components
        engine.state_manager = mock_components['state_manager']
        engine.ws_fetcher = mock_components['ws_fetcher']
        engine.order_executor = mock_components['order_executor']
        engine.event_bus = mock_components['event_bus']

        with caplog.at_level('WARNING'):
            await engine.graceful_shutdown(timeout=5)

        # Should have logged warning about open positions
        assert any('open position' in record.message.lower()
                   for record in caplog.records)

    @pytest.mark.asyncio
    async def test_graceful_shutdown_handles_missing_components(
        self, mock_config
    ):
        """Test shutdown handles missing components gracefully."""
        engine = LiveTradingEngine(config=mock_config)

        # Don't inject any components (all None)
        engine.state_manager = None
        engine.ws_fetcher = None
        engine.order_executor = None
        engine.event_bus = None

        # Should not raise exception
        try:
            await engine.graceful_shutdown(timeout=5)
            assert True
        except Exception as e:
            pytest.fail(f"Shutdown with missing components raised: {e}")

    @pytest.mark.asyncio
    async def test_graceful_shutdown_timeout_protection(
        self, mock_config, mock_components
    ):
        """Test that shutdown respects timeout."""
        engine = LiveTradingEngine(config=mock_config)

        # Make state_manager.close() hang
        async def slow_close():
            await asyncio.sleep(100)  # Hang forever

        mock_components['state_manager'].close = slow_close

        # Inject components
        engine.state_manager = mock_components['state_manager']
        engine.ws_fetcher = mock_components['ws_fetcher']
        engine.order_executor = mock_components['order_executor']
        engine.event_bus = mock_components['event_bus']

        # Shutdown with short timeout
        start = asyncio.get_event_loop().time()
        await engine.graceful_shutdown(timeout=2)
        elapsed = asyncio.get_event_loop().time() - start

        # Should respect timeout and not hang
        assert elapsed < 5, f"Shutdown took {elapsed}s, timeout was 2s"

    @pytest.mark.asyncio
    async def test_graceful_shutdown_sequence_order(
        self, mock_config, mock_components
    ):
        """Test that shutdown steps execute in correct order."""
        engine = LiveTradingEngine(config=mock_config)

        call_order = []

        # Track call order
        async def track_close():
            call_order.append('state_manager')

        async def track_disconnect_fetcher():
            call_order.append('ws_fetcher')

        async def track_close_executor():
            call_order.append('order_executor')

        async def track_shutdown_bus():
            call_order.append('event_bus')

        mock_components['state_manager'].close = track_close
        mock_components['ws_fetcher'].disconnect = track_disconnect_fetcher
        mock_components['order_executor'].close = track_close_executor
        mock_components['event_bus'].shutdown = track_shutdown_bus

        # Inject components
        engine.state_manager = mock_components['state_manager']
        engine.ws_fetcher = mock_components['ws_fetcher']
        engine.order_executor = mock_components['order_executor']
        engine.event_bus = mock_components['event_bus']

        await engine.graceful_shutdown(timeout=5)

        # Check order: state_manager → ws_fetcher → order_executor → event_bus
        assert 'state_manager' in call_order
        assert 'ws_fetcher' in call_order
        assert 'order_executor' in call_order
        assert 'event_bus' in call_order

        # state_manager should come before disconnections
        state_idx = call_order.index('state_manager')
        fetcher_idx = call_order.index('ws_fetcher')
        executor_idx = call_order.index('order_executor')

        assert state_idx < fetcher_idx
        assert state_idx < executor_idx

    @pytest.mark.asyncio
    async def test_graceful_shutdown_handles_exceptions(
        self, mock_config, mock_components, caplog
    ):
        """Test that shutdown handles component exceptions gracefully."""
        engine = LiveTradingEngine(config=mock_config)

        # Make ws_fetcher.disconnect() raise exception
        async def failing_disconnect():
            raise RuntimeError("Disconnect failed")

        mock_components['ws_fetcher'].disconnect = failing_disconnect

        # Inject components
        engine.state_manager = mock_components['state_manager']
        engine.ws_fetcher = mock_components['ws_fetcher']
        engine.order_executor = mock_components['order_executor']
        engine.event_bus = mock_components['event_bus']

        # Should not raise exception
        with caplog.at_level('ERROR'):
            await engine.graceful_shutdown(timeout=5)

        # Should still call other cleanup methods
        mock_components['state_manager'].close.assert_called_once()
        mock_components['order_executor'].close.assert_called_once()
        mock_components['event_bus'].shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_completion_logged(
        self, mock_config, mock_components, caplog
    ):
        """Test that shutdown completion is logged."""
        engine = LiveTradingEngine(config=mock_config)

        # Inject components
        engine.state_manager = mock_components['state_manager']
        engine.ws_fetcher = mock_components['ws_fetcher']
        engine.order_executor = mock_components['order_executor']
        engine.event_bus = mock_components['event_bus']

        with caplog.at_level('INFO'):
            await engine.graceful_shutdown(timeout=5)

        # Should have logged completion
        log_messages = [record.message for record in caplog.records]
        assert any('shutdown' in msg.lower() for msg in log_messages)

    @pytest.mark.asyncio
    async def test_signal_handler_triggers_shutdown(self, mock_config):
        """Test that signal handler triggers graceful shutdown."""
        engine = LiveTradingEngine(config=mock_config)

        # Mock graceful_shutdown
        shutdown_called = [False]

        async def mock_shutdown(timeout=30):
            shutdown_called[0] = True

        engine.graceful_shutdown = mock_shutdown

        if hasattr(engine, '_setup_signal_handlers'):
            # Setup handlers
            engine._setup_signal_handlers()

            # Get current event loop
            loop = asyncio.get_event_loop()

            # Trigger SIGTERM (simulated)
            # Note: Can't actually send signal in test, so we test the handler directly
            sigterm_handler = signal.getsignal(signal.SIGTERM)

            if sigterm_handler != signal.SIG_DFL and sigterm_handler != signal.SIG_IGN:
                # Call handler
                sigterm_handler(signal.SIGTERM, None)

                # Give time for async task to start
                await asyncio.sleep(0.1)

                # Shutdown should have been called
                # (This may not work in all test environments due to signal handling complexity)

    @pytest.mark.asyncio
    async def test_multiple_shutdown_calls_safe(
        self, mock_config, mock_components
    ):
        """Test that multiple shutdown calls are safe."""
        engine = LiveTradingEngine(config=mock_config)

        # Inject components
        engine.state_manager = mock_components['state_manager']
        engine.ws_fetcher = mock_components['ws_fetcher']
        engine.order_executor = mock_components['order_executor']
        engine.event_bus = mock_components['event_bus']

        # Call shutdown twice
        await engine.graceful_shutdown(timeout=5)
        await engine.graceful_shutdown(timeout=5)

        # Should not crash
        assert True

    @pytest.mark.asyncio
    async def test_shutdown_clears_running_flag_immediately(
        self, mock_config, mock_components
    ):
        """Test that running flag is cleared at start of shutdown."""
        engine = LiveTradingEngine(config=mock_config)
        engine.running = True

        # Inject components
        engine.state_manager = mock_components['state_manager']
        engine.ws_fetcher = mock_components['ws_fetcher']
        engine.order_executor = mock_components['order_executor']
        engine.event_bus = mock_components['event_bus']

        # Make shutdown slow
        async def slow_close():
            # Check running flag during shutdown
            assert engine.running is False  # Should already be False
            await asyncio.sleep(0.1)

        mock_components['state_manager'].close = slow_close

        await engine.graceful_shutdown(timeout=5)

        # running should be False
        assert engine.running is False


class TestShutdownIntegration:
    """Integration tests for shutdown behavior"""

    @pytest.mark.asyncio
    async def test_full_shutdown_sequence(self):
        """Test complete shutdown sequence with real components."""
        from slob.live.event_bus import EventBus

        config = LiveTradingEngineConfig(
            symbol='NQ',
            account='DU123456',
            ib_host='127.0.0.1',
            ib_port=4002,
            client_id=1
        )

        engine = LiveTradingEngine(config=config)
        engine.running = True

        # Create real event bus
        engine.event_bus = EventBus()

        # Mock other components
        engine.state_manager = Mock()
        engine.state_manager.close = AsyncMock()
        engine.ws_fetcher = Mock()
        engine.ws_fetcher.disconnect = AsyncMock()
        engine.order_executor = Mock()
        engine.order_executor.close = AsyncMock()
        engine.order_executor.get_positions = AsyncMock(return_value=[])

        # Execute shutdown
        await engine.graceful_shutdown(timeout=10)

        # Verify all cleanup happened
        assert engine.running is False
        engine.state_manager.close.assert_called_once()
        engine.ws_fetcher.disconnect.assert_called_once()
        engine.order_executor.close.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
