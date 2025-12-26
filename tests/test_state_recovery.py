"""
Tests for State Recovery (Phase 2).

Tests:
- State recovery on startup
- Position reconciliation with IB
- Active setup restoration
- Open trade recovery
- Mismatch detection and alerting

Run with: pytest tests/test_state_recovery.py -v
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from datetime import datetime
from pathlib import Path

from slob.live.live_trading_engine import LiveTradingEngine, LiveTradingEngineConfig
from slob.live.setup_state import SetupCandidate, SetupState


class TestStateRecovery:
    """Test suite for state recovery functionality"""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        config = LiveTradingEngineConfig(
            symbol='NQ',
            account='DU123456',
            ib_host='127.0.0.1',
            ib_port=4002,
            client_id=1,
            redis_host='localhost',
            redis_port=6379
        )
        return config

    @pytest.fixture
    def mock_state_manager(self):
        """Create mock state manager."""
        manager = Mock()
        manager.initialize = AsyncMock()
        manager.get_active_setups = AsyncMock(return_value=[])
        manager.get_open_trades = AsyncMock(return_value=[])
        manager.close_trade = AsyncMock()
        manager.close = AsyncMock()
        return manager

    @pytest.fixture
    def mock_order_executor(self):
        """Create mock order executor."""
        executor = Mock()
        executor.initialize = AsyncMock()
        executor.get_positions = AsyncMock(return_value=[])
        executor.close = AsyncMock()
        executor.is_connected = Mock(return_value=True)
        return executor

    @pytest.fixture
    def mock_setup_tracker(self):
        """Create mock setup tracker."""
        tracker = Mock()
        tracker.restore_setup = AsyncMock()
        return tracker

    @pytest.mark.asyncio
    async def test_recover_state_initializes_state_manager(
        self, mock_config, mock_state_manager
    ):
        """Test that recover_state() initializes state manager."""
        engine = LiveTradingEngine(config=mock_config)
        engine.state_manager = mock_state_manager
        engine.setup_tracker = Mock()
        engine.order_executor = Mock()
        engine.order_executor.get_positions = AsyncMock(return_value=[])

        await engine.recover_state()

        mock_state_manager.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_recover_active_setups(
        self, mock_config, mock_state_manager, mock_setup_tracker
    ):
        """Test recovery of active setups from database."""
        # Create mock active setups
        setup1 = {
            'id': 'setup1',
            'type': 'LIQ1',
            'state': 'WAITING_ENTRY',
            'entry_price': 19500.0,
            'sl_price': 19550.0,
            'tp_price': 19400.0
        }
        setup2 = {
            'id': 'setup2',
            'type': 'LIQ2',
            'state': 'IN_TRADE',
            'entry_price': 19600.0,
            'sl_price': 19650.0,
            'tp_price': 19500.0
        }

        mock_state_manager.get_active_setups = AsyncMock(
            return_value=[setup1, setup2]
        )

        engine = LiveTradingEngine(config=mock_config)
        engine.state_manager = mock_state_manager
        engine.setup_tracker = mock_setup_tracker
        engine.order_executor = Mock()
        engine.order_executor.get_positions = AsyncMock(return_value=[])

        await engine.recover_state()

        # Should have restored both setups
        assert mock_setup_tracker.restore_setup.call_count == 2
        mock_setup_tracker.restore_setup.assert_any_call(setup1)
        mock_setup_tracker.restore_setup.assert_any_call(setup2)

    @pytest.mark.asyncio
    async def test_recover_open_trades(
        self, mock_config, mock_state_manager
    ):
        """Test recovery of open trades from database."""
        # Create mock open trades
        trade1 = {
            'id': 'trade1',
            'setup_id': 'setup1',
            'symbol': 'NQ',
            'entry_price': 19500.0,
            'quantity': 1,
            'state': 'OPEN'
        }
        trade2 = {
            'id': 'trade2',
            'setup_id': 'setup2',
            'symbol': 'NQ',
            'entry_price': 19600.0,
            'quantity': 1,
            'state': 'OPEN'
        }

        mock_state_manager.get_open_trades = AsyncMock(
            return_value=[trade1, trade2]
        )

        engine = LiveTradingEngine(config=mock_config)
        engine.state_manager = mock_state_manager
        engine.setup_tracker = Mock()
        engine.setup_tracker.restore_setup = AsyncMock()
        engine.order_executor = Mock()
        engine.order_executor.get_positions = AsyncMock(return_value=[])

        await engine.recover_state()

        # Should have called get_open_trades
        mock_state_manager.get_open_trades.assert_called_once()

    @pytest.mark.asyncio
    async def test_position_reconciliation_matching_positions(
        self, mock_config, mock_state_manager, mock_order_executor
    ):
        """Test position reconciliation when IB and DB match."""
        # Create matching positions
        ib_position = Mock()
        ib_position.contract.symbol = 'NQ'
        ib_position.position = 1
        ib_position.avgCost = 19500.0

        db_trade = {
            'id': 'trade1',
            'setup_id': 'setup1',
            'symbol': 'NQ',
            'entry_price': 19500.0,
            'quantity': 1,
            'state': 'OPEN'
        }

        mock_order_executor.get_positions = AsyncMock(return_value=[ib_position])
        mock_state_manager.get_open_trades = AsyncMock(return_value=[db_trade])

        engine = LiveTradingEngine(config=mock_config)
        engine.state_manager = mock_state_manager
        engine.order_executor = mock_order_executor
        engine.setup_tracker = Mock()
        engine.setup_tracker.restore_setup = AsyncMock()

        await engine.recover_state()

        # No alerts should be triggered (positions match)
        # close_trade should NOT be called
        mock_state_manager.close_trade.assert_not_called()

    @pytest.mark.asyncio
    async def test_position_reconciliation_unexpected_position(
        self, mock_config, mock_state_manager, mock_order_executor, caplog
    ):
        """Test detection of unexpected position in IB (not in DB)."""
        # IB has position, DB doesn't
        ib_position = Mock()
        ib_position.contract.symbol = 'NQ'
        ib_position.position = 1

        mock_order_executor.get_positions = AsyncMock(return_value=[ib_position])
        mock_state_manager.get_open_trades = AsyncMock(return_value=[])  # Empty DB

        engine = LiveTradingEngine(config=mock_config)
        engine.state_manager = mock_state_manager
        engine.order_executor = mock_order_executor
        engine.setup_tracker = Mock()
        engine.setup_tracker.restore_setup = AsyncMock()

        with caplog.at_level('CRITICAL'):
            await engine.recover_state()

        # Should have logged critical alert
        assert any('UNEXPECTED POSITIONS IN IB' in record.message
                   for record in caplog.records)

    @pytest.mark.asyncio
    async def test_position_reconciliation_missing_position(
        self, mock_config, mock_state_manager, mock_order_executor, caplog
    ):
        """Test detection of missing position (in DB but not in IB)."""
        # DB has trade, IB doesn't have position
        db_trade = {
            'id': 'trade1',
            'setup_id': 'setup1',
            'symbol': 'NQ',
            'entry_price': 19500.0,
            'quantity': 1,
            'state': 'OPEN'
        }

        mock_order_executor.get_positions = AsyncMock(return_value=[])  # No IB positions
        mock_state_manager.get_open_trades = AsyncMock(return_value=[db_trade])

        engine = LiveTradingEngine(config=mock_config)
        engine.state_manager = mock_state_manager
        engine.order_executor = mock_order_executor
        engine.setup_tracker = Mock()
        engine.setup_tracker.restore_setup = AsyncMock()

        with caplog.at_level('WARNING'):
            await engine.recover_state()

        # Should have closed the trade in DB
        mock_state_manager.close_trade.assert_called_once_with(
            trade_id='trade1',
            exit_price=0.0,
            exit_reason='manual_close_detected'
        )

        # Should have logged warning
        assert any('closed externally' in record.message.lower()
                   for record in caplog.records)

    @pytest.mark.asyncio
    async def test_recovery_handles_missing_restore_setup_method(
        self, mock_config, mock_state_manager
    ):
        """Test graceful handling when setup_tracker lacks restore_setup()."""
        setup1 = {
            'id': 'setup1',
            'type': 'LIQ1',
            'state': 'WAITING_ENTRY'
        }

        mock_state_manager.get_active_setups = AsyncMock(return_value=[setup1])

        engine = LiveTradingEngine(config=mock_config)
        engine.state_manager = mock_state_manager
        engine.setup_tracker = Mock(spec=[])  # No restore_setup method
        engine.order_executor = Mock()
        engine.order_executor.get_positions = AsyncMock(return_value=[])

        # Should not raise exception
        try:
            await engine.recover_state()
            assert True
        except AttributeError:
            pytest.fail("Should handle missing restore_setup() gracefully")

    @pytest.mark.asyncio
    async def test_recovery_logs_summary(
        self, mock_config, mock_state_manager, caplog
    ):
        """Test that recovery logs a summary of recovered state."""
        setup1 = {'id': 'setup1', 'type': 'LIQ1'}
        setup2 = {'id': 'setup2', 'type': 'LIQ2'}

        trade1 = {'id': 'trade1', 'symbol': 'NQ'}
        trade2 = {'id': 'trade2', 'symbol': 'NQ'}

        mock_state_manager.get_active_setups = AsyncMock(
            return_value=[setup1, setup2]
        )
        mock_state_manager.get_open_trades = AsyncMock(
            return_value=[trade1, trade2]
        )

        engine = LiveTradingEngine(config=mock_config)
        engine.state_manager = mock_state_manager
        engine.setup_tracker = Mock()
        engine.setup_tracker.restore_setup = AsyncMock()
        engine.order_executor = Mock()
        engine.order_executor.get_positions = AsyncMock(return_value=[])

        with caplog.at_level('INFO'):
            await engine.recover_state()

        # Should have logged recovery info
        log_messages = [record.message for record in caplog.records]
        assert any('Recovering state' in msg for msg in log_messages)

    @pytest.mark.asyncio
    async def test_recovery_with_no_previous_state(
        self, mock_config, mock_state_manager
    ):
        """Test recovery when no previous state exists (clean start)."""
        mock_state_manager.get_active_setups = AsyncMock(return_value=[])
        mock_state_manager.get_open_trades = AsyncMock(return_value=[])

        engine = LiveTradingEngine(config=mock_config)
        engine.state_manager = mock_state_manager
        engine.setup_tracker = Mock()
        engine.setup_tracker.restore_setup = AsyncMock()
        engine.order_executor = Mock()
        engine.order_executor.get_positions = AsyncMock(return_value=[])

        # Should not raise exception
        try:
            await engine.recover_state()
            assert True
        except Exception as e:
            pytest.fail(f"Recovery with no state raised exception: {e}")

    @pytest.mark.asyncio
    async def test_recovery_resilience_to_corrupted_data(
        self, mock_config, mock_state_manager, caplog
    ):
        """Test that recovery handles corrupted data gracefully."""
        # Return invalid/corrupted setup data
        corrupted_setup = {'invalid': 'data', 'missing': 'required_fields'}

        mock_state_manager.get_active_setups = AsyncMock(
            return_value=[corrupted_setup]
        )
        mock_state_manager.get_open_trades = AsyncMock(return_value=[])

        engine = LiveTradingEngine(config=mock_config)
        engine.state_manager = mock_state_manager
        engine.setup_tracker = Mock()

        # Make restore_setup raise on invalid data
        engine.setup_tracker.restore_setup = AsyncMock(
            side_effect=ValueError("Invalid setup data")
        )

        engine.order_executor = Mock()
        engine.order_executor.get_positions = AsyncMock(return_value=[])

        # Should handle error gracefully
        with caplog.at_level('ERROR'):
            await engine.recover_state()

        # Should have logged error but not crashed
        assert any('error' in record.message.lower()
                   for record in caplog.records)


class TestStateManagerRecovery:
    """Test StateManager recovery methods"""

    @pytest.mark.asyncio
    async def test_get_active_setups_query(self):
        """Test get_active_setups() returns correct data."""
        from slob.live.state_manager import StateManager, StateManagerConfig
        import aiosqlite
        import tempfile

        # Create temporary database
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            # Create state manager
            config = StateManagerConfig(
                sqlite_db_path=db_path,
                redis_host='localhost'
            )
            manager = StateManager(config=config)
            await manager.initialize()

            # Insert test data
            async with aiosqlite.connect(db_path) as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS active_setups (
                        id TEXT PRIMARY KEY,
                        type TEXT,
                        state TEXT,
                        entry_price REAL,
                        created_at DATETIME
                    )
                """)
                await conn.execute("""
                    INSERT INTO active_setups VALUES
                    ('setup1', 'LIQ1', 'WAITING_ENTRY', 19500.0, datetime('now'))
                """)
                await conn.commit()

            # Test recovery
            if hasattr(manager, 'get_active_setups'):
                setups = await manager.get_active_setups()
                assert len(setups) > 0
                assert setups[0]['id'] == 'setup1'

            await manager.close()

        finally:
            Path(db_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_get_open_trades_query(self):
        """Test get_open_trades() returns correct data."""
        from slob.live.state_manager import StateManager, StateManagerConfig
        import aiosqlite
        import tempfile

        # Create temporary database
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            config = StateManagerConfig(
                sqlite_db_path=db_path,
                redis_host='localhost'
            )
            manager = StateManager(config=config)
            await manager.initialize()

            # Insert test data
            async with aiosqlite.connect(db_path) as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        id TEXT PRIMARY KEY,
                        setup_id TEXT,
                        symbol TEXT,
                        entry_price REAL,
                        state TEXT,
                        created_at DATETIME
                    )
                """)
                await conn.execute("""
                    INSERT INTO trades VALUES
                    ('trade1', 'setup1', 'NQ', 19500.0, 'OPEN', datetime('now'))
                """)
                await conn.commit()

            # Test recovery
            if hasattr(manager, 'get_open_trades'):
                trades = await manager.get_open_trades()
                assert len(trades) > 0
                assert trades[0]['id'] == 'trade1'
                assert trades[0]['symbol'] == 'NQ'

            await manager.close()

        finally:
            Path(db_path).unlink(missing_ok=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
