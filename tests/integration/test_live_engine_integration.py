"""
Integration test for LiveTradingEngine with Week 2 components.

Tests the complete flow:
Data → SetupTracker → StateManager → OrderExecutor
"""

import pytest
import asyncio
import tempfile
import shutil
from datetime import datetime, timedelta

from slob.live.live_trading_engine import LiveTradingEngine


# Mark for IB integration tests
ib_integration = pytest.mark.skip(reason="Requires IB connection - run manually")


@pytest.mark.asyncio
@ib_integration
async def test_live_engine_initialization():
    """Test LiveTradingEngine initializes all Week 2 components."""

    # Create temp directory for databases
    temp_dir = tempfile.mkdtemp()

    try:
        # Create engine (IB mode, trading disabled for safety)
        engine = LiveTradingEngine(
            symbols=["NQ"],
            paper_trading=True,
            db_path=f"{temp_dir}/candles.db",
            state_db_path=f"{temp_dir}/state.db",
            data_source='ib',
            ib_host='127.0.0.1',
            ib_port=7497,
            ib_client_id=999,  # Test client
            enable_trading=False,  # Dry-run mode
            redis_host='localhost',
            redis_port=6379
        )

        # Initialize (will connect to IB)
        await engine.start()

        # Verify Week 1 components
        assert engine.event_bus is not None
        assert engine.tick_buffer is not None
        assert engine.candle_aggregator is not None
        assert engine.candle_store is not None
        assert engine.ws_fetcher is not None

        # Verify Week 2 components
        assert engine.setup_tracker is not None
        assert engine.state_manager is not None
        # OrderExecutor is None when trading is disabled
        assert engine.order_executor is None  # Trading disabled

        # Shutdown
        await engine.shutdown()

    finally:
        shutil.rmtree(temp_dir)


@pytest.mark.asyncio
async def test_setup_detection_and_persistence():
    """
    Test that setup detection works and state is persisted.

    This is a mock test - doesn't require real market data.
    """
    from slob.live.setup_tracker import SetupTracker, SetupTrackerConfig
    from slob.live.state_manager import StateManager, StateManagerConfig
    from slob.live.setup_state import SetupCandidate, SetupState

    temp_dir = tempfile.mkdtemp()

    try:
        # Initialize components
        tracker_config = SetupTrackerConfig(
            consol_min_duration=3,
            consol_max_duration=30,
            consol_min_quality=0.5
        )
        tracker = SetupTracker(tracker_config)

        state_config = StateManagerConfig(
            sqlite_path=f"{temp_dir}/state.db",
            enable_redis=False  # Use in-memory fallback
        )
        state_manager = StateManager(state_config)
        await state_manager.initialize()

        # Set LSE levels
        tracker.lse_high = 15300.0
        tracker.lse_low = 15200.0
        tracker.current_date = datetime(2024, 1, 15).date()

        # Create a mock setup candidate manually
        candidate = SetupCandidate(
            id="test-001",
            state=SetupState.WATCHING_CONSOL,
            lse_high=15300.0,
            lse_low=15200.0,
            liq1_detected=True,
            liq1_time=datetime.now(),
            liq1_price=15320.0
        )

        # Save to state manager
        await state_manager.save_setup(candidate)

        # Load back
        loaded_setups = await state_manager.load_active_setups()

        assert len(loaded_setups) == 1
        assert loaded_setups[0].id == "test-001"
        assert loaded_setups[0].state == SetupState.WATCHING_CONSOL
        assert loaded_setups[0].liq1_detected is True

        # Cleanup
        await state_manager.close()

    finally:
        shutil.rmtree(temp_dir)


@pytest.mark.asyncio
async def test_order_placement_dry_run():
    """
    Test order placement logic in dry-run mode.

    Verifies that setup → order flow works without placing real orders.
    """
    from slob.live.setup_state import SetupCandidate, SetupState
    from datetime import datetime

    # Create a completed setup
    setup = SetupCandidate(
        id="test-setup-001",
        state=SetupState.SETUP_COMPLETE,
        symbol="NQ",
        lse_high=15300.0,
        lse_low=15200.0,
        liq1_detected=True,
        liq1_time=datetime.now(),
        liq1_price=15320.0,
        liq2_detected=True,
        liq2_time=datetime.now() + timedelta(minutes=15),
        liq2_price=15315.0,
        entry_triggered=True,
        entry_trigger_time=datetime.now() + timedelta(minutes=20),
        entry_price=15297.0,
        sl_price=15316.0,
        tp_price=15199.0,
        risk_reward_ratio=5.2
    )

    # Verify setup data
    assert setup.entry_price == 15297.0
    assert setup.sl_price == 15316.0
    assert setup.tp_price == 15199.0

    # Calculate what order size would be
    from slob.live.order_executor import OrderExecutor, OrderExecutorConfig

    config = OrderExecutorConfig(max_position_size=5)
    executor = OrderExecutor(config)

    position_size = executor.calculate_position_size(
        account_balance=100000.0,
        risk_per_trade=0.01,
        entry_price=setup.entry_price,
        stop_loss_price=setup.sl_price
    )

    # With 100k account, 1% risk, and 19 points SL:
    # Risk = $1,000
    # Points risk = 19
    # Dollar risk per contract = 19 × $20 = $380
    # Contracts = $1,000 / $380 = 2.6 → 2 contracts
    assert position_size >= 1
    assert position_size <= 5  # Max clamp

    print(f"✅ Dry-run test: Would place {position_size} contracts")


@pytest.mark.asyncio
async def test_crash_recovery_scenario():
    """
    Simulate crash recovery:
    1. Create engine, detect setups
    2. Crash (shutdown)
    3. Restart engine
    4. Verify state recovered
    """
    temp_dir = tempfile.mkdtemp()

    try:
        # Phase 1: Initial session
        from slob.live.state_manager import StateManager, StateManagerConfig
        from slob.live.setup_state import SetupCandidate, SetupState

        config = StateManagerConfig(
            sqlite_path=f"{temp_dir}/state.db",
            enable_redis=False
        )
        manager1 = StateManager(config)
        await manager1.initialize()

        # Create and save 2 active setups
        setup1 = SetupCandidate(
            id="crash-001",
            state=SetupState.WATCHING_CONSOL,
            lse_high=15300.0
        )
        setup2 = SetupCandidate(
            id="crash-002",
            state=SetupState.WAITING_ENTRY,
            lse_high=15305.0,
            liq2_detected=True
        )

        await manager1.save_setup(setup1)
        await manager1.save_setup(setup2)

        # Simulate crash
        await manager1.close()

        # Phase 2: Restart
        manager2 = StateManager(config)
        await manager2.initialize()

        # Recover state
        recovered = await manager2.recover_state()

        assert len(recovered['active_setups']) == 2

        recovered_ids = {s.id for s in recovered['active_setups']}
        assert 'crash-001' in recovered_ids
        assert 'crash-002' in recovered_ids

        # Verify states preserved
        setup1_recovered = next(s for s in recovered['active_setups'] if s.id == 'crash-001')
        assert setup1_recovered.state == SetupState.WATCHING_CONSOL

        setup2_recovered = next(s for s in recovered['active_setups'] if s.id == 'crash-002')
        assert setup2_recovered.state == SetupState.WAITING_ENTRY
        assert setup2_recovered.liq2_detected is True

        await manager2.close()

        print("✅ Crash recovery verified")

    finally:
        shutil.rmtree(temp_dir)


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "-s"])
