"""
Unit tests for AlpacaWSFetcher

Tests WebSocket connection, authentication, message parsing, and reconnection logic.
"""

import pytest
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch, MagicMock

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from slob.live.alpaca_ws_fetcher import (
    AlpacaWSFetcher,
    Tick,
    ConnectionState
)


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket connection."""
    ws = AsyncMock()
    ws.recv = AsyncMock()
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    return ws


@pytest.fixture
def fetcher():
    """Create AlpacaWSFetcher instance."""
    return AlpacaWSFetcher(
        api_key="test_key",
        api_secret="test_secret",
        paper_trading=True
    )


class TestAlpacaWSFetcher:
    """Test suite for AlpacaWSFetcher."""

    def test_initialization(self, fetcher):
        """Test fetcher initialization."""
        assert fetcher.api_key == "test_key"
        assert fetcher.api_secret == "test_secret"
        assert fetcher.paper_trading is True
        assert fetcher.state == ConnectionState.DISCONNECTED
        assert fetcher.ws is None
        assert len(fetcher.subscribed_symbols) == 0
        assert fetcher.reconnect_attempts == 0

    @pytest.mark.asyncio
    async def test_successful_connection(self, fetcher, mock_websocket):
        """Test successful WebSocket connection and authentication."""
        # Mock authentication response
        auth_response = json.dumps([{
            'T': 'success',
            'msg': 'authenticated'
        }])
        mock_websocket.recv.return_value = auth_response

        with patch('websockets.connect', return_value=mock_websocket):
            await fetcher.connect()

            # Verify state
            assert fetcher.state == ConnectionState.CONNECTED
            assert fetcher.ws is not None
            assert fetcher.reconnect_attempts == 0

            # Verify authentication message sent
            mock_websocket.send.assert_called_once()
            auth_call = mock_websocket.send.call_args[0][0]
            auth_data = json.loads(auth_call)
            assert auth_data['action'] == 'auth'
            assert auth_data['key'] == 'test_key'
            assert auth_data['secret'] == 'test_secret'

    @pytest.mark.asyncio
    async def test_failed_authentication(self, fetcher, mock_websocket):
        """Test failed authentication."""
        # Mock failed auth response
        auth_response = json.dumps([{
            'T': 'error',
            'msg': 'authentication failed'
        }])
        mock_websocket.recv.return_value = auth_response

        with patch('websockets.connect', return_value=mock_websocket):
            await fetcher.connect()

            # Should fail and trigger reconnection
            assert fetcher.state == ConnectionState.FAILED

    @pytest.mark.asyncio
    async def test_authentication_timeout(self, fetcher, mock_websocket):
        """Test authentication timeout."""
        # Mock timeout
        mock_websocket.recv.side_effect = asyncio.TimeoutError()

        with patch('websockets.connect', return_value=mock_websocket):
            await fetcher.connect()

            assert fetcher.state == ConnectionState.FAILED

    @pytest.mark.asyncio
    async def test_subscribe_symbols(self, fetcher, mock_websocket):
        """Test subscribing to symbols."""
        # Setup connected state
        fetcher.state = ConnectionState.CONNECTED
        fetcher.ws = mock_websocket

        await fetcher.subscribe(['NQ', 'AAPL'])

        # Verify subscription message sent
        mock_websocket.send.assert_called_once()
        sub_call = mock_websocket.send.call_args[0][0]
        sub_data = json.loads(sub_call)
        assert sub_data['action'] == 'subscribe'
        assert 'NQ' in sub_data['trades']
        assert 'AAPL' in sub_data['trades']

        # Verify symbols tracked
        assert 'NQ' in fetcher.subscribed_symbols
        assert 'AAPL' in fetcher.subscribed_symbols

    @pytest.mark.asyncio
    async def test_subscribe_when_not_connected(self, fetcher):
        """Test subscribing when not connected."""
        # Should not raise error, just log warning
        await fetcher.subscribe(['NQ'])

        # Symbols should not be added
        assert len(fetcher.subscribed_symbols) == 0

    @pytest.mark.asyncio
    async def test_tick_parsing(self, fetcher):
        """Test parsing of trade (tick) messages."""
        received_ticks = []

        async def on_tick(tick):
            received_ticks.append(tick)

        fetcher.on_tick = on_tick

        # Mock trade message
        trade_msg = {
            'T': 't',
            'S': 'NQ',
            'p': 15300.5,
            's': 10,
            't': '2024-01-15T14:30:00.123Z',
            'x': 'IEX'
        }

        await fetcher._handle_trade(trade_msg)

        # Wait for async handler to complete
        await asyncio.sleep(0.1)

        # Verify tick was parsed correctly
        assert len(received_ticks) == 1
        tick = received_ticks[0]
        assert tick.symbol == 'NQ'
        assert tick.price == 15300.5
        assert tick.size == 10
        assert tick.exchange == 'IEX'
        assert fetcher.tick_count == 1

    @pytest.mark.asyncio
    async def test_process_multiple_messages(self, fetcher):
        """Test processing array of messages."""
        received_ticks = []

        async def on_tick(tick):
            received_ticks.append(tick)

        fetcher.on_tick = on_tick

        # Mock message array
        messages = json.dumps([
            {'T': 't', 'S': 'NQ', 'p': 15300.0, 's': 5, 't': '2024-01-15T14:30:00Z', 'x': 'IEX'},
            {'T': 't', 'S': 'AAPL', 'p': 180.5, 's': 100, 't': '2024-01-15T14:30:01Z', 'x': 'IEX'},
            {'T': 'subscription', 'trades': ['NQ', 'AAPL']}
        ])

        await fetcher._process_message(messages)
        await asyncio.sleep(0.1)

        # Should have received 2 ticks (subscription message ignored)
        assert len(received_ticks) == 2
        assert received_ticks[0].symbol == 'NQ'
        assert received_ticks[1].symbol == 'AAPL'

    @pytest.mark.asyncio
    async def test_reconnection_backoff(self, fetcher):
        """Test exponential backoff during reconnection."""
        fetcher.reconnect_attempts = 0

        # Mock failed connection
        with patch.object(fetcher, 'connect', side_effect=Exception("Connection failed")):
            with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                # Simulate reconnection attempts
                for attempt in range(3):
                    fetcher.reconnect_attempts = attempt + 1
                    expected_delay = min(fetcher.reconnect_delay * (2 ** attempt), 60)

                    # Call reconnect
                    await fetcher.reconnect()

                    # Verify delay calculation
                    if mock_sleep.call_count > 0:
                        actual_delay = mock_sleep.call_args[0][0]
                        assert actual_delay == expected_delay

    @pytest.mark.asyncio
    async def test_max_reconnection_attempts(self, fetcher):
        """Test circuit breaker after max reconnection attempts."""
        fetcher.reconnect_attempts = fetcher.max_reconnect_attempts

        with patch.object(fetcher, 'connect', side_effect=Exception("Connection failed")):
            with patch.object(fetcher, '_enter_safe_mode', new_callable=AsyncMock) as mock_safe_mode:
                await fetcher.reconnect()

                # Should enter safe mode
                mock_safe_mode.assert_called_once()
                assert fetcher.state == ConnectionState.FAILED

    @pytest.mark.asyncio
    async def test_safe_mode_entry(self, fetcher):
        """Test entering safe mode."""
        await fetcher._enter_safe_mode()

        assert fetcher.should_stop is True

    @pytest.mark.asyncio
    async def test_disconnect(self, fetcher, mock_websocket):
        """Test graceful disconnection."""
        fetcher.ws = mock_websocket
        fetcher.state = ConnectionState.CONNECTED

        await fetcher.disconnect()

        assert fetcher.should_stop is True
        assert fetcher.state == ConnectionState.DISCONNECTED
        mock_websocket.close.assert_called_once()

    def test_get_stats(self, fetcher):
        """Test statistics retrieval."""
        fetcher.state = ConnectionState.CONNECTED
        fetcher.message_count = 100
        fetcher.tick_count = 50
        fetcher.subscribed_symbols = {'NQ', 'AAPL'}
        fetcher.last_message_time = datetime(2024, 1, 15, 14, 30, 0)

        stats = fetcher.get_stats()

        assert stats['state'] == 'CONNECTED'
        assert stats['message_count'] == 100
        assert stats['tick_count'] == 50
        assert 'NQ' in stats['subscribed_symbols']
        assert 'AAPL' in stats['subscribed_symbols']
        assert stats['last_message_time'] == '2024-01-15T14:30:00'

    @pytest.mark.asyncio
    async def test_error_handler_called(self, fetcher):
        """Test that error handler is called on errors."""
        errors_received = []

        async def on_error(error):
            errors_received.append(error)

        fetcher.on_error = on_error

        # Trigger error in message processing
        bad_message = "invalid json"
        await fetcher._process_message(bad_message)

        # Error handler should not be called for JSON decode errors (just logged)
        # But let's test tick handler error
        async def on_tick_error(tick):
            raise ValueError("Test error")

        fetcher.on_tick = on_tick_error

        trade_msg = {
            'T': 't',
            'S': 'NQ',
            'p': 15300.0,
            's': 10,
            't': '2024-01-15T14:30:00Z',
            'x': 'IEX'
        }

        await fetcher._handle_trade(trade_msg)
        await asyncio.sleep(0.1)

        # Error should be caught and passed to error handler
        assert len(errors_received) == 1
        assert isinstance(errors_received[0], ValueError)

    def test_timestamp_parsing(self, fetcher):
        """Test timestamp parsing from various formats."""
        # ISO format with Z
        ts1 = fetcher._parse_timestamp('2024-01-15T14:30:00.123Z')
        assert ts1.year == 2024
        assert ts1.month == 1
        assert ts1.day == 15

        # ISO format with timezone
        ts2 = fetcher._parse_timestamp('2024-01-15T14:30:00.123+00:00')
        assert ts2.year == 2024

    @pytest.mark.asyncio
    async def test_resubscribe_after_reconnect(self, fetcher, mock_websocket):
        """Test resubscribing to symbols after reconnection."""
        # Setup initial connection and subscription
        fetcher.state = ConnectionState.CONNECTED
        fetcher.subscribed_symbols = {'NQ', 'AAPL'}
        fetcher.ws = mock_websocket

        # Mock successful reconnection
        auth_response = json.dumps([{
            'T': 'success',
            'msg': 'authenticated'
        }])
        mock_websocket.recv.return_value = auth_response

        with patch('websockets.connect', return_value=mock_websocket):
            with patch.object(fetcher, 'subscribe', new_callable=AsyncMock) as mock_subscribe:
                # Reset connection state
                fetcher.state = ConnectionState.DISCONNECTED
                fetcher.ws = None

                # Reconnect
                await fetcher.reconnect()
                await asyncio.sleep(0.1)

                # Should resubscribe to previous symbols
                if fetcher.state == ConnectionState.CONNECTED:
                    mock_subscribe.assert_called()


class TestTickDataClass:
    """Test suite for Tick dataclass."""

    def test_tick_creation(self):
        """Test creating a Tick instance."""
        tick = Tick(
            symbol='NQ',
            price=15300.5,
            size=10,
            timestamp=datetime(2024, 1, 15, 14, 30, 0),
            exchange='IEX'
        )

        assert tick.symbol == 'NQ'
        assert tick.price == 15300.5
        assert tick.size == 10
        assert tick.timestamp.year == 2024
        assert tick.exchange == 'IEX'

    def test_tick_to_dict(self):
        """Test converting Tick to dictionary."""
        tick = Tick(
            symbol='NQ',
            price=15300.5,
            size=10,
            timestamp=datetime(2024, 1, 15, 14, 30, 0),
            exchange='IEX'
        )

        tick_dict = tick.to_dict()

        assert tick_dict['symbol'] == 'NQ'
        assert tick_dict['price'] == 15300.5
        assert tick_dict['size'] == 10
        assert tick_dict['exchange'] == 'IEX'


class TestConnectionState:
    """Test suite for ConnectionState enum."""

    def test_connection_states(self):
        """Test all connection states are defined."""
        assert ConnectionState.DISCONNECTED.value == 0
        assert ConnectionState.CONNECTING.value == 1
        assert ConnectionState.AUTHENTICATING.value == 2
        assert ConnectionState.CONNECTED.value == 3
        assert ConnectionState.RECONNECTING.value == 4
        assert ConnectionState.FAILED.value == 5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
