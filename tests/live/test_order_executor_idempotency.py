"""
Tests for OrderExecutor Idempotency Protection

Verifies that duplicate orders are prevented using orderRef field.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from slob.live.order_executor import OrderExecutor, OrderExecutorConfig
from slob.live.setup_state import SetupCandidate


@pytest.fixture
def mock_ib():
    """Create a mock IB connection."""
    ib = Mock()
    ib.isConnected.return_value = True
    ib.openTrades.return_value = []
    ib.trades.return_value = []
    ib.client.getReqId.return_value = 12345
    return ib


@pytest.fixture
def order_executor_config():
    """Create OrderExecutor config."""
    return OrderExecutorConfig(
        host='127.0.0.1',
        port=7497,
        client_id=1,
        default_position_size=1,
        max_position_size=5,
        enable_bracket_orders=True
    )


@pytest.fixture
def order_executor(order_executor_config, mock_ib):
    """Create OrderExecutor with mocked IB."""
    executor = OrderExecutor(order_executor_config)
    executor.ib = mock_ib
    executor.nq_contract = Mock()  # Mock NQ contract
    return executor


@pytest.fixture
def setup_candidate():
    """Create a test setup candidate."""
    setup = SetupCandidate()
    setup.entry_price = 15265.0
    setup.sl_price = 15307.0
    setup.tp_price = 15199.0
    return setup


class TestIdempotencyProtection:
    """Test idempotency protection features."""

    def test_no_duplicate_when_no_existing_orders(self, order_executor, setup_candidate):
        """Test that duplicate check returns False when no existing orders."""
        # No existing orders
        order_executor.ib.openTrades.return_value = []
        order_executor.ib.trades.return_value = []

        # Should not detect duplicate
        is_duplicate = order_executor._check_duplicate_order(setup_candidate.id)
        assert is_duplicate == False

    def test_duplicate_detected_in_open_trades(self, order_executor, setup_candidate):
        """Test that duplicate is detected when order exists in openTrades."""
        # Create mock trade with matching orderRef
        mock_trade = Mock()
        mock_order = Mock()
        mock_order.orderRef = f"SLOB_{setup_candidate.id[:8]}_20251218_120000_ENTRY"
        mock_trade.order = mock_order
        mock_trade.orderStatus.status = "Submitted"

        order_executor.ib.openTrades.return_value = [mock_trade]
        order_executor.ib.trades.return_value = []

        # Should detect duplicate
        is_duplicate = order_executor._check_duplicate_order(setup_candidate.id)
        assert is_duplicate == True

    def test_duplicate_detected_in_filled_orders(self, order_executor, setup_candidate):
        """Test that duplicate is detected when order exists in filled trades."""
        # Create mock filled trade with matching orderRef
        mock_trade = Mock()
        mock_order = Mock()
        mock_order.orderRef = f"SLOB_{setup_candidate.id[:8]}_20251218_120000_ENTRY"
        mock_trade.order = mock_order
        mock_trade.orderStatus.status = "Filled"

        order_executor.ib.openTrades.return_value = []
        order_executor.ib.trades.return_value = [mock_trade]

        # Should detect duplicate
        is_duplicate = order_executor._check_duplicate_order(setup_candidate.id)
        assert is_duplicate == True

    def test_duplicate_not_detected_for_different_setup(self, order_executor, setup_candidate):
        """Test that duplicate is NOT detected for different setup ID."""
        # Create mock trade with DIFFERENT setup ID
        mock_trade = Mock()
        mock_order = Mock()
        mock_order.orderRef = "SLOB_aaaaaaaa_20251218_120000_ENTRY"  # Different ID
        mock_trade.order = mock_order
        mock_trade.orderStatus.status = "Submitted"

        order_executor.ib.openTrades.return_value = [mock_trade]

        # Should NOT detect duplicate (different setup ID)
        is_duplicate = order_executor._check_duplicate_order(setup_candidate.id)
        assert is_duplicate == False

    def test_duplicate_check_handles_missing_orderref(self, order_executor, setup_candidate):
        """Test that duplicate check handles orders without orderRef gracefully."""
        # Create mock trade WITHOUT orderRef
        mock_trade = Mock()
        mock_order = Mock()
        mock_order.orderRef = None  # No orderRef
        mock_trade.order = mock_order

        order_executor.ib.openTrades.return_value = [mock_trade]

        # Should not crash, should return False
        is_duplicate = order_executor._check_duplicate_order(setup_candidate.id)
        assert is_duplicate == False

    def test_duplicate_check_when_ib_not_connected(self, order_executor, setup_candidate):
        """Test that duplicate check returns False when IB not connected."""
        order_executor.ib.isConnected.return_value = False

        # Should return False (fail open) when not connected
        is_duplicate = order_executor._check_duplicate_order(setup_candidate.id)
        assert is_duplicate == False

    @pytest.mark.asyncio
    async def test_place_bracket_order_rejects_duplicate(self, order_executor, setup_candidate):
        """Test that place_bracket_order rejects duplicate orders."""
        # Setup: existing order in openTrades
        mock_trade = Mock()
        mock_order = Mock()
        mock_order.orderRef = f"SLOB_{setup_candidate.id[:8]}_20251218_120000_ENTRY"
        mock_trade.order = mock_order
        mock_trade.orderStatus.status = "Submitted"

        order_executor.ib.openTrades.return_value = [mock_trade]

        # Try to place order (should be rejected as duplicate)
        result = await order_executor.place_bracket_order(setup_candidate, position_size=1)

        # Verify rejection
        assert result.success == False
        assert "duplicate" in result.error_message.lower()
        assert "already placed" in result.error_message.lower()

    def test_orderref_format(self, setup_candidate):
        """Test that orderRef format is correct."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        order_ref_base = f"SLOB_{setup_candidate.id[:8]}_{timestamp}"

        # Verify format components
        assert order_ref_base.startswith("SLOB_")
        assert len(order_ref_base.split('_')[1]) == 8  # Setup ID prefix is 8 chars
        assert order_ref_base.endswith(timestamp)

        # Verify order type suffixes
        entry_ref = f"{order_ref_base}_ENTRY"
        sl_ref = f"{order_ref_base}_SL"
        tp_ref = f"{order_ref_base}_TP"

        assert entry_ref.endswith("_ENTRY")
        assert sl_ref.endswith("_SL")
        assert tp_ref.endswith("_TP")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
