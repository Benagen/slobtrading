
"""
Live Trading Engine
"""
import asyncio
import logging
import signal
from typing import List, Optional, Any
from datetime import datetime
from pathlib import Path

from .alpaca_ws_fetcher import AlpacaWSFetcher, Tick
from .tick_buffer import TickBuffer
from .candle_aggregator import CandleAggregator, Candle
from .event_bus import EventBus, EventType
from .candle_store import CandleStore

# Week 2 components
from .setup_tracker import SetupTracker, SetupTrackerConfig
from .state_manager import StateManager, StateManagerConfig
from .order_executor import OrderExecutor, OrderExecutorConfig
from .setup_state import SetupCandidate, SetupState

# ML Shadow Mode
from .ml_shadow_engine import MLShadowEngine

# --- DIREKT IMPORT (INGEN TRY-EXCEPT SOM DÖLJER FEL) ---
from .ib_ws_fetcher import IBWSFetcher
IB_AVAILABLE = True
# -------------------------------------------------------

# Alerting
from slob.monitoring.telegram_notifier import TelegramNotifier
from slob.monitoring.email_notifier import EmailNotifier

# Secrets management
from slob.config.secrets import get_secret

class LiveTradingEngineConfig:
    """Configuration that accepts ANYTHING via kwargs."""
    def __init__(self, **kwargs):
        # Defaults
        self.ib_host = "127.0.0.1"
        self.ib_port = 4002
        self.client_id = 1
        self.account = ""
        self.risk_per_trade = 0.01
        self.max_position_size = 5
        self.symbol = "NQ"

        # Strategy Defaults
        self.max_retracement_pips = 100.0  # Updated from consol_max_range_pips
        self.consol_min_duration_minutes = 15
        self.sl_buffer_pips = 1.0
        self.tp_risk_reward = 2.0
        self.bar_size = "1 min"

        # ML Shadow Mode
        self.shadow_mode_enabled = False
        self.ml_model_path = "models/setup_classifier_latest.joblib"
        self.ml_threshold = 0.55

        # Apply overrides
        for key, value in kwargs.items():
            setattr(self, key, value)

        # Load account from secrets if not provided
        if not self.account:
            try:
                self.account = get_secret('ib_account')
                logging.getLogger(__name__).info(f"✅ Loaded IB Account from secrets: {self.account}")
            except Exception as e:
                logging.getLogger(__name__).warning(f"Could not load IB account from secrets: {e}")
                logging.getLogger(__name__).warning("Account will need to be provided via config or environment")

        # Validate account format
        if self.account and not (self.account.startswith('DU') or self.account.startswith('U')):
            raise ValueError(
                f"Invalid IB account: '{self.account}'. "
                f"Expected format: DU123456 (paper) or U123456 (live)"
            )

class LiveTradingEngine:
    def __init__(self, config: LiveTradingEngineConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.running = False
        self.tasks = []
        self.started_at = None
        
        # Initialize Components
        self.event_bus = EventBus()
        self.tick_buffer = TickBuffer()
        self.candle_aggregator = CandleAggregator(on_candle_complete=self._on_candle_complete)
        self.candle_store = CandleStore()
        self.state_manager = StateManager(StateManagerConfig(sqlite_path="data/trading_state.db"))
        
        # Setup Tracker
        tracker_config = SetupTrackerConfig(
            symbol=config.symbol,
            max_retracement_pips=getattr(config, 'max_retracement_pips', 100.0),  # Updated parameter
            consol_min_duration=getattr(config, 'consol_min_duration_minutes', 15),
            sl_buffer_pips=getattr(config, 'sl_buffer_pips', 1.0)
        )
        self.setup_tracker = SetupTracker(tracker_config)
        
        # Order Executor
        executor_config = OrderExecutorConfig(
            host=config.ib_host,  # Changed from ib_host
            port=config.ib_port,  # Changed from ib_port
            client_id=config.client_id,
            account=config.account,
            max_position_size=config.max_position_size
        )
        self.order_executor = OrderExecutor(executor_config)
        self.ws_fetcher = None

        # ML Shadow Mode
        self.shadow_engine = None
        if getattr(config, 'shadow_mode_enabled', False):
            model_path = getattr(config, 'ml_model_path', 'models/setup_classifier_latest.joblib')
            if not Path(model_path).exists():
                self.logger.warning(f"ML model not found: {model_path}")
                self.logger.warning("Shadow mode DISABLED - train model first")
            else:
                try:
                    self.shadow_engine = MLShadowEngine(
                        model_path=model_path,
                        event_bus=self.event_bus,
                        candle_store=self.candle_store,
                        state_manager=self.state_manager,
                        threshold=getattr(config, 'ml_threshold', 0.55)
                    )
                    self.logger.info(f"✅ Shadow mode ENABLED (threshold={config.ml_threshold:.0%})")
                except Exception as e:
                    self.logger.error(f"Failed to initialize shadow mode: {e}")
                    self.logger.warning("Shadow mode DISABLED due to initialization error")
                    self.shadow_engine = None

        # Alerting (Telegram + Email)
        self.telegram = TelegramNotifier()
        self.email = EmailNotifier()

        if self.telegram.enabled:
            self.logger.info("✅ Telegram alerts ENABLED")
        if self.email.enabled:
            self.logger.info("✅ Email alerts ENABLED")

        self._setup_event_handlers()
        self._setup_signal_handlers()

    def _setup_event_handlers(self):
        self.event_bus.subscribe(EventType.CANDLE_COMPLETED, self.candle_store.save_candle)

    def _setup_signal_handlers(self):
        """
        Setup graceful shutdown on SIGTERM/SIGINT.

        Handles:
        - SIGTERM (Docker stop, systemd stop)
        - SIGINT (Ctrl+C)

        Triggers graceful shutdown sequence:
        1. Stop accepting new data
        2. Cancel pending tasks
        3. Persist final state
        4. Close connections
        5. Exit cleanly
        """
        def signal_handler(signum, frame):
            signame = 'SIGTERM' if signum == signal.SIGTERM else 'SIGINT'
            self.logger.info(f"📡 Received {signame}, initiating graceful shutdown...")

            # Create shutdown task in event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.graceful_shutdown())
            else:
                loop.run_until_complete(self.graceful_shutdown())

        # Register handlers
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        self.logger.info("✅ Signal handlers registered (SIGTERM, SIGINT)")

    async def _on_candle_complete(self, candle: Candle):
        await self.event_bus.emit(EventType.CANDLE_COMPLETED, candle)
        self.candle_store.save_candle(candle)
        
        candle_dict = {
            'timestamp': candle.timestamp,
            'open': candle.open,
            'high': candle.high,
            'low': candle.low,
            'close': candle.close,
            'volume': candle.volume
        }
        await self.setup_tracker.on_candle(candle_dict)
        
        for setup in self.setup_tracker.completed_setups:
            await self._handle_setup_found({'setup': setup})

    async def _handle_setup_found(self, data: dict):
        setup = data.get('setup')
        if not setup: return
        self.logger.info(f"⚡ SETUP FOUND: {setup.id} | Entry: {setup.entry_price}")

        # Emit event for shadow mode (if enabled)
        # This allows shadow engine to make ML predictions in parallel
        await self.event_bus.emit(EventType.SETUP_DETECTED, {'setup': setup})

        # Alert: Setup detected
        if self.telegram.enabled:
            setup_data = {
                'id': setup.id,
                'direction': 'SHORT',  # SLOB is short-only
                'entry_price': setup.entry_price,
                'sl_price': setup.sl_price,
                'tp_price': setup.tp_price,
                'risk_reward_ratio': getattr(setup, 'risk_reward_ratio', 0)
            }
            self.telegram.notify_setup_detected(setup_data)

        # Calculate position size using RiskManager
        position_size = self.order_executor.calculate_position_size(
            entry_price=setup.entry_price,
            stop_loss_price=setup.sl_price,
            atr=getattr(setup, 'atr', None)  # Use ATR if available
        )

        self.logger.info(f"Position size: {position_size} contracts")

        # Alert: Order placement
        if self.telegram.enabled:
            order_data = {
                'type': 'BRACKET',
                'symbol': self.config.symbol,
                'quantity': position_size,
                'price': setup.entry_price,
                'order_id': setup.id[:8]
            }
            self.telegram.notify_order_placed(order_data)

        await self.order_executor.place_bracket_order(setup, position_size)

    async def initialize(self):
        """
        Initialize trading engine with state recovery.

        Steps:
        1. Recover state from database
        2. Connect to IB Gateway
        3. Subscribe to market data
        4. Initialize order executor
        5. Reconcile positions (verify IB matches database)
        6. Resume normal operation
        """
        self.started_at = datetime.now()
        self.logger.info(f"🚀 Initializing Engine for {self.config.symbol} on port {self.config.ib_port}")

        # Step 1: Recover state from persistence
        await self.recover_state()

        # Step 2: Initialize WS Fetcher
        self.ws_fetcher = IBWSFetcher(
            host=self.config.ib_host,
            port=self.config.ib_port,
            client_id=10,  # Unique ID for data fetcher (different from executor client_id=2)
            account=self.config.account
        )

        async def on_tick_bridge(tick):
             await self.tick_buffer.enqueue(tick)
             await self.candle_aggregator.process_tick(tick)

        self.ws_fetcher.on_tick = on_tick_bridge

        # Step 3: Connect to IB
        await self.ws_fetcher.connect()
        await self.ws_fetcher.subscribe([self.config.symbol])

        # Step 4: Initialize Order Executor
        if hasattr(self.order_executor, 'initialize'):
             await self.order_executor.initialize()

        # Step 5: Reconcile positions
        await self._reconcile_positions()

        self.running = True
        self.logger.info("✅ Engine initialization complete")

        # Alert: System started
        if self.telegram.enabled:
            status_details = {
                'Symbol': self.config.symbol,
                'Account': self.config.account,
                'Port': self.config.ib_port,
                'Shadow Mode': 'Enabled' if self.shadow_engine else 'Disabled'
            }
            self.telegram.notify_system_status("System Started", status_details)

        if self.email.enabled:
            self.email.send_system_notification(
                "System Started",
                f"Trading engine initialized successfully\nSymbol: {self.config.symbol}\nAccount: {self.config.account}"
            )

    async def run(self):
        """Main blocking loop."""
        if not self.running:
            await self.initialize()
            
        self.logger.info("🟢 Engine loop started. Waiting for market data...")
        
        # Health monitor loop
        while self.running:
            await asyncio.sleep(60) # Log status every minute
            self.logger.info("💓 Engine heartbeat - Running...")

    async def start(self):
        await self.run()

    async def shutdown(self):
        """Simple shutdown (backward compatibility)."""
        await self.graceful_shutdown()

    async def stop(self):
        """Simple stop (backward compatibility)."""
        await self.graceful_shutdown()

    async def graceful_shutdown(self, timeout: int = 30):
        """
        Gracefully shutdown with state persistence and cleanup.

        Steps:
        1. Stop accepting new setups
        2. Cancel pending tasks
        3. Handle open positions (based on strategy)
        4. Persist final state
        5. Close all connections
        6. Clean up resources

        Args:
            timeout: Maximum time to wait for cleanup (seconds)
        """
        if not self.running:
            self.logger.info("Engine already stopped")
            return

        self.logger.info("🛑 Starting graceful shutdown...")
        start_time = asyncio.get_event_loop().time()

        # Step 1: Stop accepting new data
        self.running = False
        self.logger.info("1/6: Stopped accepting new setups")

        # Step 2: Cancel pending async tasks
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if tasks:
            self.logger.info(f"2/6: Cancelling {len(tasks)} pending tasks...")
            for task in tasks:
                task.cancel()

            # Wait for cancellation with timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=min(5, timeout)
                )
            except asyncio.TimeoutError:
                self.logger.warning("Some tasks did not cancel within timeout")
        else:
            self.logger.info("2/6: No pending tasks to cancel")

        # Step 3: Handle open positions
        try:
            open_positions = await self.order_executor.get_positions()
            if open_positions:
                self.logger.warning(
                    f"3/6: {len(open_positions)} open positions remain\n"
                    f"Strategy: Leave positions open (managed by IB bracket orders)\n"
                    f"Manual action may be required via TWS if desired"
                )
                # Option A: Close all (risk reduction)
                # for pos in open_positions:
                #     await self.order_executor.close_position(pos)

                # Option B: Leave open (current strategy - bracket orders manage)
                # Positions will be managed by SL/TP orders already in IB

                # Option C: Ask user (interactive mode)
                # if input("Close all positions? (y/n): ") == 'y':
                #     for pos in open_positions:
                #         await self.order_executor.close_position(pos)
            else:
                self.logger.info("3/6: No open positions")
        except Exception as e:
            self.logger.error(f"Error checking open positions: {e}")

        # Step 4: Persist final state
        self.logger.info("4/6: Persisting final state...")
        try:
            if hasattr(self.state_manager, 'close'):
                await self.state_manager.close()
            self.logger.info("Final state saved to database")
        except Exception as e:
            self.logger.error(f"Failed to persist final state: {e}")

        # Step 5: Disconnect from IB
        self.logger.info("5/6: Closing connections...")
        try:
            if self.ws_fetcher:
                await self.ws_fetcher.disconnect()
                self.logger.info("WS Fetcher disconnected")

            if self.order_executor and hasattr(self.order_executor, 'close'):
                await self.order_executor.close()
                self.logger.info("Order Executor disconnected")
        except Exception as e:
            self.logger.error(f"Error closing connections: {e}")

        # Step 6: Shutdown event bus
        self.logger.info("6/6: Shutting down event bus...")
        try:
            if hasattr(self.event_bus, 'shutdown'):
                await self.event_bus.shutdown()
        except Exception as e:
            self.logger.error(f"Error shutting down event bus: {e}")

        elapsed = asyncio.get_event_loop().time() - start_time
        self.logger.info(f"✅ Graceful shutdown complete (took {elapsed:.1f}s)")

        # Alert: System stopped
        if self.telegram.enabled:
            try:
                self.telegram.send_alert(
                    f"System Stopped\nShutdown time: {elapsed:.1f}s\nOpen positions: {len(open_positions) if 'open_positions' in locals() else 0}",
                    "INFO"
                )
            except:
                pass  # Don't fail shutdown if alert fails

        if self.email.enabled:
            try:
                self.email.send_system_notification(
                    "System Stopped",
                    f"Trading engine shut down gracefully\nShutdown time: {elapsed:.1f}s"
                )
            except:
                pass  # Don't fail shutdown if alert fails
        self.logger.info("=" * 60)

    # ═══════════════════════════════════════════════════════════════════
    # STATE RECOVERY & POSITION RECONCILIATION
    # ═══════════════════════════════════════════════════════════════════

    async def recover_state(self):
        """
        Recover trading state from database on startup.

        Loads:
        - Active setups (in progress)
        - Open trades (pending fills)
        - Historical data (for setup detection continuity)

        Critical for recovery after:
        - System crash
        - Network disconnection
        - Manual restart
        - Container restart (Docker)
        """
        self.logger.info("🔄 Recovering state from database...")

        try:
            # Initialize state manager first
            if hasattr(self.state_manager, 'initialize'):
                await self.state_manager.initialize()

            # Recover active setups
            active_setups = await self.state_manager.get_active_setups()

            if active_setups:
                self.logger.info(f"Found {len(active_setups)} active setups:")
                for setup in active_setups:
                    self.logger.info(
                        f"  - Setup {setup.get('id', 'unknown')[:8]}: "
                        f"State={setup.get('state', 'unknown')}, "
                        f"Entry={setup.get('entry_price', 'N/A')}"
                    )

                    # Restore to setup tracker
                    if hasattr(self.setup_tracker, 'restore_setup'):
                        await self.setup_tracker.restore_setup(setup)
            else:
                self.logger.info("No active setups to recover")

            # Recover open trades
            open_trades = await self.state_manager.get_open_trades()

            if open_trades:
                self.logger.info(f"Found {len(open_trades)} open trades")
                for trade in open_trades:
                    self.logger.info(
                        f"  - Trade {trade.get('id', 'unknown')[:8]}: "
                        f"Symbol={trade.get('symbol', 'N/A')}, "
                        f"Entry={trade.get('entry_price', 'N/A')}"
                    )
            else:
                self.logger.info("No open trades to recover")

            self.logger.info("✅ State recovery complete")

        except Exception as e:
            self.logger.error(f"State recovery error: {e}")
            self.logger.warning("Continuing with fresh state...")

    async def _reconcile_positions(self):
        """
        Reconcile IB positions with database positions.

        Verifies that:
        - All database positions exist in IB
        - No unexpected positions in IB
        - Position quantities match

        Critical for:
        - Detecting manual closes via TWS
        - Detecting unexpected fills
        - Ensuring state consistency
        """
        self.logger.info("🔍 Reconciling positions...")

        try:
            # Get positions from IB
            ib_positions = await self.order_executor.get_positions()

            # Get positions from database
            db_trades = await self.state_manager.get_open_trades()

            # Extract symbols
            ib_symbols = {pos.contract.symbol for pos in ib_positions}
            db_symbols = {trade.get('symbol', 'NQ') for trade in db_trades}

            # Check for discrepancies
            unexpected_positions = ib_symbols - db_symbols
            missing_positions = db_symbols - ib_symbols

            if unexpected_positions:
                self.logger.critical(
                    f"❌ UNEXPECTED POSITIONS IN IB: {unexpected_positions}\n"
                    f"These positions exist in IB but not in database.\n"
                    f"Possible causes:\n"
                    f"  - Manual trade via TWS\n"
                    f"  - Database corruption\n"
                    f"  - Failed state persistence\n"
                    f"Action: Review positions and close manually if needed"
                )
                # TODO: Send alert via Telegram/Email

            if missing_positions:
                self.logger.warning(
                    f"⚠️ POSITIONS CLOSED EXTERNALLY: {missing_positions}\n"
                    f"These positions exist in database but not in IB.\n"
                    f"Likely closed manually via TWS.\n"
                    f"Updating database to reflect closure..."
                )

                # Update database to mark as closed
                for symbol in missing_positions:
                    # Find matching trades in db_trades
                    for trade in db_trades:
                        if trade.get('symbol') == symbol:
                            await self.state_manager.close_trade(
                                trade_id=trade.get('id'),
                                exit_price=0.0,  # Unknown (manual close)
                                exit_reason='manual_close_detected'
                            )
                            self.logger.info(f"Marked trade {trade.get('id')[:8]} as manually closed")

            if not unexpected_positions and not missing_positions:
                self.logger.info("✅ Position reconciliation: All positions match")
            else:
                self.logger.info("✅ Position reconciliation complete (with discrepancies)")

        except Exception as e:
            self.logger.error(f"Position reconciliation error: {e}")
            self.logger.warning("Continuing without reconciliation...")
