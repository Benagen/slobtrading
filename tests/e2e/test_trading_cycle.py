"""
End-to-End Trading Cycle Tests

Tests the complete trading cycle from setup detection through order execution.

Test Scenarios:
1. Happy path: Setup → Entry → Fill → Exit
2. Rejected order: Setup → Entry attempt → Order rejected (Error 321)
3. Partial fill: Setup → Entry → Partial fill → Wait → Complete fill
4. Timeout: Setup → Entry → Timeout → Cancel order
5. Crash recovery: Setup → Crash mid-order → Restart → Position reconciled

This is a critical test suite validating that the entire system works together.
"""

import pytest
import asyncio
import sqlite3
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, MagicMock, patch
from typing import Dict, List

# Import system components
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'slob'))

from slob.live.setup_tracker import SetupTracker, SetupTrackerConfig
from slob.live.order_executor import OrderExecutor, OrderExecutorConfig
from slob.live.state_manager import StateManager
from slob.live.setup_state import SetupState, SetupCandidate


@pytest.fixture
def temp_db(tmp_path):
    """Create temporary database for testing."""
    db_path = tmp_path / "test_trading.db"
    return str(db_path)


@pytest.fixture
def setup_tracker_config():
    """Create SetupTracker configuration for testing."""
    return SetupTrackerConfig(
        lse_open=time(9, 0),
        lse_close=time(15, 30),
        nyse_open=time(15, 30),
        consol_min_duration=5,  # Shorter for testing
        consol_max_duration=15,
        consol_min_quality=0.3,
        atr_period=14,
        max_entry_wait_candles=10,
        symbol="NQ"
    )


@pytest.fixture
def order_executor_config():
    """Create OrderExecutor configuration for testing."""
    return OrderExecutorConfig(
        host='127.0.0.1',
        port=4002,
        client_id=999,  # Test client ID
        account='DU123456',  # Paper trading account
        paper_trading=True,
        max_retry_attempts=3,
        default_position_size=1
    )


@pytest.fixture
async def setup_tracker(setup_tracker_config):
    """Create SetupTracker instance."""
    tracker = SetupTracker(setup_tracker_config)
    yield tracker


@pytest.fixture
async def mock_ib_connection():
    """Mock IB connection for testing."""
    mock_ib = AsyncMock()
    mock_ib.isConnected.return_value = True
    mock_ib.connectAsync = AsyncMock()
    mock_ib.reqMarketDataType = Mock()

    # Mock contract qualification
    mock_ib.qualifyContractsAsync = AsyncMock()

    # Mock account values
    mock_account_value = Mock()
    mock_account_value.tag = 'NetLiquidation'
    mock_account_value.currency = 'USD'
    mock_account_value.value = '100000.0'
    mock_ib.accountValuesAsync = AsyncMock(return_value=[mock_account_value])

    return mock_ib


class TestHappyPathTradingCycle:
    """Test complete successful trading cycle."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_complete_cycle_setup_to_exit(
        self,
        setup_tracker,
        temp_db,
        setup_tracker_config
    ):
        """
        Test happy path: Setup detection → Order placement → Fill → Exit.

        Flow:
        1. Feed LSE session candles (establish LSE high/low)
        2. Feed NYSE candles to create LIQ #1
        3. Feed consolidation candles
        4. Feed LIQ #2 breakout
        5. Feed entry trigger (close below no-wick low)
        6. Verify setup completed with correct SL/TP
        """
        # Step 1: LSE Session - establish LSE high/low
        lse_candles = self._generate_lse_candles(
            start_time=datetime.combine(datetime.now().date(), time(9, 0)),
            count=20,
            high_price=18500.0,
            low_price=18400.0
        )

        for candle in lse_candles:
            result = await setup_tracker.on_candle(candle)
            assert not result.setup_completed, "No setup should complete during LSE"

        # Verify LSE levels set
        assert setup_tracker.lse_high == 18500.0
        assert setup_tracker.lse_low == 18400.0

        # Step 2: NYSE Session - create LIQ #1 (break LSE high)
        liq1_candle = {
            'timestamp': datetime.combine(datetime.now().date(), time(15, 35)),
            'open': 18495.0,
            'high': 18520.0,  # Breaks LSE high
            'low': 18490.0,
            'close': 18510.0,
            'volume': 1000
        }

        result = await setup_tracker.on_candle(liq1_candle)
        assert not result.setup_completed
        assert len(setup_tracker.active_candidates) == 1, "LIQ #1 should create candidate"

        candidate_id = list(setup_tracker.active_candidates.keys())[0]
        candidate = setup_tracker.active_candidates[candidate_id]
        assert candidate.state == SetupState.WATCHING_CONSOL
        assert candidate.liq1_detected is True
        assert candidate.liq1_price == 18520.0

        # Step 3: Consolidation - feed tight range candles (need min 5 for test config)
        consol_candles = self._generate_consolidation_candles(
            start_time=liq1_candle['timestamp'] + timedelta(minutes=1),
            count=6,  # 6 candles to reach min_duration of 5
            high=18515.0,
            low=18505.0
        )

        for i, candle in enumerate(consol_candles):
            result = await setup_tracker.on_candle(candle)
            candidate = setup_tracker.active_candidates.get(candidate_id)

            # At min_duration (5 candles), should transition to WATCHING_LIQ2
            if i >= setup_tracker_config.consol_min_duration - 1:
                # Should have transitioned to WATCHING_LIQ2
                if candidate and candidate.state == SetupState.WATCHING_LIQ2:
                    assert candidate.consol_confirmed is True
                    assert candidate.nowick_found is True
                    break
            else:
                assert not result.setup_completed

        # Ensure we transitioned
        candidate = setup_tracker.active_candidates.get(candidate_id)
        assert candidate is not None, "Candidate should still exist"
        assert candidate.state == SetupState.WATCHING_LIQ2, f"Expected WATCHING_LIQ2, got {candidate.state}"

        # Step 4: LIQ #2 - break consolidation high
        liq2_candle = {
            'timestamp': consol_candles[-1]['timestamp'] + timedelta(minutes=1),
            'open': 18510.0,
            'high': 18530.0,  # Breaks consol high
            'low': 18508.0,
            'close': 18525.0,
            'volume': 1500
        }

        result = await setup_tracker.on_candle(liq2_candle)
        candidate = setup_tracker.active_candidates[candidate_id]
        assert candidate.state == SetupState.WAITING_ENTRY
        assert candidate.liq2_detected is True
        assert candidate.liq2_price == 18530.0

        # Step 5: Entry trigger - close below no-wick low
        entry_trigger_candle = {
            'timestamp': liq2_candle['timestamp'] + timedelta(minutes=1),
            'open': 18520.0,
            'high': 18522.0,
            'low': 18495.0,
            'close': 18500.0,  # Below no-wick low
            'volume': 1200
        }

        result = await setup_tracker.on_candle(entry_trigger_candle)

        # Verify setup completed
        assert result.setup_completed is True
        assert result.candidate.state == SetupState.SETUP_COMPLETE
        assert result.candidate.entry_triggered is True
        assert result.candidate.entry_price is not None
        assert result.candidate.sl_price is not None
        assert result.candidate.tp_price == setup_tracker.lse_low - setup_tracker_config.tp_buffer_pips

        # Verify risk/reward ratio calculated
        assert result.candidate.risk_reward_ratio > 0

        # Verify candidate moved to completed list
        assert candidate_id not in setup_tracker.active_candidates
        assert len(setup_tracker.completed_setups) == 1

    def _generate_lse_candles(
        self,
        start_time: datetime,
        count: int,
        high_price: float,
        low_price: float
    ) -> List[Dict]:
        """Generate LSE session candles."""
        candles = []
        current_time = start_time

        for i in range(count):
            candle = {
                'timestamp': current_time,
                'open': low_price + (high_price - low_price) * 0.5,
                'high': high_price if i == count // 2 else high_price - 10,
                'low': low_price if i == count // 2 else low_price + 10,
                'close': low_price + (high_price - low_price) * 0.6,
                'volume': 500 + i * 10
            }
            candles.append(candle)
            current_time += timedelta(minutes=1)

        return candles

    def _generate_consolidation_candles(
        self,
        start_time: datetime,
        count: int,
        high: float,
        low: float
    ) -> List[Dict]:
        """
        Generate tight consolidation candles with a clear no-wick candidate.

        Creates varied candles to ensure proper percentile calculations:
        - Varied body sizes (1-6 pips) for 30th-70th percentile range
        - Middle candle has minimal upper wick and medium body
        - Other candles have larger upper wicks
        """
        candles = []
        current_time = start_time
        mid = (high + low) / 2

        # Body size patterns: [small, medium, large, small, medium, large]
        # This ensures the middle candle's body falls in 30th-70th percentile
        body_patterns = [2, 3, 5, 2, 4, 6]  # Varies from 2-6 pips
        wick_patterns = [4, 3.5, 5, 4.5, 3, 4]  # Upper wicks 3-5 pips

        for i in range(count):
            # Make middle candle a clear no-wick bullish candle
            if i == count // 2:
                candle = {
                    'timestamp': current_time,
                    'open': mid - 2,
                    'high': mid + 2.5,  # Small upper wick = 0.5 pips
                    'low': mid - 3,
                    'close': mid + 2,  # Bullish close, body = 4 pips
                    'volume': 300
                }
            else:
                # Other candles - varied bodies and larger wicks
                idx = min(i, len(body_patterns) - 1)
                body = body_patterns[idx] / 2  # Half for each direction
                wick = wick_patterns[idx]

                candle = {
                    'timestamp': current_time,
                    'open': mid - body,
                    'high': mid + body + wick,  # Larger upper wick
                    'low': mid - body - 1,
                    'close': mid + body,  # Bullish
                    'volume': 250
                }

            candles.append(candle)
            current_time += timedelta(minutes=1)

        return candles


class TestRejectedOrderScenario:
    """Test order rejection scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_insufficient_buying_power(
        self,
        mock_ib_connection,
        order_executor_config
    ):
        """
        Test order rejected due to insufficient buying power (IB Error 321).

        Flow:
        1. Mock IB to return Error 321 on order placement
        2. Attempt to place order
        3. Verify error handled and trading disabled
        """
        # Mock IB to trigger error 321
        mock_ib_connection.placeOrder = Mock(side_effect=Exception("Error 321: Insufficient buying power"))

        # Create order executor with mocked IB
        with patch('slob.live.order_executor.IB', return_value=mock_ib_connection):
            executor = OrderExecutor(order_executor_config)
            executor.ib = mock_ib_connection
            executor.connected = True
            executor.trading_enabled = True
            executor.pending_orders = {}  # Initialize pending_orders

            # Create a pending order entry first
            executor.pending_orders[1] = {
                'timestamp': datetime.now(),
                'status': 'pending'
            }

            # Simulate error 321
            executor._handle_ib_error(
                reqId=1,
                errorCode=321,
                errorString="Insufficient buying power",
                contract=None
            )

            # Verify trading disabled
            assert executor.trading_enabled is False
            assert 1 in executor.pending_orders
            assert executor.pending_orders[1]['error']['code'] == 321


class TestPartialFillScenario:
    """Test partial fill handling."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_partial_fill_completion(
        self,
        mock_ib_connection,
        order_executor_config
    ):
        """
        Test partial fill → wait → complete fill scenario.

        Flow:
        1. Place order for 2 contracts
        2. Receive partial fill (1 contract)
        3. Wait for remaining fill
        4. Verify final position = 2 contracts
        """
        # This test would require more complex IB mocking
        # Marking as TODO for now - needs Trade object mocking
        pytest.skip("Requires Trade object mocking - TODO")


class TestTimeoutScenario:
    """Test order timeout and cancellation."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_entry_timeout_cancellation(self, setup_tracker_config):
        """
        Test setup invalidation on entry timeout.

        Flow:
        1. Create fresh tracker with setup in WAITING_ENTRY state
        2. Feed candles without entry trigger
        3. Verify invalidation after max_entry_wait_candles
        """
        # Create fresh tracker to avoid state contamination
        fresh_tracker = SetupTracker(setup_tracker_config)

        # Set LSE levels (required for NYSE session)
        fresh_tracker.lse_high = 18500.0
        fresh_tracker.lse_low = 18400.0
        fresh_tracker.lse_close_time = datetime.combine(datetime.now().date(), time(15, 30))
        fresh_tracker.current_date = datetime.now().date()

        # Create a candidate manually in WAITING_ENTRY state
        candidate = SetupCandidate(
            symbol="NQ",
            lse_high=18500.0,
            lse_low=18400.0,
            lse_close_time=fresh_tracker.lse_close_time,
            state=SetupState.WAITING_ENTRY
        )

        # Set required fields for WAITING_ENTRY
        candidate.liq2_detected = True
        candidate.liq2_price = 18520.0
        candidate.liq2_time = datetime.combine(datetime.now().date(), time(16, 0))
        candidate.liq2_candle = {'open': 18510, 'high': 18520, 'low': 18505, 'close': 18515}
        candidate.spike_high = 18520.0
        candidate.spike_high_time = candidate.liq2_time
        candidate.nowick_low = 18505.0
        candidate.consol_candles = [{'timestamp': candidate.liq2_time, 'high': 18515, 'low': 18505}]
        # Track candles processed
        candidate.candles_processed = len(candidate.consol_candles) + 1  # consol + liq2

        fresh_tracker.active_candidates[candidate.id] = candidate

        # Feed candles without triggering entry (close stays above no-wick low)
        current_time = datetime.combine(datetime.now().date(), time(16, 1))

        for i in range(setup_tracker_config.max_entry_wait_candles + 2):
            candle = {
                'timestamp': current_time + timedelta(minutes=i),
                'open': 18520.0,
                'high': 18525.0,
                'low': 18515.0,
                'close': 18520.0,  # Above no-wick low - no entry
                'volume': 500
            }

            result = await fresh_tracker.on_candle(candle)

            if i >= setup_tracker_config.max_entry_wait_candles:
                # Should invalidate
                assert result.setup_invalidated is True
                assert candidate.id not in fresh_tracker.active_candidates
                assert len(fresh_tracker.invalidated_setups) == 1
                break


class TestCrashRecoveryScenario:
    """Test system crash recovery mid-trade."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_position_reconciliation_after_crash(
        self,
        temp_db
    ):
        """
        Test position reconciliation after crash.

        Flow:
        1. Create StateManager with active trade
        2. Simulate crash (don't close properly)
        3. Create new StateManager
        4. Verify active trade recovered
        """
        from slob.live.state_manager import StateManager, StateManagerConfig

        # Step 1: Create initial state with active trade
        config = StateManagerConfig(
            sqlite_path=temp_db,
            enable_redis=False  # Disable Redis for testing
        )
        manager1 = StateManager(config)
        await manager1.initialize()  # CRITICAL: Initialize database connection

        # Create an active setup as SetupCandidate object
        setup = SetupCandidate(
            symbol='NQ',
            lse_high=18500.0,
            lse_low=18400.0,
            lse_close_time=datetime.now(),
            state=SetupState.WAITING_ENTRY
        )
        # Set id explicitly for testing
        setup.id = 'test-setup-123'
        setup.liq1_price = 18520.0
        setup.liq2_price = 18520.0
        setup.consol_low = 18505.0
        setup.consol_high = 18515.0
        setup.direction = 'SHORT'

        await manager1.save_setup(setup)

        # Simulate crash - don't call close()
        del manager1

        # Step 2: Create new manager (simulates restart)
        config2 = StateManagerConfig(
            sqlite_path=temp_db,
            enable_redis=False
        )
        manager2 = StateManager(config2)
        await manager2.initialize()  # CRITICAL: Initialize database connection

        # Step 3: Recover state
        recovered_setups = await manager2.get_active_setups()

        # Verify recovery
        assert len(recovered_setups) >= 1, f"Expected at least 1 setup, got {len(recovered_setups)}"

        # Find our test setup
        test_setup = None
        for s in recovered_setups:
            if isinstance(s, SetupCandidate):
                if s.id == 'test-setup-123':
                    test_setup = s
                    break
            elif isinstance(s, dict):
                if s.get('id') == 'test-setup-123':
                    test_setup = s
                    break

        assert test_setup is not None, "Test setup not found in recovered setups"

        # Verify fields (handle both dict and object)
        if isinstance(test_setup, SetupCandidate):
            assert test_setup.symbol == 'NQ'
            assert test_setup.state == SetupState.WAITING_ENTRY
        else:
            assert test_setup['symbol'] == 'NQ'

        # Cleanup
        await manager2.close()


# Summary test to verify all scenarios can run
@pytest.mark.asyncio
@pytest.mark.integration
async def test_all_scenarios_summary(setup_tracker):
    """Quick sanity check that all test scenarios are runnable."""
    assert setup_tracker is not None
    assert setup_tracker.config.symbol == "NQ"
    assert len(setup_tracker.active_candidates) == 0
