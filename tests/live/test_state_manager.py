"""
Tests for StateManager - Crash Recovery and Persistence

Critical tests:
- Save/load active setups (Redis + SQLite)
- Crash recovery scenarios
- Trade persistence
- Session state management
- Transactional integrity
"""

import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, date, timedelta

from slob.live.state_manager import StateManager, StateManagerConfig
from slob.live.setup_state import SetupCandidate, SetupState, InvalidationReason


@pytest.fixture
async def temp_state_manager():
    """Create temporary StateManager with isolated storage."""
    # Create temporary directory for SQLite
    temp_dir = tempfile.mkdtemp()

    config = StateManagerConfig(
        redis_host='localhost',
        redis_port=6379,
        redis_db=15,  # Use test DB (different from production)
        sqlite_path=f"{temp_dir}/test_state.db",
        backup_dir=f"{temp_dir}/backups",
        enable_redis=True  # Will fallback to in-memory if Redis unavailable
    )

    manager = StateManager(config)
    await manager.initialize()

    # Clear any existing test data from Redis
    if manager.redis_client:
        await manager.redis_client.flushdb()

    yield manager

    # Cleanup
    await manager.close()
    shutil.rmtree(temp_dir)


# ─────────────────────────────────────────────────────────────────
# SETUP PERSISTENCE TESTS
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_and_load_active_setup(temp_state_manager):
    """Test saving setup to Redis and loading it back."""
    manager = temp_state_manager

    # Create setup candidate
    candidate = SetupCandidate(
        id="test-setup-001",
        state=SetupState.WATCHING_CONSOL,
        lse_high=15300.0,
        lse_low=15200.0,
        liq1_detected=True,
        liq1_time=datetime.now(),
        liq1_price=15320.0,
        symbol="NQ"
    )

    # Save to storage
    await manager.save_setup(candidate)

    # Load back from Redis
    loaded_setups = await manager.load_active_setups()

    assert len(loaded_setups) == 1
    loaded = loaded_setups[0]

    assert loaded.id == candidate.id
    assert loaded.state == SetupState.WATCHING_CONSOL
    assert loaded.lse_high == 15300.0
    assert loaded.liq1_detected is True
    assert loaded.liq1_price == 15320.0


@pytest.mark.asyncio
async def test_completed_setup_removed_from_redis(temp_state_manager):
    """Test that completed setups are removed from active Redis keys."""
    manager = temp_state_manager

    # Create active setup
    candidate = SetupCandidate(
        id="test-setup-002",
        state=SetupState.WATCHING_LIQ2,
        lse_high=15300.0
    )

    await manager.save_setup(candidate)

    # Verify it's in Redis
    active_setups = await manager.load_active_setups()
    assert len(active_setups) == 1

    # Mark as complete
    candidate.state = SetupState.SETUP_COMPLETE
    candidate.entry_triggered = True

    await manager.save_setup(candidate)

    # Should be removed from Redis
    active_setups = await manager.load_active_setups()
    assert len(active_setups) == 0


@pytest.mark.asyncio
async def test_invalidated_setup_removed_from_redis(temp_state_manager):
    """Test that invalidated setups are removed from active Redis keys."""
    manager = temp_state_manager

    candidate = SetupCandidate(
        id="test-setup-003",
        state=SetupState.WATCHING_CONSOL
    )

    await manager.save_setup(candidate)

    # Invalidate
    candidate.state = SetupState.INVALIDATED
    candidate.invalidation_reason = InvalidationReason.CONSOL_TIMEOUT

    await manager.save_setup(candidate)

    # Should be removed from Redis
    active_setups = await manager.load_active_setups()
    assert len(active_setups) == 0


@pytest.mark.asyncio
async def test_multiple_active_setups(temp_state_manager):
    """Test tracking multiple concurrent setups."""
    manager = temp_state_manager

    # Create 3 concurrent candidates
    for i in range(3):
        candidate = SetupCandidate(
            id=f"test-setup-{i:03d}",
            state=SetupState.WATCHING_CONSOL,
            lse_high=15300.0 + i * 10
        )
        await manager.save_setup(candidate)

    # Load all
    active_setups = await manager.load_active_setups()

    assert len(active_setups) == 3
    assert all(s.state == SetupState.WATCHING_CONSOL for s in active_setups)


# ─────────────────────────────────────────────────────────────────
# CRASH RECOVERY TESTS
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crash_recovery_active_setups(temp_state_manager):
    """
    Test crash recovery scenario.

    Simulate:
    1. System running with 2 active setups
    2. System crashes (StateManager closed)
    3. System restarts (new StateManager)
    4. Verify state recovered
    """
    manager = temp_state_manager

    # Create 2 active setups
    setup1 = SetupCandidate(
        id="crash-test-001",
        state=SetupState.WATCHING_CONSOL,
        lse_high=15300.0,
        liq1_detected=True
    )

    setup2 = SetupCandidate(
        id="crash-test-002",
        state=SetupState.WAITING_ENTRY,
        lse_high=15305.0,
        liq1_detected=True,
        liq2_detected=True,
        entry_price=15280.0
    )

    await manager.save_setup(setup1)
    await manager.save_setup(setup2)

    # Simulate crash - close manager
    await manager.close()

    # Simulate restart - create new manager with same config
    new_manager = StateManager(manager.config)
    await new_manager.initialize()

    # Recover state
    recovered_state = await new_manager.recover_state()

    # Verify recovery
    assert len(recovered_state['active_setups']) == 2

    recovered_ids = {s.id for s in recovered_state['active_setups']}
    assert 'crash-test-001' in recovered_ids
    assert 'crash-test-002' in recovered_ids

    # Verify states preserved
    setup1_recovered = next(s for s in recovered_state['active_setups'] if s.id == 'crash-test-001')
    assert setup1_recovered.state == SetupState.WATCHING_CONSOL
    assert setup1_recovered.liq1_detected is True

    setup2_recovered = next(s for s in recovered_state['active_setups'] if s.id == 'crash-test-002')
    assert setup2_recovered.state == SetupState.WAITING_ENTRY
    assert setup2_recovered.liq2_detected is True

    await new_manager.close()


@pytest.mark.asyncio
async def test_crash_recovery_with_completed_setups(temp_state_manager):
    """
    Test that completed setups are NOT loaded as active after crash.
    """
    manager = temp_state_manager

    # Create 1 active, 1 completed setup
    active = SetupCandidate(id="active-001", state=SetupState.WATCHING_LIQ2)
    completed = SetupCandidate(id="completed-001", state=SetupState.SETUP_COMPLETE)

    await manager.save_setup(active)
    await manager.save_setup(completed)

    # Close and restart
    await manager.close()

    new_manager = StateManager(manager.config)
    await new_manager.initialize()

    recovered = await new_manager.recover_state()

    # Only active setup should be loaded
    assert len(recovered['active_setups']) == 1
    assert recovered['active_setups'][0].id == 'active-001'

    await new_manager.close()


# ─────────────────────────────────────────────────────────────────
# TRADE PERSISTENCE TESTS
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_persist_trade(temp_state_manager):
    """Test saving trade to SQLite."""
    manager = temp_state_manager

    trade_data = {
        'setup_id': 'setup-123',
        'symbol': 'NQ',
        'entry_time': datetime.now().isoformat(),
        'entry_price': 15250.0,
        'position_size': 2,
        'sl_price': 15300.0,
        'tp_price': 15100.0,
        'result': 'OPEN'
    }

    await manager.persist_trade(trade_data)

    # Query back
    trades = await manager.get_trades_for_setup('setup-123')

    assert len(trades) == 1
    assert trades[0]['setup_id'] == 'setup-123'
    assert trades[0]['entry_price'] == 15250.0
    assert trades[0]['position_size'] == 2
    assert trades[0]['result'] == 'OPEN'


@pytest.mark.asyncio
async def test_persist_multiple_trades(temp_state_manager):
    """Test multiple trades for same setup."""
    manager = temp_state_manager

    setup_id = 'setup-456'

    # Entry
    entry_trade = {
        'setup_id': setup_id,
        'symbol': 'NQ',
        'entry_time': datetime.now().isoformat(),
        'entry_price': 15250.0,
        'position_size': 2,
        'sl_price': 15300.0,
        'tp_price': 15100.0,
        'result': 'OPEN'
    }

    await manager.persist_trade(entry_trade)

    # Exit (update with new trade or update existing - here we're just saving another row)
    exit_trade = {
        'setup_id': setup_id,
        'symbol': 'NQ',
        'entry_time': datetime.now().isoformat(),
        'entry_price': 15250.0,
        'position_size': 2,
        'exit_time': (datetime.now() + timedelta(minutes=30)).isoformat(),
        'exit_price': 15150.0,
        'exit_reason': 'TP',
        'pnl': 200.0,
        'pnl_percent': 1.33,
        'sl_price': 15300.0,
        'tp_price': 15100.0,
        'result': 'WIN'
    }

    await manager.persist_trade(exit_trade)

    # Query
    trades = await manager.get_trades_for_setup(setup_id)

    assert len(trades) == 2


@pytest.mark.asyncio
async def test_crash_recovery_open_trades(temp_state_manager):
    """Test recovery of open trades after crash."""
    manager = temp_state_manager

    # Create 2 open trades
    trade1 = {
        'setup_id': 'open-001',
        'symbol': 'NQ',
        'entry_time': datetime.now().isoformat(),
        'entry_price': 15250.0,
        'position_size': 1,
        'sl_price': 15280.0,
        'tp_price': 15180.0,
        'result': 'OPEN'
    }

    trade2 = {
        'setup_id': 'open-002',
        'symbol': 'NQ',
        'entry_time': datetime.now().isoformat(),
        'entry_price': 15300.0,
        'position_size': 2,
        'sl_price': 15330.0,
        'tp_price': 15230.0,
        'result': 'OPEN'
    }

    await manager.persist_trade(trade1)
    await manager.persist_trade(trade2)

    # Simulate crash
    await manager.close()

    new_manager = StateManager(manager.config)
    await new_manager.initialize()

    # Recover
    recovered = await new_manager.recover_state()

    assert len(recovered['open_trades']) == 2
    assert all(t['result'] == 'OPEN' for t in recovered['open_trades'])

    await new_manager.close()


# ─────────────────────────────────────────────────────────────────
# SESSION STATE TESTS
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_init(temp_state_manager):
    """Test session initialization."""
    manager = temp_state_manager

    today = date.today()
    starting_capital = 100000.0

    await manager.init_session(today, starting_capital)

    # Query session
    session = await manager.get_session(today)

    assert session is not None
    assert session['date'] == str(today)
    assert session['starting_capital'] == starting_capital
    assert session['setups_detected'] == 0
    assert session['trades_executed'] == 0


@pytest.mark.asyncio
async def test_session_updates(temp_state_manager):
    """Test updating session state."""
    manager = temp_state_manager

    today = date.today()

    await manager.init_session(today, 100000.0)

    # Update metrics
    await manager.update_session(
        today,
        setups_detected=3,
        trades_executed=2,
        trades_won=1,
        trades_lost=1,
        daily_pnl=150.0
    )

    # Verify updates
    session = await manager.get_session(today)

    assert session['setups_detected'] == 3
    assert session['trades_executed'] == 2
    assert session['trades_won'] == 1
    assert session['trades_lost'] == 1
    assert session['daily_pnl'] == 150.0


@pytest.mark.asyncio
async def test_crash_recovery_session_state(temp_state_manager):
    """Test session state recovery after crash."""
    manager = temp_state_manager

    today = date.today()

    await manager.init_session(today, 100000.0)
    await manager.update_session(today, setups_detected=5, daily_pnl=300.0)

    # Crash
    await manager.close()

    # Restart
    new_manager = StateManager(manager.config)
    await new_manager.initialize()

    recovered = await new_manager.recover_state()

    assert recovered['session_state'] is not None
    assert recovered['session_state']['setups_detected'] == 5
    assert recovered['session_state']['daily_pnl'] == 300.0

    await new_manager.close()


# ─────────────────────────────────────────────────────────────────
# EDGE CASES
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deserialize_setup_with_nulls(temp_state_manager):
    """Test deserializing setup with many None values."""
    manager = temp_state_manager

    # Minimal setup (just created, nothing detected yet)
    candidate = SetupCandidate(
        id="minimal-001",
        state=SetupState.WATCHING_LIQ1,
        lse_high=15300.0,
        lse_low=15200.0
    )

    await manager.save_setup(candidate)

    loaded = await manager.load_active_setups()

    assert len(loaded) == 1
    assert loaded[0].id == 'minimal-001'
    assert loaded[0].liq1_detected is False
    assert loaded[0].liq1_time is None
    assert loaded[0].liq2_time is None
    assert loaded[0].entry_trigger_time is None


@pytest.mark.asyncio
async def test_update_existing_setup(temp_state_manager):
    """Test updating existing setup (UPSERT behavior)."""
    manager = temp_state_manager

    candidate = SetupCandidate(
        id="update-001",
        state=SetupState.WATCHING_CONSOL,
        lse_high=15300.0
    )

    await manager.save_setup(candidate)

    # Update state
    candidate.state = SetupState.WATCHING_LIQ2
    candidate.liq2_detected = True
    candidate.liq2_time = datetime.now()

    await manager.save_setup(candidate)

    # Load - should have updated state
    loaded = await manager.load_active_setups()

    assert len(loaded) == 1
    assert loaded[0].state == SetupState.WATCHING_LIQ2
    assert loaded[0].liq2_detected is True


@pytest.mark.asyncio
async def test_in_memory_fallback_no_redis():
    """Test that StateManager works without Redis (in-memory fallback)."""
    temp_dir = tempfile.mkdtemp()

    config = StateManagerConfig(
        sqlite_path=f"{temp_dir}/test_state.db",
        enable_redis=False  # Disable Redis
    )

    manager = StateManager(config)
    await manager.initialize()

    # Save setup (should use in-memory store)
    candidate = SetupCandidate(
        id="memory-001",
        state=SetupState.WATCHING_CONSOL,
        lse_high=15300.0
    )

    await manager.save_setup(candidate)

    # Load (from memory)
    loaded = await manager.load_active_setups()

    assert len(loaded) == 1
    assert loaded[0].id == 'memory-001'

    await manager.close()
    shutil.rmtree(temp_dir)


# ─────────────────────────────────────────────────────────────────
# PERFORMANCE TESTS
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_load_performance(temp_state_manager):
    """Test performance with many setups."""
    manager = temp_state_manager

    import time

    # Save 100 setups
    start = time.time()

    for i in range(100):
        candidate = SetupCandidate(
            id=f"perf-{i:04d}",
            state=SetupState.WATCHING_CONSOL,
            lse_high=15300.0 + i
        )
        await manager.save_setup(candidate)

    save_time = time.time() - start

    # Load all
    start = time.time()
    loaded = await manager.load_active_setups()
    load_time = time.time() - start

    assert len(loaded) == 100

    # Performance check (should be fast)
    assert save_time < 2.0  # 100 saves in < 2 seconds
    assert load_time < 0.5  # Load 100 in < 0.5 seconds

    print(f"✅ Performance: Save 100 setups: {save_time:.3f}s, Load 100: {load_time:.3f}s")
