"""
Unit Tests for IB WebSocket Fetcher

Tests the Interactive Brokers WebSocket fetcher implementation.
"""

import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# Skip all tests if ib_insync not installed
pytest.importorskip("ib_insync")

from slob.live.ib_ws_fetcher import IBWSFetcher, ConnectionState
from slob.data.tick import Tick


class TestIBWSFetcherInitialization:
    """Test IB fetcher initialization."""

    def test_default_initialization(self):
        """Test fetcher with default configuration."""
        fetcher = IBWSFetcher()

        assert fetcher.config.host == '127.0.0.1'
        assert fetcher.config.port == 7497
        assert fetcher.config.client_id == 1
        assert fetcher.config.paper_trading is True
        assert fetcher.state == ConnectionState.DISCONNECTED

    def test_custom_initialization(self):
        """Test fetcher with custom configuration."""
        fetcher = IBWSFetcher(
            host='192.168.1.100',
            port=4002,
            client_id=5,
            account='DU123456',
            paper_trading=True
        )

        assert fetcher.config.host == '192.168.1.100'
        assert fetcher.config.port == 4002
        assert fetcher.config.client_id == 5
        assert fetcher.config.account == 'DU123456'
        assert fetcher.config.paper_trading is True


class TestIBConnection:
    """Test IB connection logic."""

    @pytest.mark.asyncio
    async def test_connection_flow(self):
        """Test connection establishes successfully."""
        fetcher = IBWSFetcher()

        # Mock IB instance
        with patch('slob.live.ib_ws_fetcher.IB') as mock_ib:
            mock_instance = AsyncMock()
            mock_ib.return_value = mock_instance
            mock_instance.connectAsync = AsyncMock()
            mock_instance.isConnected = MagicMock(return_value=True)

            # Connect
            await fetcher.connect()

            # Verify
            assert fetcher.state == ConnectionState.CONNECTED
            assert fetcher.reconnect_attempts == 0
            mock_instance.connectAsync.assert_called_once()

    @pytest.mark.asyncio
    async def test_connection_failure(self):
        """Test connection failure handling."""
        fetcher = IBWSFetcher()

        # Mock IB instance to raise error
        with patch('slob.live.ib_ws_fetcher.IB') as mock_ib:
            mock_instance = AsyncMock()
            mock_ib.return_value = mock_instance
            mock_instance.connectAsync = AsyncMock(
                side_effect=Exception("Connection refused")
            )

            # Should raise ConnectionError
            with pytest.raises(ConnectionError):
                await fetcher.connect()

            assert fetcher.state == ConnectionState.FAILED

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnect cleans up properly."""
        fetcher = IBWSFetcher()

        # Mock IB instance
        with patch('slob.live.ib_ws_fetcher.IB') as mock_ib:
            mock_instance = AsyncMock()
            mock_ib.return_value = mock_instance
            mock_instance.connectAsync = AsyncMock()
            mock_instance.isConnected = MagicMock(return_value=True)
            mock_instance.disconnect = MagicMock()

            # Connect then disconnect
            await fetcher.connect()
            await fetcher.disconnect()

            # Verify
            assert fetcher.state == ConnectionState.DISCONNECTED
            assert len(fetcher.subscribed_contracts) == 0
            mock_instance.disconnect.assert_called_once()


class TestIBSubscriptions:
    """Test IB market data subscriptions."""

    @pytest.mark.asyncio
    async def test_subscribe_to_nq(self):
        """Test subscribing to NQ futures."""
        fetcher = IBWSFetcher()

        # Mock IB and contract resolution
        with patch('slob.live.ib_ws_fetcher.IB') as mock_ib:
            mock_instance = AsyncMock()
            mock_ib.return_value = mock_instance
            mock_instance.connectAsync = AsyncMock()
            mock_instance.isConnected = MagicMock(return_value=True)

            # Mock contract resolution
            from ib_insync import Future
            mock_contract = Future('NQ', lastTradeDateOrContractMonth='202412', exchange='CME')
            mock_contract.conId = 123456

            mock_instance.reqContractDetailsAsync = AsyncMock(
                return_value=[MagicMock(contract=mock_contract)]
            )

            # Mock ticker
            mock_ticker = MagicMock()
            mock_ticker.updateEvent = MagicMock()
            mock_instance.reqMktData = MagicMock(return_value=mock_ticker)

            # Connect and subscribe
            await fetcher.connect()
            fetcher.state = ConnectionState.CONNECTED
            await fetcher.subscribe(['NQ'])

            # Verify
            assert 'NQ' in fetcher.subscribed_contracts
            assert 123456 in fetcher.contract_to_symbol
            assert fetcher.contract_to_symbol[123456] == 'NQ'
            mock_instance.reqMktData.assert_called_once()


class TestIBTickHandling:
    """Test tick handling and conversion."""

    def test_ticker_update_creates_tick(self):
        """Test that ticker updates are converted to Ticks."""
        fetcher = IBWSFetcher()

        # Setup
        ticks_received = []

        def tick_handler(tick: Tick):
            ticks_received.append(tick)

        fetcher.on_tick = tick_handler

        # Mock ticker
        from ib_insync import Future
        mock_contract = Future('NQ', exchange='CME')
        mock_contract.conId = 123456
        fetcher.contract_to_symbol[123456] = 'NQ'

        mock_ticker = MagicMock()
        mock_ticker.contract = mock_contract
        mock_ticker.time = datetime(2024, 1, 15, 14, 30, 0)
        mock_ticker.last = 15300.25
        mock_ticker.lastSize = 5

        # Trigger update
        fetcher._on_ticker_update(mock_ticker)

        # Verify (async handler, need to wait)
        import time
        time.sleep(0.1)  # Give async task time to run

        # Stats should be updated immediately
        assert fetcher.tick_count == 1
        assert fetcher.message_count == 1


class TestIBStatistics:
    """Test statistics tracking."""

    def test_get_stats(self):
        """Test statistics reporting."""
        fetcher = IBWSFetcher()
        fetcher.state = ConnectionState.CONNECTED
        fetcher.tick_count = 100
        fetcher.message_count = 105
        fetcher.subscribed_contracts = {'NQ': MagicMock()}
        fetcher.last_message_time = datetime(2024, 1, 15, 14, 30, 0)

        stats = fetcher.get_stats()

        assert stats['state'] == 'CONNECTED'
        assert stats['tick_count'] == 100
        assert stats['message_count'] == 105
        assert stats['subscribed_symbols'] == ['NQ']
        assert stats['last_message_time'] is not None


class TestIBReconnection:
    """Test reconnection logic."""

    @pytest.mark.asyncio
    async def test_reconnect_attempts(self):
        """Test reconnection with exponential backoff."""
        fetcher = IBWSFetcher()
        fetcher.max_reconnect_attempts = 3

        # Mock IB
        with patch('slob.live.ib_ws_fetcher.IB') as mock_ib:
            mock_instance = AsyncMock()
            mock_ib.return_value = mock_instance
            mock_instance.connectAsync = AsyncMock()
            mock_instance.isConnected = MagicMock(return_value=True)
            mock_instance.disconnect = MagicMock()

            # First connection succeeds
            await fetcher.connect()
            assert fetcher.reconnect_attempts == 0

            # Simulate disconnect
            await fetcher.disconnect()

            # Reconnect
            await fetcher.reconnect()

            # Should have attempted once
            assert fetcher.reconnect_attempts == 1


# Integration test (requires real IB connection, marked as manual)
@pytest.mark.manual
@pytest.mark.asyncio
async def test_real_ib_connection():
    """
    Integration test with real IB connection.

    Requirements:
    - TWS or IB Gateway running on localhost:7497
    - Paper trading account
    - API enabled

    Run manually with: pytest -m manual tests/live/test_ib_ws_fetcher.py::test_real_ib_connection
    """
    fetcher = IBWSFetcher(
        host='127.0.0.1',
        port=7497,
        client_id=999,  # Use high client_id for tests
        paper_trading=True
    )

    try:
        # Connect
        await fetcher.connect()
        assert fetcher.is_connected()

        # Subscribe to NQ
        ticks_received = []

        async def tick_handler(tick: Tick):
            ticks_received.append(tick)
            print(f"Tick: {tick.symbol} @ {tick.price}")

        fetcher.on_tick = tick_handler
        await fetcher.subscribe(['NQ'])

        # Listen for 10 seconds
        listen_task = asyncio.create_task(fetcher.listen())

        await asyncio.sleep(10)
        fetcher.is_running = False

        # Should have received some ticks
        print(f"Received {len(ticks_received)} ticks")
        assert len(ticks_received) > 0

    finally:
        await fetcher.disconnect()
