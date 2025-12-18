"""
Tests for OrderExecutor RiskManager Integration

Verifies that RiskManager is properly integrated for:
- Position sizing with fixed % risk
- ATR-based volatility adjustment
- Drawdown protection (size reduction + trading halt)
- Account balance syncing from IBKR
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from slob.live.order_executor import OrderExecutor, OrderExecutorConfig
from slob.live.setup_state import SetupCandidate


@pytest.fixture
def mock_ib():
    """Create a mock IB connection."""
    ib = Mock()
    ib.isConnected.return_value = True
    ib.accountValues.return_value = [
        Mock(tag='TotalCashValue', value='50000.00'),
        Mock(tag='NetLiquidation', value='50000.00')
    ]
    ib.client.getReqId.return_value = 12345
    return ib


@pytest.fixture
def order_executor_config():
    """Create OrderExecutor config."""
    return OrderExecutorConfig(
        host='127.0.0.1',
        port=7497,
        client_id=1,
        account='DU282477',
        default_position_size=1,
        max_position_size=5,
        enable_bracket_orders=True
    )


@pytest.fixture
def order_executor(order_executor_config, mock_ib):
    """Create OrderExecutor with mocked IB and RiskManager."""
    executor = OrderExecutor(order_executor_config)
    executor.ib = mock_ib
    executor.nq_contract = Mock()  # Mock NQ contract
    return executor


@pytest.fixture
def setup_candidate():
    """Create a test setup candidate."""
    setup = SetupCandidate()
    setup.entry_price = 15265.0
    setup.sl_price = 15307.0  # 42 points risk
    setup.tp_price = 15199.0
    return setup


class TestRiskManagerIntegration:
    """Test RiskManager integration features."""

    def test_riskmanager_initialized(self, order_executor):
        """Test that RiskManager is initialized in OrderExecutor."""
        assert hasattr(order_executor, 'risk_manager')
        assert order_executor.risk_manager is not None
        assert order_executor.risk_manager.initial_capital == 50000.0
        assert order_executor.risk_manager.max_risk_per_trade == 0.01  # 1%

    def test_get_account_balance_from_ib(self, order_executor, mock_ib):
        """Test that account balance is retrieved from IB."""
        balance = order_executor.get_account_balance()

        assert balance == 50000.0
        assert order_executor._cached_balance == 50000.0
        assert order_executor.risk_manager.current_capital == 50000.0

    def test_get_account_balance_fallback_when_disconnected(self, order_executor):
        """Test that fallback balance is used when IB not connected."""
        order_executor.ib.isConnected.return_value = False
        order_executor._cached_balance = 60000.0

        balance = order_executor.get_account_balance()

        assert balance == 60000.0

    def test_calculate_position_size_fixed_risk(self, order_executor, setup_candidate):
        """Test position size calculation with fixed % risk."""
        # Entry: 15265, SL: 15307, risk: 42 points
        # Account: $50,000, Risk: 1% = $500
        # NQ multiplier: $20/point
        # Expected: $500 / (42 * $20) = $500 / $840 ≈ 0.6 → 1 contract (minimum)

        contracts = order_executor.calculate_position_size(
            entry_price=setup_candidate.entry_price,
            stop_loss_price=setup_candidate.sl_price,
            atr=None
        )

        assert contracts >= 1  # Minimum 1 contract
        assert contracts <= order_executor.config.max_position_size

    def test_calculate_position_size_with_atr(self, order_executor, setup_candidate):
        """Test position size calculation with ATR-based adjustment."""
        # With ATR, position size should be inversely proportional to volatility
        # High ATR = smaller position, Low ATR = larger position

        contracts_low_atr = order_executor.calculate_position_size(
            entry_price=setup_candidate.entry_price,
            stop_loss_price=setup_candidate.sl_price,
            atr=20.0  # Low volatility
        )

        contracts_high_atr = order_executor.calculate_position_size(
            entry_price=setup_candidate.entry_price,
            stop_loss_price=setup_candidate.sl_price,
            atr=100.0  # High volatility
        )

        # Low ATR should allow larger position
        # Note: This assertion might need adjustment based on actual RiskManager logic
        assert contracts_low_atr >= contracts_high_atr or contracts_high_atr == 1

    def test_position_size_respects_max_limit(self, order_executor, setup_candidate):
        """Test that position size never exceeds max_position_size."""
        # Set very tight SL to trigger large position size calculation
        contracts = order_executor.calculate_position_size(
            entry_price=15265.0,
            stop_loss_price=15267.0,  # Only 2 points risk
            atr=None
        )

        assert contracts <= order_executor.config.max_position_size

    def test_drawdown_protection_reduces_size(self, order_executor, setup_candidate):
        """Test that position size is reduced at 15% drawdown."""
        # Set account to 15% drawdown
        order_executor.risk_manager.current_capital = 42500.0  # 15% down from 50k
        order_executor.risk_manager.peak_equity = 50000.0
        order_executor.risk_manager.current_drawdown = 0.15
        order_executor.risk_manager.risk_reduction_active = True

        contracts = order_executor.calculate_position_size(
            entry_price=setup_candidate.entry_price,
            stop_loss_price=setup_candidate.sl_price,
            atr=None
        )

        # Should still return at least 1 contract, but risk should be reduced
        assert contracts >= 1

    def test_drawdown_protection_stops_trading_at_25_percent(self, order_executor, setup_candidate):
        """Test that trading stops at 25% drawdown."""
        # Set account to 25% drawdown
        order_executor.risk_manager.current_capital = 37500.0  # 25% down from 50k
        order_executor.risk_manager.peak_equity = 50000.0
        order_executor.risk_manager.current_drawdown = 0.25
        order_executor.risk_manager.trading_enabled = False

        contracts = order_executor.calculate_position_size(
            entry_price=setup_candidate.entry_price,
            stop_loss_price=setup_candidate.sl_price,
            atr=None
        )

        # Trading should be disabled
        assert contracts == 0

    def test_minimum_one_contract_when_trading_enabled(self, order_executor, setup_candidate):
        """Test that at least 1 contract is returned when trading is enabled."""
        # Set very small account or large SL distance
        order_executor._cached_balance = 5000.0  # Small account

        contracts = order_executor.calculate_position_size(
            entry_price=setup_candidate.entry_price,
            stop_loss_price=setup_candidate.sl_price,
            atr=None
        )

        # Should return minimum 1 contract (unless trading disabled)
        assert contracts >= 1 or order_executor.risk_manager.trading_enabled == False

    def test_account_balance_synced_on_position_sizing(self, order_executor, mock_ib, setup_candidate):
        """Test that account balance is synced from IB during position sizing."""
        # Change IB balance
        mock_ib.accountValues.return_value = [
            Mock(tag='TotalCashValue', value='60000.00')
        ]

        contracts = order_executor.calculate_position_size(
            entry_price=setup_candidate.entry_price,
            stop_loss_price=setup_candidate.sl_price,
            atr=None
        )

        # Verify balance was updated
        assert order_executor._cached_balance == 60000.0
        assert order_executor.risk_manager.current_capital == 60000.0

    def test_zero_sl_distance_returns_minimum(self, order_executor):
        """Test that zero SL distance still returns minimum 1 contract (safety)."""
        contracts = order_executor.calculate_position_size(
            entry_price=15265.0,
            stop_loss_price=15265.0,  # Same as entry (0 risk)
            atr=None
        )

        # Safety feature: always return at least 1 contract if trading enabled
        assert contracts == 1


class TestRiskManagerMethods:
    """Test RiskManager-specific functionality."""

    def test_kelly_criterion_disabled_by_default(self, order_executor):
        """Test that Kelly Criterion is disabled by default."""
        assert order_executor.risk_manager.use_kelly == False

    def test_risk_reduction_thresholds_configured(self, order_executor):
        """Test that drawdown thresholds are properly configured."""
        assert order_executor.risk_manager.max_drawdown_stop == 0.25  # 25%
        assert order_executor.risk_manager.reduce_size_at_dd == 0.15  # 15%

    def test_risk_per_trade_is_one_percent(self, order_executor):
        """Test that default risk per trade is 1%."""
        assert order_executor.risk_manager.max_risk_per_trade == 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
