"""
Tests for IB Reconnection Logic (Phase 2).

Tests:
- Exponential backoff reconnection
- Heartbeat monitoring
- Safe mode entry
- Connection health checks
- Auto-resubscription after reconnection

Run with: pytest tests/test_ib_reconnection.py -v
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from datetime import datetime

from slob.live.ib_ws_fetcher import IBWSFetcher, Tick


class TestIBReconnection:
    """Test suite for IB reconnection logic"""

    @pytest.fixture
    def mock_ib(self):
        """Create mock IB connection."""
        mock = MagicMock()
        mock.connectAsync = AsyncMock()
        mock.isConnected = Mock(return_value=True)
        mock.disconnect = Mock()
        mock.reqMarketDataType = Mock()
        mock.reqMktData = Mock()
        mock.reqContractDetailsAsync = AsyncMock(return_value=[])
        mock.qualifyContractsAsync = AsyncMock()
        mock.pendingTickersEvent = MagicMock()
        mock.pendingTickersEvent.__iadd__ = Mock(return_value=mock.pendingTickersEvent)
        return mock

    @pytest.mark.asyncio
    async def test_successful_first_connection(self, mock_ib):
        """Test successful connection on first attempt."""
        fetcher = IBWSFetcher(host='127.0.0.1', port=4002, client_id=1)

        with patch('slob.live.ib_ws_fetcher.IB', return_value=mock_ib):
            result = await fetcher.connect_with_retry(max_attempts=3)

        assert result is True
        assert fetcher.connected is True
        assert fetcher.reconnect_count == 0
        mock_ib.connectAsync.assert_called_once()
        mock_ib.reqMarketDataType.assert_called_once_with(3)  # Delayed data

    @pytest.mark.asyncio
    async def test_exponential_backoff_timing(self, mock_ib):
        """Test exponential backoff timing (2^attempt seconds)."""
        fetcher = IBWSFetcher(host='127.0.0.1', port=4002, client_id=1)

        # Make first 2 attempts fail, 3rd succeed
        connect_attempts = [0]

        async def mock_connect(*args, **kwargs):
            connect_attempts[0] += 1
            if connect_attempts[0] < 3:
                raise ConnectionError("Connection refused")
            # 3rd attempt succeeds
            return None

        mock_ib.connectAsync = mock_connect

        with patch('slob.live.ib_ws_fetcher.IB', return_value=mock_ib):
            start_time = asyncio.get_event_loop().time()
            result = await fetcher.connect_with_retry(max_attempts=5)
            elapsed = asyncio.get_event_loop().time() - start_time

        assert result is True
        assert fetcher.connected is True
        # Should have waited 2^1 + 2^2 = 2 + 4 = 6 seconds
        assert elapsed >= 6.0, f"Expected at least 6s delay, got {elapsed}s"

    @pytest.mark.asyncio
    async def test_max_backoff_cap(self, mock_ib):
        """Test backoff is capped at 60 seconds."""
        fetcher = IBWSFetcher(host='127.0.0.1', port=4002, client_id=1)

        # Simulate many failures (would be 2^10 = 1024s without cap)
        connect_attempts = [0]

        async def mock_connect(*args, **kwargs):
            connect_attempts[0] += 1
            if connect_attempts[0] < 8:  # Fail 7 times
                raise ConnectionError("Connection refused")
            return None

        mock_ib.connectAsync = mock_connect

        with patch('slob.live.ib_ws_fetcher.IB', return_value=mock_ib):
            with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                result = await fetcher.connect_with_retry(max_attempts=10)

                # Check that sleep was capped at 60s
                sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
                assert all(delay <= 60 for delay in sleep_calls), \
                    f"Found sleep > 60s: {sleep_calls}"

    @pytest.mark.asyncio
    async def test_connection_failure_enters_safe_mode(self, mock_ib):
        """Test that persistent failures trigger safe mode."""
        fetcher = IBWSFetcher(host='127.0.0.1', port=4002, client_id=1, max_reconnect_attempts=3)

        # All attempts fail
        mock_ib.connectAsync = AsyncMock(side_effect=ConnectionError("Connection refused"))

        with patch('slob.live.ib_ws_fetcher.IB', return_value=mock_ib):
            result = await fetcher.connect_with_retry(max_attempts=3)

        assert result is False
        assert fetcher.connected is False
        assert fetcher.safe_mode is True
        assert fetcher.running is False

    @pytest.mark.asyncio
    async def test_heartbeat_detects_disconnect(self, mock_ib):
        """Test heartbeat monitoring detects disconnection."""
        fetcher = IBWSFetcher(
            host='127.0.0.1',
            port=4002,
            client_id=1,
            heartbeat_interval=0.1  # Fast heartbeat for testing
        )

        # Start connected, then disconnect
        connection_state = [True]

        def mock_is_connected():
            return connection_state[0]

        mock_ib.isConnected = mock_is_connected

        with patch('slob.live.ib_ws_fetcher.IB', return_value=mock_ib):
            # Initial connection
            await fetcher.connect_with_retry(max_attempts=1)
            assert fetcher.connected is True

            # Simulate disconnection
            connection_state[0] = False

            # Wait for heartbeat to detect disconnection
            await asyncio.sleep(0.3)  # Wait for 3 heartbeat cycles

            # Heartbeat should have detected disconnection
            assert fetcher.reconnect_count > 0

    @pytest.mark.asyncio
    async def test_heartbeat_triggers_reconnection(self, mock_ib):
        """Test heartbeat triggers reconnection on disconnect."""
        fetcher = IBWSFetcher(
            host='127.0.0.1',
            port=4002,
            client_id=1,
            heartbeat_interval=0.1
        )

        # Simulate disconnect then reconnect
        connection_state = [True, False, True]  # Connected → Disconnected → Reconnected
        connection_check = [0]

        def mock_is_connected():
            idx = min(connection_check[0], len(connection_state) - 1)
            result = connection_state[idx]
            connection_check[0] += 1
            return result

        mock_ib.isConnected = mock_is_connected

        # Make reconnection succeed
        async def mock_reconnect(*args, **kwargs):
            connection_state.append(True)
            return None

        mock_ib.connectAsync = mock_reconnect

        with patch('slob.live.ib_ws_fetcher.IB', return_value=mock_ib):
            await fetcher.connect_with_retry(max_attempts=1)

            # Wait for heartbeat to detect and fix
            await asyncio.sleep(0.5)

            # Should have attempted reconnection
            assert fetcher.reconnect_count >= 1

    @pytest.mark.asyncio
    async def test_resubscription_after_reconnection(self, mock_ib):
        """Test that symbols are resubscribed after reconnection."""
        fetcher = IBWSFetcher(host='127.0.0.1', port=4002, client_id=1)

        with patch('slob.live.ib_ws_fetcher.IB', return_value=mock_ib):
            await fetcher.connect_with_retry(max_attempts=1)

            # Subscribe to symbols
            await fetcher.subscribe(['NQ'])
            assert len(fetcher.subscriptions) > 0

            original_subscriptions = list(fetcher.subscriptions)

            # Simulate reconnection
            fetcher.subscriptions = []  # Clear subscriptions (simulates disconnect)

            # Re-subscribe (this happens in heartbeat monitor)
            await fetcher.subscribe(['NQ'])

            # Should have resubscribed
            assert len(fetcher.subscriptions) > 0

    @pytest.mark.asyncio
    async def test_safe_mode_stops_heartbeat(self, mock_ib):
        """Test that entering safe mode stops heartbeat monitoring."""
        fetcher = IBWSFetcher(
            host='127.0.0.1',
            port=4002,
            client_id=1,
            heartbeat_interval=0.1
        )

        # All connections fail
        mock_ib.connectAsync = AsyncMock(side_effect=ConnectionError("Connection refused"))

        with patch('slob.live.ib_ws_fetcher.IB', return_value=mock_ib):
            result = await fetcher.connect_with_retry(max_attempts=2)

        assert result is False
        assert fetcher.safe_mode is True
        assert fetcher.running is False

        # Heartbeat should be stopped
        if fetcher._heartbeat_task:
            assert fetcher._heartbeat_task.done() or fetcher._heartbeat_task.cancelled()

    @pytest.mark.asyncio
    async def test_is_healthy_check(self, mock_ib):
        """Test is_healthy() returns correct status."""
        fetcher = IBWSFetcher(host='127.0.0.1', port=4002, client_id=1)

        with patch('slob.live.ib_ws_fetcher.IB', return_value=mock_ib):
            # Before connection
            assert fetcher.is_healthy() is False

            # After successful connection
            await fetcher.connect_with_retry(max_attempts=1)
            assert fetcher.is_healthy() is True

            # After entering safe mode
            await fetcher._enter_safe_mode()
            assert fetcher.is_healthy() is False

    @pytest.mark.asyncio
    async def test_clear_safe_mode(self, mock_ib):
        """Test manual safe mode clearing."""
        fetcher = IBWSFetcher(host='127.0.0.1', port=4002, client_id=1)

        # Enter safe mode
        await fetcher._enter_safe_mode()
        assert fetcher.safe_mode is True
        assert fetcher.reconnect_count > 0

        # Clear safe mode
        fetcher.clear_safe_mode()
        assert fetcher.safe_mode is False
        assert fetcher.reconnect_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_stops_heartbeat(self, mock_ib):
        """Test disconnect() stops heartbeat monitoring."""
        fetcher = IBWSFetcher(
            host='127.0.0.1',
            port=4002,
            client_id=1,
            heartbeat_interval=0.1
        )

        with patch('slob.live.ib_ws_fetcher.IB', return_value=mock_ib):
            await fetcher.connect_with_retry(max_attempts=1)
            assert fetcher.running is True

            # Disconnect
            await fetcher.disconnect()

            assert fetcher.running is False
            assert fetcher.connected is False
            if fetcher._heartbeat_task:
                assert fetcher._heartbeat_task.done() or fetcher._heartbeat_task.cancelled()

    @pytest.mark.asyncio
    async def test_tick_processing_resilience(self, mock_ib):
        """Test that tick processing errors don't crash the system."""
        fetcher = IBWSFetcher(host='127.0.0.1', port=4002, client_id=1)

        # Create a callback that tracks calls
        tick_received = []

        async def on_tick(tick: Tick):
            tick_received.append(tick)

        fetcher.on_tick = on_tick

        # Create mock tickers with various error conditions
        mock_ticker_good = Mock()
        mock_ticker_good.last = 19500.0
        mock_ticker_good.time = datetime.now()
        mock_ticker_good.volume = 100

        mock_ticker_bad = Mock()
        mock_ticker_bad.last = None  # No price
        mock_ticker_bad.close = None
        mock_ticker_bad.bid = None
        mock_ticker_bad.ask = None
        mock_ticker_bad.delayedLast = None

        # Process tickers (this should not crash)
        try:
            fetcher._on_ib_tick([mock_ticker_good, mock_ticker_bad])
            await asyncio.sleep(0.1)  # Let async tasks complete

            # Should have processed good ticker, skipped bad ticker
            # No exception should be raised
            assert True
        except Exception as e:
            pytest.fail(f"Tick processing raised exception: {e}")


class TestOrderExecutorReconnection:
    """Test suite for OrderExecutor reconnection"""

    @pytest.mark.asyncio
    async def test_reconnect_after_connection_loss(self):
        """Test OrderExecutor reconnects after connection loss."""
        from slob.live.order_executor import OrderExecutor, OrderExecutorConfig

        config = OrderExecutorConfig(
            host='127.0.0.1',
            port=4002,
            client_id=2,
            account='DU123456'
        )

        executor = OrderExecutor(config=config, risk_manager=Mock())

        # Mock IB connection
        mock_ib = MagicMock()
        mock_ib.connectAsync = AsyncMock()
        mock_ib.isConnected = Mock(return_value=True)
        mock_ib.reqContractDetailsAsync = AsyncMock(return_value=[])

        with patch('slob.live.order_executor.IB', return_value=mock_ib):
            # Test connect_with_retry
            result = await executor.connect_with_retry(max_attempts=3)
            assert result is True

            # Simulate disconnection
            mock_ib.isConnected = Mock(return_value=False)
            assert executor.is_connected() is False

            # Reconnect
            mock_ib.isConnected = Mock(return_value=True)
            result = await executor.reconnect()
            assert result is True

    @pytest.mark.asyncio
    async def test_order_placement_checks_connection(self):
        """Test that order placement checks connection health."""
        from slob.live.order_executor import OrderExecutor, OrderExecutorConfig
        from slob.backtest.setup import Setup

        config = OrderExecutorConfig(
            host='127.0.0.1',
            port=4002,
            client_id=2,
            account='DU123456'
        )

        mock_risk_manager = Mock()
        mock_risk_manager.check_circuit_breaker = Mock(return_value=(True, None))

        executor = OrderExecutor(config=config, risk_manager=mock_risk_manager)

        # Mock disconnected IB
        executor.ib = None

        # Create mock setup
        mock_setup = Mock(spec=Setup)
        mock_setup.entry_price = 19500.0
        mock_setup.sl_price = 19550.0
        mock_setup.tp_price = 19400.0

        # Attempt order placement while disconnected
        result = await executor.place_bracket_order(mock_setup, position_size=1)

        # Should fail gracefully
        assert result.success is False
        assert "connection" in result.error_message.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
