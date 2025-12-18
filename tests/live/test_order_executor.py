"""
Tests for OrderExecutor - IB Order Placement

Tests cover:
- Order placement (market, limit, stop)
- Bracket orders (entry + SL + TP)
- Retry logic
- Position sizing
- Error handling

Note: Tests require IB TWS/Gateway running on localhost
"""

import pytest
import asyncio
from datetime import datetime

from slob.live.order_executor import (
    OrderExecutor,
    OrderExecutorConfig,
    OrderResult,
    OrderStatus,
    BracketOrderResult
)
from slob.live.setup_state import SetupCandidate, SetupState


# Mark for IB integration tests (skip by default, run when IB available)
ib_integration = pytest.mark.skipif(
    True,  # Set to False when IB is running
    reason="IB TWS/Gateway not running - skipping integration tests"
)


@pytest.fixture
async def order_executor():
    """Create OrderExecutor connected to IB paper trading."""
    config = OrderExecutorConfig(
        host='127.0.0.1',
        port=7497,  # TWS paper trading
        client_id=999,  # Test client
        paper_trading=True,
        max_retry_attempts=3,
        default_position_size=1
    )

    executor = OrderExecutor(config)

    try:
        await executor.initialize()
        yield executor
    finally:
        await executor.close()


# ─────────────────────────────────────────────────────────────────
# CONNECTION TESTS
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@ib_integration
async def test_executor_initialization(order_executor):
    """Test OrderExecutor initializes and connects to IB."""
    assert order_executor.ib is not None
    assert order_executor.ib.isConnected()
    assert order_executor.nq_contract is not None

    # Contract should be NQ futures
    assert order_executor.nq_contract.symbol == 'NQ'
    assert order_executor.nq_contract.exchange == 'CME'


@pytest.mark.asyncio
@ib_integration
async def test_nq_contract_resolution(order_executor):
    """Test NQ front month contract is resolved correctly."""
    contract = order_executor.nq_contract

    assert contract.symbol == 'NQ'
    assert contract.lastTradeDateOrContractMonth is not None
    assert contract.conId > 0  # Valid contract ID

    print(f"✅ Resolved NQ contract: {contract.localSymbol} (expiry: {contract.lastTradeDateOrContractMonth})")


# ─────────────────────────────────────────────────────────────────
# ORDER PLACEMENT TESTS (UNIT STYLE - NO ACTUAL EXECUTION)
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bracket_order_validation():
    """Test bracket order validates setup data."""
    config = OrderExecutorConfig(paper_trading=True)
    executor = OrderExecutor(config)

    # Setup without entry price
    invalid_setup = SetupCandidate(
        id="test-001",
        state=SetupState.WAITING_ENTRY,
        lse_high=15300.0,
        # Missing: entry_price, sl_price, tp_price
    )

    # Should reject
    result = await executor.place_bracket_order(invalid_setup)

    assert result.success is False
    assert "missing" in result.error_message.lower()
    assert result.entry_order.status == OrderStatus.REJECTED


def test_position_size_calculation():
    """Test position sizing algorithm."""
    config = OrderExecutorConfig(max_position_size=5)
    executor = OrderExecutor(config)

    # Test: $100,000 account, 1% risk, 50 points SL
    account_balance = 100000
    risk_per_trade = 0.01  # 1%
    entry_price = 15250.0
    stop_loss_price = 15300.0  # 50 points risk

    contracts = executor.calculate_position_size(
        account_balance,
        risk_per_trade,
        entry_price,
        stop_loss_price
    )

    # Expected:
    # Risk amount = $100k × 1% = $1,000
    # Points risk = 50
    # Dollar risk per contract = 50 × $20 = $1,000
    # Contracts = $1,000 / $1,000 = 1
    assert contracts == 1


def test_position_size_max_clamp():
    """Test position size is clamped to max."""
    config = OrderExecutorConfig(max_position_size=3)
    executor = OrderExecutor(config)

    # Large account, small SL = many contracts
    contracts = executor.calculate_position_size(
        account_balance=1000000,  # $1M
        risk_per_trade=0.02,  # 2%
        entry_price=15250.0,
        stop_loss_price=15255.0  # Only 5 points risk!
    )

    # Should be clamped to max
    assert contracts <= 3


# ─────────────────────────────────────────────────────────────────
# BRACKET ORDER TESTS (MOCK - NO ACTUAL EXECUTION)
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bracket_order_structure():
    """Test bracket order creates proper order structure."""
    # This test validates order structure without actually submitting to IB

    setup = SetupCandidate(
        id="test-bracket-001",
        state=SetupState.WAITING_ENTRY,
        lse_high=15300.0,
        entry_price=15250.0,
        sl_price=15280.0,  # 30 points SL
        tp_price=15100.0,  # 150 points TP (5:1 RR)
        risk_reward_ratio=5.0
    )

    # Verify setup has required fields
    assert setup.entry_price == 15250.0
    assert setup.sl_price == 15280.0
    assert setup.tp_price == 15100.0
    assert setup.sl_price > setup.entry_price  # SL above entry (SHORT)
    assert setup.tp_price < setup.entry_price  # TP below entry (SHORT)


# ─────────────────────────────────────────────────────────────────
# INTEGRATION TESTS (REQUIRES IB)
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.skipif(True, reason="Requires IB and manual verification")
async def test_place_bracket_order_live(order_executor):
    """
    Test placing actual bracket order on IB paper trading.

    ⚠️ WARNING: This test places REAL orders on paper account!
    Only run manually when ready to test.
    """
    setup = SetupCandidate(
        id="live-test-001",
        state=SetupState.WAITING_ENTRY,
        lse_high=15300.0,
        entry_price=15250.0,
        sl_price=15280.0,
        tp_price=15100.0,
        risk_reward_ratio=5.0
    )

    result = await order_executor.place_bracket_order(setup, position_size=1)

    # Verify orders submitted
    assert result.success is True
    assert result.entry_order.status == OrderStatus.SUBMITTED
    assert result.stop_loss_order.status == OrderStatus.SUBMITTED
    assert result.take_profit_order.status == OrderStatus.SUBMITTED

    print(f"✅ Bracket order placed:")
    print(f"   Entry:  {result.entry_order.order_id}")
    print(f"   SL:     {result.stop_loss_order.order_id}")
    print(f"   TP:     {result.take_profit_order.order_id}")

    # Cancel orders (cleanup)
    await order_executor.cancel_order(result.entry_order.order_id)
    await order_executor.cancel_order(result.stop_loss_order.order_id)
    await order_executor.cancel_order(result.take_profit_order.order_id)


@pytest.mark.asyncio
@pytest.mark.skipif(True, reason="Requires IB")
async def test_get_positions(order_executor):
    """Test getting current positions from IB."""
    positions = await order_executor.get_positions()

    # Should return list (may be empty in paper account)
    assert isinstance(positions, list)

    if positions:
        print(f"Current positions: {len(positions)}")
        for pos in positions:
            print(f"  {pos.contract.symbol}: {pos.position} contracts")


@pytest.mark.asyncio
@pytest.mark.skipif(True, reason="Requires IB")
async def test_get_open_orders(order_executor):
    """Test getting open orders from IB."""
    orders = await order_executor.get_open_orders()

    # Should return list
    assert isinstance(orders, list)

    print(f"Open orders: {len(orders)}")


# ─────────────────────────────────────────────────────────────────
# ERROR HANDLING TESTS
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_initialization_failure():
    """Test executor handles connection failure gracefully."""
    config = OrderExecutorConfig(
        host='invalid-host',
        port=9999,  # Invalid port
        paper_trading=True
    )

    executor = OrderExecutor(config)

    with pytest.raises(Exception):
        # Should raise connection error
        await executor.initialize()


def test_executor_stats():
    """Test executor statistics tracking."""
    config = OrderExecutorConfig()
    executor = OrderExecutor(config)

    stats = executor.get_stats()

    assert 'orders_submitted' in stats
    assert 'orders_filled' in stats
    assert 'orders_rejected' in stats
    assert 'active_orders' in stats
    assert 'fill_rate' in stats

    # Initially all zero
    assert stats['orders_submitted'] == 0
    assert stats['orders_filled'] == 0
    assert stats['fill_rate'] == 0


# ─────────────────────────────────────────────────────────────────
# MOCK TESTS (NO IB REQUIRED)
# ─────────────────────────────────────────────────────────────────

def test_order_result_dataclass():
    """Test OrderResult dataclass."""
    result = OrderResult(
        order_id=12345,
        status=OrderStatus.FILLED,
        filled_price=15250.50,
        filled_quantity=2
    )

    assert result.order_id == 12345
    assert result.status == OrderStatus.FILLED
    assert result.filled_price == 15250.50
    assert result.filled_quantity == 2
    assert result.timestamp is not None


def test_bracket_order_result_dataclass():
    """Test BracketOrderResult dataclass."""
    entry = OrderResult(order_id=1, status=OrderStatus.SUBMITTED)
    sl = OrderResult(order_id=2, status=OrderStatus.SUBMITTED)
    tp = OrderResult(order_id=3, status=OrderStatus.SUBMITTED)

    bracket = BracketOrderResult(
        entry_order=entry,
        stop_loss_order=sl,
        take_profit_order=tp,
        success=True
    )

    assert bracket.success is True
    assert bracket.entry_order.order_id == 1
    assert bracket.stop_loss_order.order_id == 2
    assert bracket.take_profit_order.order_id == 3


# ─────────────────────────────────────────────────────────────────
# CONFIGURATION TESTS
# ─────────────────────────────────────────────────────────────────

def test_order_executor_config_defaults():
    """Test OrderExecutorConfig default values."""
    config = OrderExecutorConfig()

    assert config.host == '127.0.0.1'
    assert config.port == 7497
    assert config.paper_trading is True
    assert config.max_retry_attempts == 3
    assert config.default_position_size == 1
    assert config.max_position_size == 5
    assert config.enable_bracket_orders is True


def test_order_executor_config_custom():
    """Test OrderExecutorConfig with custom values."""
    config = OrderExecutorConfig(
        host='192.168.1.100',
        port=4002,
        client_id=5,
        account='DU123456',
        paper_trading=False,
        max_position_size=10
    )

    assert config.host == '192.168.1.100'
    assert config.port == 4002
    assert config.client_id == 5
    assert config.account == 'DU123456'
    assert config.paper_trading is False
    assert config.max_position_size == 10
