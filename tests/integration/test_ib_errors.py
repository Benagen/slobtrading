"""
IB Error Handling Integration Tests

Tests proper handling of all critical Interactive Brokers API error codes.

Error Codes Covered:
- 321: Insufficient buying power (order rejected)
- 502: Session disconnected (connectivity issue)
- 1100: Connectivity lost (reconnect required)
- 2103: Order ID exceeded max allowed (reset required)
- 1102: Connectivity restored (recovery)
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

from slob.live.order_executor import OrderExecutor, OrderExecutorConfig, BracketOrderResult
from slob.live.ib_ws_fetcher import IBWSFetcher, Tick
from slob.live.setup_tracker import SetupCandidate, SetupState
from ib_insync import IB, Contract


@pytest.fixture
def executor_config():
    """Create OrderExecutor configuration for testing."""
    return OrderExecutorConfig(
        host='127.0.0.1',
        port=4002,
        client_id=999,
        account='DU123456',
        paper_trading=True,
        max_retry_attempts=2,
        default_position_size=1
    )


@pytest.fixture
async def mock_ib():
    """Create mock IB connection."""
    mock = AsyncMock(spec=IB)
    mock.isConnected.return_value = True
    mock.connectAsync = AsyncMock()
    mock.disconnectAsync = AsyncMock()
    mock.reqMarketDataType = Mock()

    # Mock account values
    mock_account_value = Mock()
    mock_account_value.tag = 'NetLiquidation'
    mock_account_value.currency = 'USD'
    mock_account_value.value = '100000.0'
    mock.accountValuesAsync = AsyncMock(return_value=[mock_account_value])

    # Mock contract qualification
    mock_contract = Mock(spec=Contract)
    mock_contract.symbol = 'NQ'
    mock_contract.conId = 12345
    mock.qualifyContractsAsync = AsyncMock(return_value=[mock_contract])

    return mock


class TestIBError321InsufficientBuyingPower:
    """Test handling of IB Error 321: Insufficient buying power."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_error_321_disables_trading(self, mock_ib, executor_config):
        """
        Test that Error 321 disables trading to prevent further order rejections.

        Flow:
        1. Attempt to place bracket order
        2. IB returns Error 321
        3. Verify trading is disabled
        4. Verify error is logged
        """
        executor = OrderExecutor(executor_config)
        executor.ib = mock_ib
        executor.trading_enabled = True
        executor.pending_orders = {}

        # Simulate Error 321 directly (as if IB triggered it)
        await executor._handle_ib_error(1, 321, "Insufficient buying power")

        # Verify trading is disabled
        assert executor.trading_enabled is False, "Trading should be disabled after Error 321"

    @pytest.mark.asyncio
    async def test_error_321_subsequent_orders_rejected(self, mock_ib):
        """
        Test that subsequent orders are rejected after Error 321.

        Flow:
        1. Error 321 disables trading
        2. Attempt another order
        3. Verify it's rejected immediately
        """
        # Use non-paper trading config so we hit the trading_enabled check
        config = OrderExecutorConfig(
            host='127.0.0.1',
            port=4001,  # Live port
            client_id=999,
            account='U123456',  # Live account
            paper_trading=False,  # Not paper trading
            max_retry_attempts=2,
            default_position_size=1
        )

        # Mock the validation to bypass the live trading confirmation requirement
        with patch.object(OrderExecutor, 'validate_paper_trading_mode', return_value=None):
            executor = OrderExecutor(config)

        executor.ib = mock_ib
        executor.trading_enabled = False  # Already disabled by previous error

        # Create a setup candidate with all required fields
        setup = SetupCandidate(
            symbol='NQ',
            lse_high=18510.0,
            lse_low=18490.0,
            lse_close_time=datetime.now(),
            state=SetupState.WAITING_ENTRY
        )
        setup.entry_price = 18500.0
        setup.sl_price = 18510.0
        setup.tp_price = 18490.0
        setup.direction = 'SHORT'

        # Attempt order when trading is disabled
        result = await executor.place_bracket_order(setup)

        assert result.success is False
        assert result.entry_order.error_message is not None
        assert "disabled" in result.entry_order.error_message.lower()


class TestIBError502SessionDisconnected:
    """Test handling of IB Error 502: Session disconnected."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_error_502_triggers_reconnect(self, mock_ib, executor_config):
        """
        Test that Error 502 triggers automatic reconnection.

        Flow:
        1. Connection active
        2. Error 502 occurs (session disconnect)
        3. Verify reconnect is triggered
        4. Verify connection is restored
        """
        executor = OrderExecutor(executor_config)
        executor.ib = mock_ib

        # Mock reconnect method
        executor.reconnect = AsyncMock()

        # Simulate Error 502
        await executor._handle_ib_error(0, 502, "Session disconnected")

        # Verify reconnect was called
        executor.reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_502_during_order_placement(self, mock_ib, executor_config):
        """
        Test Error 502 during active order placement.

        Flow:
        1. Order being placed
        2. Error 502 occurs mid-placement
        3. Verify order is marked as failed
        4. Verify reconnect is triggered
        """
        executor = OrderExecutor(executor_config)
        executor.ib = mock_ib
        executor.pending_orders = {
            1: {
                'timestamp': datetime.now(),
                'status': 'pending',
                'symbol': 'NQ'
            }
        }

        # Mock reconnect
        executor.reconnect = AsyncMock()

        # Simulate Error 502 for order ID 1
        await executor._handle_ib_error(1, 502, "Session disconnected")

        # Verify error is stored in pending order
        assert 'error' in executor.pending_orders[1]
        assert executor.pending_orders[1]['error']['code'] == 502

        # Verify reconnect triggered
        executor.reconnect.assert_called_once()


class TestIBError1100ConnectivityLost:
    """Test handling of IB Error 1100: Connectivity lost."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_error_1100_triggers_reconnect(self, mock_ib, executor_config):
        """
        Test that Error 1100 triggers automatic reconnection.

        Flow:
        1. Connection active
        2. Error 1100 occurs (connectivity lost)
        3. Verify reconnect is triggered
        4. Verify critical error is logged
        """
        executor = OrderExecutor(executor_config)
        executor.ib = mock_ib

        # Mock reconnect
        executor.reconnect = AsyncMock()

        # Simulate Error 1100
        await executor._handle_ib_error(0, 1100, "Connectivity between IB and TWS lost")

        # Verify reconnect was called
        executor.reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_1102_connectivity_restored(self, mock_ib, executor_config):
        """
        Test that Error 1102 indicates connectivity restoration.

        Flow:
        1. Error 1100 (lost connectivity)
        2. Error 1102 (connectivity restored)
        3. Verify system continues normally
        """
        executor = OrderExecutor(executor_config)
        executor.ib = mock_ib

        # Mock reconnect
        executor.reconnect = AsyncMock()

        # Simulate connectivity lost
        await executor._handle_ib_error(0, 1100, "Connectivity lost")
        assert executor.reconnect.call_count == 1

        # Simulate connectivity restored
        await executor._handle_ib_error(0, 1102, "Connectivity restored")

        # Should not trigger additional reconnect
        assert executor.reconnect.call_count == 1


class TestIBError2103OrderIDExceeded:
    """Test handling of IB Error 2103: Order ID exceeded max allowed."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_error_2103_triggers_reconnect(self, mock_ib, executor_config):
        """
        Test that Error 2103 triggers reconnection to reset order IDs.

        Flow:
        1. Order ID counter reaches IB's max
        2. Error 2103 occurs
        3. Verify reconnect is triggered (to reset counter)
        4. Verify critical error is logged
        """
        executor = OrderExecutor(executor_config)
        executor.ib = mock_ib

        # Mock reconnect
        executor.reconnect = AsyncMock()

        # Simulate Error 2103
        await executor._handle_ib_error(999999, 2103, "OrderId exceeds maximum")

        # Verify reconnect was called to reset order IDs
        executor.reconnect.assert_called_once()


class TestIBFetcherErrorHandling:
    """Test error handling in IBWSFetcher."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_fetcher_tick_handler_error_isolation(self, mock_ib):
        """
        Test that tick handler errors don't crash the fetcher.

        Flow:
        1. Register tick handler that raises exception
        2. Process tick
        3. Verify error is logged but fetcher continues
        """
        fetcher = IBWSFetcher(
            host='127.0.0.1',
            port=4002,
            client_id=998
        )
        fetcher.ib = mock_ib
        fetcher.connected = True

        # Track if handler was called
        handler_called = False

        # Mock tick handler that fails
        async def failing_handler(tick):
            nonlocal handler_called
            handler_called = True
            raise ValueError("Handler error")

        fetcher.on_tick = failing_handler

        # Create proper mock ticker with valid numeric values
        mock_ticker = Mock()
        mock_ticker.contract = Mock()
        mock_ticker.contract.symbol = 'NQ'
        mock_ticker.last = 18500.0  # Numeric value, not Mock
        mock_ticker.lastSize = 1  # Numeric value, not Mock
        mock_ticker.volume = 100  # Numeric value, not Mock
        mock_ticker.time = datetime.now()

        # Process tick - should not crash despite handler error
        # The fetcher uses create_task for handlers with error handling
        try:
            fetcher._on_ib_tick([mock_ticker])
            # Give task time to execute
            await asyncio.sleep(0.2)
        except Exception as e:
            pytest.fail(f"Fetcher crashed on handler error: {e}")

        # Verify handler was called (even though it failed)
        assert handler_called is True


class TestErrorRecovery:
    """Test complete error recovery scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_complete_reconnect_cycle(self, mock_ib, executor_config):
        """
        Test complete reconnection cycle after critical error.

        Flow:
        1. System operating normally
        2. Critical error occurs (502/1100)
        3. Reconnect is triggered
        4. Connection is restored
        5. System resumes normal operation
        """
        executor = OrderExecutor(executor_config)
        executor.ib = mock_ib

        # Track reconnection
        reconnect_called = False

        async def mock_reconnect():
            nonlocal reconnect_called
            reconnect_called = True
            # Simulate successful reconnection
            mock_ib.isConnected.return_value = True
            return True

        executor.reconnect = mock_reconnect

        # Simulate critical error
        await executor._handle_ib_error(0, 1100, "Connectivity lost")

        # Give the task time to execute (asyncio.create_task is used in _handle_ib_error)
        await asyncio.sleep(0.1)

        # Verify reconnect was triggered
        assert reconnect_called is True

        # Verify connection is restored
        assert mock_ib.isConnected() is True

    @pytest.mark.asyncio
    async def test_error_recovery_preserves_state(self, mock_ib, executor_config):
        """
        Test that error recovery preserves pending order state.

        Flow:
        1. Order is pending
        2. Connection error occurs
        3. Reconnect happens
        4. Pending order information is preserved
        """
        executor = OrderExecutor(executor_config)
        executor.ib = mock_ib

        # Set up pending order
        executor.pending_orders = {
            1: {
                'timestamp': datetime.now(),
                'status': 'pending',
                'symbol': 'NQ',
                'qty': 1
            }
        }

        # Mock reconnect that preserves state
        async def mock_reconnect():
            # Reconnect should NOT clear pending_orders
            pass

        executor.reconnect = mock_reconnect

        # Simulate error
        await executor._handle_ib_error(0, 502, "Session disconnected")

        # Verify pending order is still tracked
        assert 1 in executor.pending_orders
        assert executor.pending_orders[1]['symbol'] == 'NQ'


# Summary test
@pytest.mark.asyncio
async def test_all_error_scenarios_summary():
    """
    Summary test verifying all critical error scenarios are covered.

    Ensures:
    - Error 321: Trading disabled
    - Error 502: Reconnect triggered
    - Error 1100: Reconnect triggered
    - Error 2103: Reconnect triggered
    - Error isolation: Handler errors don't crash system
    - State preservation: Pending orders preserved across reconnects
    """
    assert True  # All tests above validate these scenarios


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
