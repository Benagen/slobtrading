"""
Live Trading Engine

Main orchestrator for the live trading system.
Integrates all components: data fetching, buffering, aggregation, events, storage.
"""

import asyncio
import logging
import signal
from typing import List, Optional
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

# Optional IB support (only imported if used)
try:
    from .ib_ws_fetcher import IBWSFetcher
    IB_AVAILABLE = True
except ImportError:
    IB_AVAILABLE = False

logger = logging.getLogger(__name__)


class LiveTradingEngine:
    """
    Main live trading engine.

    Orchestrates all components:
    - WebSocket data fetching (AlpacaWSFetcher)
    - Tick buffering (TickBuffer)
    - Candle aggregation (CandleAggregator)
    - Event dispatch (EventBus)
    - Candle persistence (CandleStore)

    Week 1 Functionality:
    - Real-time data streaming
    - Candle generation and storage
    - Health monitoring
    - Graceful shutdown

    Week 2 Functionality:
    - Setup tracking (SetupTracker)
    - State persistence (StateManager)
    - Order execution (OrderExecutor)
    - Risk management

    Week 3 Will Add:
    - Docker deployment
    - Monitoring (Prometheus/Grafana)
    - Telegram alerts

    Usage:
        engine = LiveTradingEngine(
            api_key="YOUR_KEY",
            api_secret="YOUR_SECRET",
            symbols=["NQ"]
        )

        await engine.start()
        await engine.run()
    """

    def __init__(
        self,
        api_key: str = None,
        api_secret: str = None,
        symbols: List[str] = None,
        paper_trading: bool = True,
        db_path: str = "data/candles.db",
        state_db_path: str = "data/slob_state.db",
        data_source: str = 'alpaca',
        ib_host: str = '127.0.0.1',
        ib_port: int = 7497,
        ib_client_id: int = 1,
        ib_account: str = None,
        enable_trading: bool = True,
        redis_host: str = 'localhost',
        redis_port: int = 6379,
        account_balance: float = 100000.0,
        risk_per_trade: float = 0.01
    ):
        """
        Initialize live trading engine.

        Args:
            api_key: Alpaca API key (required if data_source='alpaca')
            api_secret: Alpaca API secret (required if data_source='alpaca')
            symbols: List of symbols to trade (e.g., ["NQ"])
            paper_trading: Use paper trading (default: True)
            db_path: Path to candle database
            state_db_path: Path to state database (SQLite)
            data_source: Data source ('alpaca' or 'ib')
            ib_host: IB Gateway/TWS host (if data_source='ib')
            ib_port: IB port (7497 TWS paper, 4002 Gateway paper)
            ib_client_id: IB client ID (1-999)
            ib_account: IB account (DU for paper, U for live)
            enable_trading: Enable order execution (False for dry-run)
            redis_host: Redis host for state storage
            redis_port: Redis port
            account_balance: Starting account balance
            risk_per_trade: Risk per trade (e.g., 0.01 = 1%)
        """
        self.data_source = data_source.lower()
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbols = symbols or ['NQ']
        self.paper_trading = paper_trading
        self.db_path = db_path
        self.state_db_path = state_db_path

        # Week 2 configuration
        self.enable_trading = enable_trading
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.account_balance = account_balance
        self.risk_per_trade = risk_per_trade

        # IB-specific
        self.ib_host = ib_host
        self.ib_port = ib_port
        self.ib_client_id = ib_client_id
        self.ib_account = ib_account

        # Validate configuration
        if self.data_source == 'alpaca':
            if not api_key or not api_secret:
                raise ValueError("api_key and api_secret required for Alpaca")
        elif self.data_source == 'ib':
            if not IB_AVAILABLE:
                raise ImportError(
                    "ib_insync not installed. Run: pip install ib_insync"
                )
        else:
            raise ValueError(f"Invalid data_source: {data_source}. Must be 'alpaca' or 'ib'")

        # Week 1 components (will be initialized in start())
        self.event_bus: Optional[EventBus] = None
        self.ws_fetcher = None  # AlpacaWSFetcher or IBWSFetcher
        self.tick_buffer: Optional[TickBuffer] = None
        self.candle_aggregator: Optional[CandleAggregator] = None
        self.candle_store: Optional[CandleStore] = None

        # Week 2 components
        self.setup_tracker: Optional[SetupTracker] = None
        self.state_manager: Optional[StateManager] = None
        self.order_executor: Optional[OrderExecutor] = None

        # State
        self.started_at: Optional[datetime] = None
        self.should_stop = False

        # Background tasks
        self.tasks: List[asyncio.Task] = []

        logger.info(
            f"LiveTradingEngine initialized "
            f"(data_source={self.data_source}, symbols={symbols}, paper={paper_trading})"
        )

    async def start(self):
        """
        Start the trading engine.

        Initializes all components and establishes connections.
        """
        logger.info("=" * 60)
        logger.info("STARTING LIVE TRADING ENGINE")
        logger.info("=" * 60)

        self.started_at = datetime.now()

        # Initialize EventBus
        logger.info("Initializing EventBus...")
        self.event_bus = EventBus(enable_history=True, max_history_size=1000)

        # Initialize CandleStore
        logger.info(f"Initializing CandleStore (db_path={self.db_path})...")
        self.candle_store = CandleStore(db_path=self.db_path)

        # Initialize CandleAggregator
        logger.info("Initializing CandleAggregator...")
        self.candle_aggregator = CandleAggregator(
            on_candle_complete=self._on_candle_complete
        )

        # Initialize TickBuffer
        logger.info("Initializing TickBuffer...")
        self.tick_buffer = TickBuffer(
            max_size=10000,
            ttl_seconds=60,
            on_overflow=self._on_tick_overflow
        )

        # Start auto-flush task
        flush_task = asyncio.create_task(self.tick_buffer.auto_flush(interval=10))
        self.tasks.append(flush_task)

        # Initialize data fetcher (Alpaca or IB)
        if self.data_source == 'alpaca':
            logger.info("Initializing AlpacaWSFetcher...")
            self.ws_fetcher = AlpacaWSFetcher(
                api_key=self.api_key,
                api_secret=self.api_secret,
                paper_trading=self.paper_trading,
                on_tick=self._on_tick,
                on_error=self._on_error
            )
            logger.info("Connecting to Alpaca WebSocket...")
            await self.ws_fetcher.connect()

        elif self.data_source == 'ib':
            logger.info("Initializing IBWSFetcher...")
            self.ws_fetcher = IBWSFetcher(
                host=self.ib_host,
                port=self.ib_port,
                client_id=self.ib_client_id,
                account=self.ib_account,
                paper_trading=self.paper_trading
            )
            self.ws_fetcher.on_tick = self._on_tick
            self.ws_fetcher.on_error = self._on_error

            logger.info(f"Connecting to IB at {self.ib_host}:{self.ib_port}...")
            await self.ws_fetcher.connect()

        # Subscribe to symbols
        logger.info(f"Subscribing to symbols: {self.symbols}")
        await self.ws_fetcher.subscribe(self.symbols)

        # Emit system event
        await self.event_bus.emit(
            EventType.WEBSOCKET_CONNECTED,
            {'symbols': self.symbols, 'paper': self.paper_trading}
        )

        # ─────────────────────────────────────────────────────────────
        # WEEK 2: Setup Tracking & Trading
        # ─────────────────────────────────────────────────────────────

        # Initialize StateManager
        logger.info("Initializing StateManager...")
        state_config = StateManagerConfig(
            redis_host=self.redis_host,
            redis_port=self.redis_port,
            sqlite_path=self.state_db_path,
            enable_redis=True
        )
        self.state_manager = StateManager(state_config)
        await self.state_manager.initialize()

        # Recover state from previous session (crash recovery)
        logger.info("Recovering state from previous session...")
        recovered_state = await self.state_manager.recover_state()
        logger.info(
            f"State recovered: {len(recovered_state['active_setups'])} active setups, "
            f"{len(recovered_state['open_trades'])} open trades"
        )

        # Initialize SetupTracker
        logger.info("Initializing SetupTracker...")
        tracker_config = SetupTrackerConfig(
            consol_min_duration=3,
            consol_max_duration=30,
            consol_min_quality=0.6,
            atr_multiplier_min=0.3,
            atr_multiplier_max=2.0,
            max_entry_wait_candles=10,
            max_retracement_pips=50.0
        )
        self.setup_tracker = SetupTracker(tracker_config)

        # Restore active setups from crash recovery
        if recovered_state['active_setups']:
            logger.info(f"Restoring {len(recovered_state['active_setups'])} active setups...")
            for setup in recovered_state['active_setups']:
                self.setup_tracker.active_candidates[setup.id] = setup

        # Initialize OrderExecutor (if trading enabled)
        if self.enable_trading:
            if self.data_source == 'ib':
                logger.info("Initializing OrderExecutor (IB)...")
                executor_config = OrderExecutorConfig(
                    host=self.ib_host,
                    port=self.ib_port,
                    client_id=self.ib_client_id + 1,  # Different client ID from data fetcher
                    account=self.ib_account,
                    paper_trading=self.paper_trading,
                    default_position_size=1,
                    max_position_size=5
                )
                self.order_executor = OrderExecutor(executor_config)
                await self.order_executor.initialize()
            else:
                logger.warning("OrderExecutor not implemented for Alpaca yet (IB only)")
        else:
            logger.info("Trading disabled - running in dry-run mode")

        # Initialize session for today
        from datetime import date
        today = date.today()
        session = await self.state_manager.get_session(today)
        if not session:
            logger.info(f"Initializing new trading session for {today}...")
            await self.state_manager.init_session(today, self.account_balance)

        logger.info("=" * 60)
        logger.info("✅ LIVE TRADING ENGINE STARTED (Week 1 + Week 2)")
        logger.info("=" * 60)

    async def run(self):
        """
        Main run loop.

        Processes tick stream and handles events.
        Runs until stopped.
        """
        logger.info("Starting main run loop...")

        try:
            # Start tick processor
            processor_task = asyncio.create_task(self._tick_processor())
            self.tasks.append(processor_task)

            # Start WebSocket listener
            listener_task = asyncio.create_task(self.ws_fetcher.listen())
            self.tasks.append(listener_task)

            # Start health monitor
            monitor_task = asyncio.create_task(self._health_monitor())
            self.tasks.append(monitor_task)

            # Wait for all tasks
            await asyncio.gather(*self.tasks, return_exceptions=True)

        except asyncio.CancelledError:
            logger.info("Run loop cancelled")

        except Exception as e:
            logger.error(f"Error in run loop: {e}", exc_info=True)
            await self._on_error(e)

        finally:
            if not self.should_stop:
                await self.shutdown()

    async def _on_tick(self, tick: Tick):
        """
        Handle incoming tick from WebSocket.

        Args:
            tick: Market tick data
        """
        # Enqueue tick for processing
        await self.tick_buffer.enqueue(tick)

        # Emit event
        await self.event_bus.emit(EventType.TICK_RECEIVED, tick)

    async def _tick_processor(self):
        """
        Background task to process ticks from buffer.

        Dequeues ticks and aggregates into candles.
        """
        logger.info("Tick processor started")

        while not self.should_stop:
            try:
                # Dequeue tick (with timeout to allow checking should_stop)
                tick = await self.tick_buffer.dequeue(timeout=1.0)

                if tick:
                    # Process tick through candle aggregator
                    await self.candle_aggregator.process_tick(tick)

            except asyncio.CancelledError:
                break

            except Exception as e:
                logger.error(f"Error processing tick: {e}", exc_info=True)

        logger.info("Tick processor stopped")

    async def _on_candle_complete(self, candle: Candle):
        """
        Handle completed candle.

        Week 1: Save to database
        Week 2: Process through SetupTracker

        Args:
            candle: Completed M1 candle
        """
        logger.info(f"Candle completed: {candle}")

        # Save to database
        try:
            self.candle_store.save_candle(candle)
        except Exception as e:
            logger.error(f"Failed to save candle: {e}")

        # Emit event
        await self.event_bus.emit(EventType.CANDLE_COMPLETED, candle)

        # ─────────────────────────────────────────────────────────────
        # WEEK 2: Process candle through SetupTracker
        # ─────────────────────────────────────────────────────────────
        if self.setup_tracker:
            try:
                # Convert Candle to dict format expected by SetupTracker
                candle_dict = {
                    'timestamp': candle.timestamp,
                    'open': candle.open,
                    'high': candle.high,
                    'low': candle.low,
                    'close': candle.close,
                    'volume': candle.volume
                }

                # Process candle
                await self.setup_tracker.on_candle(candle_dict)

                # Check for completed setups
                for setup in self.setup_tracker.completed_setups:
                    await self._on_setup_complete(setup)

                # Save active candidates to state manager
                for candidate in self.setup_tracker.active_candidates.values():
                    await self.state_manager.save_setup(candidate)

            except Exception as e:
                logger.error(f"Error processing candle through SetupTracker: {e}", exc_info=True)

    async def _on_setup_complete(self, setup: SetupCandidate):
        """
        Handle completed setup - place bracket order.

        Args:
            setup: Completed setup candidate
        """
        logger.info("=" * 60)
        logger.info(f"🎯 SETUP COMPLETE: {setup.id[:8]}")
        logger.info("=" * 60)
        logger.info(f"   Entry:  {setup.entry_price}")
        logger.info(f"   SL:     {setup.sl_price}")
        logger.info(f"   TP:     {setup.tp_price}")
        logger.info(f"   R:R:    {setup.risk_reward_ratio:.1f}")
        logger.info("=" * 60)

        # Save completed setup to database
        await self.state_manager.save_setup(setup)

        # Emit event
        await self.event_bus.emit(EventType.SETUP_DETECTED, setup)

        # Place order (if trading enabled)
        if self.enable_trading and self.order_executor:
            try:
                # Calculate position size based on risk
                position_size = self.order_executor.calculate_position_size(
                    account_balance=self.account_balance,
                    risk_per_trade=self.risk_per_trade,
                    entry_price=setup.entry_price,
                    stop_loss_price=setup.sl_price
                )

                logger.info(f"Placing bracket order: {position_size} contracts...")

                # Place bracket order
                order_result = await self.order_executor.place_bracket_order(
                    setup=setup,
                    position_size=position_size
                )

                if order_result.success:
                    logger.info(f"✅ Order placed successfully!")
                    logger.info(f"   Entry Order ID: {order_result.entry_order.order_id}")
                    logger.info(f"   SL Order ID: {order_result.stop_loss_order.order_id}")
                    logger.info(f"   TP Order ID: {order_result.take_profit_order.order_id}")

                    # Save trade to database
                    trade_data = {
                        'setup_id': setup.id,
                        'symbol': setup.symbol,
                        'entry_time': setup.entry_trigger_time.isoformat(),
                        'entry_price': setup.entry_price,
                        'position_size': position_size,
                        'sl_price': setup.sl_price,
                        'tp_price': setup.tp_price,
                        'result': 'OPEN'
                    }
                    await self.state_manager.persist_trade(trade_data)

                else:
                    logger.error(f"❌ Order placement failed: {order_result.error_message}")

            except Exception as e:
                logger.error(f"Error placing order: {e}", exc_info=True)
        else:
            logger.info("Trading disabled - order would be placed here")

    async def _on_tick_overflow(self, tick: Tick):
        """
        Handle tick buffer overflow.

        Args:
            tick: Tick that caused overflow
        """
        logger.warning(f"⚠️ Tick buffer overflow! Tick: {tick}")

    async def _on_error(self, error: Exception):
        """
        Handle system errors.

        Args:
            error: Exception that occurred
        """
        logger.error(f"System error: {error}", exc_info=True)

        # TODO: Send Telegram alert in Week 3

    async def _health_monitor(self):
        """
        Background task to monitor system health.

        Logs statistics every 60 seconds.
        """
        logger.info("Health monitor started")

        while not self.should_stop:
            try:
                await asyncio.sleep(60)

                if self.should_stop:
                    break

                # Log statistics
                logger.info("=" * 60)
                logger.info("SYSTEM HEALTH CHECK")
                logger.info("=" * 60)

                # Runtime
                runtime = datetime.now() - self.started_at
                logger.info(f"Runtime: {runtime}")

                # WebSocket stats
                ws_stats = self.ws_fetcher.get_stats()
                logger.info(f"WebSocket: {ws_stats}")

                # Buffer stats
                buffer_stats = self.tick_buffer.get_stats()
                logger.info(f"TickBuffer: {buffer_stats}")

                # Aggregator stats
                agg_stats = self.candle_aggregator.get_stats()
                logger.info(f"CandleAggregator: {agg_stats}")

                # Store stats
                store_stats = self.candle_store.get_stats()
                logger.info(f"CandleStore: {store_stats}")

                # EventBus stats
                event_stats = self.event_bus.get_stats()
                logger.info(f"EventBus: {event_stats}")

                # Week 2 stats
                if self.setup_tracker:
                    tracker_stats = self.setup_tracker.get_stats()
                    logger.info(f"SetupTracker: {tracker_stats}")

                if self.state_manager:
                    state_stats = self.state_manager.get_stats() if hasattr(self.state_manager, 'get_stats') else {'status': 'running'}
                    logger.info(f"StateManager: {state_stats}")

                if self.order_executor:
                    executor_stats = self.order_executor.get_stats()
                    logger.info(f"OrderExecutor: {executor_stats}")

                logger.info("=" * 60)

            except asyncio.CancelledError:
                break

            except Exception as e:
                logger.error(f"Error in health monitor: {e}", exc_info=True)

        logger.info("Health monitor stopped")

    async def shutdown(self):
        """
        Gracefully shutdown the trading engine.

        Stops all components and saves state.
        """
        if self.should_stop:
            return

        logger.info("=" * 60)
        logger.info("SHUTTING DOWN LIVE TRADING ENGINE")
        logger.info("=" * 60)

        self.should_stop = True

        # Cancel all background tasks
        logger.info("Cancelling background tasks...")
        for task in self.tasks:
            task.cancel()

        # Wait for tasks to finish
        await asyncio.gather(*self.tasks, return_exceptions=True)

        # Force complete all active candles
        if self.candle_aggregator:
            logger.info("Force completing active candles...")
            await self.candle_aggregator.force_complete_all()

        # Shutdown TickBuffer
        if self.tick_buffer:
            logger.info("Shutting down TickBuffer...")
            await self.tick_buffer.shutdown()

        # Disconnect WebSocket
        if self.ws_fetcher:
            logger.info("Disconnecting WebSocket...")
            await self.ws_fetcher.disconnect()

        # Shutdown EventBus
        if self.event_bus:
            logger.info("Shutting down EventBus...")
            await self.event_bus.shutdown()

        # Close database
        if self.candle_store:
            logger.info("Closing database...")
            self.candle_store.close()

        # Week 2 shutdown
        if self.order_executor:
            logger.info("Closing OrderExecutor...")
            await self.order_executor.close()

        if self.state_manager:
            logger.info("Closing StateManager...")
            await self.state_manager.close()

        # Final statistics
        logger.info("=" * 60)
        logger.info("FINAL STATISTICS")
        logger.info("=" * 60)

        runtime = datetime.now() - self.started_at
        logger.info(f"Total runtime: {runtime}")

        if self.ws_fetcher:
            logger.info(f"WebSocket: {self.ws_fetcher.get_stats()}")

        if self.candle_aggregator:
            logger.info(f"CandleAggregator: {self.candle_aggregator.get_stats()}")

        if self.candle_store:
            logger.info(f"CandleStore: {self.candle_store.get_stats()}")

        if self.setup_tracker:
            logger.info(f"SetupTracker: {self.setup_tracker.get_stats()}")

        if self.order_executor:
            logger.info(f"OrderExecutor: {self.order_executor.get_stats()}")

        logger.info("=" * 60)
        logger.info("✅ SHUTDOWN COMPLETE")
        logger.info("=" * 60)

    def setup_signal_handlers(self):
        """
        Setup signal handlers for graceful shutdown.

        Handles SIGINT (Ctrl+C) and SIGTERM.
        """
        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, initiating shutdown...")
            asyncio.create_task(self.shutdown())

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        logger.info("Signal handlers configured")


async def main():
    """
    Example main function for running the live trading engine.

    Usage:
        # IB (Interactive Brokers) - recommended for NQ futures
        python -m slob.live.live_trading_engine

        # Alpaca (stocks only)
        python -m slob.live.live_trading_engine --alpaca
    """
    import os
    import sys
    from dotenv import load_dotenv

    # Load environment variables
    load_dotenv()

    # Determine data source
    use_alpaca = '--alpaca' in sys.argv
    data_source = 'alpaca' if use_alpaca else 'ib'

    if data_source == 'alpaca':
        # Alpaca (stocks)
        api_key = os.getenv('ALPACA_API_KEY')
        api_secret = os.getenv('ALPACA_API_SECRET')

        if not api_key or not api_secret:
            logger.error("Missing Alpaca credentials in environment variables")
            return

        engine = LiveTradingEngine(
            api_key=api_key,
            api_secret=api_secret,
            symbols=["AAPL"],  # Example stock
            paper_trading=True,
            db_path="data/candles.db",
            state_db_path="data/slob_state.db",
            data_source='alpaca',
            enable_trading=False  # OrderExecutor not implemented for Alpaca yet
        )

    else:
        # Interactive Brokers (NQ futures)
        logger.info("Using Interactive Brokers for NQ futures")

        engine = LiveTradingEngine(
            symbols=["NQ"],  # NQ = Nasdaq 100 E-mini futures
            paper_trading=True,
            db_path="data/candles.db",
            state_db_path="data/slob_state.db",
            data_source='ib',
            ib_host='127.0.0.1',
            ib_port=7497,  # TWS paper trading (4002 for Gateway)
            ib_client_id=1,
            ib_account=os.getenv('IB_ACCOUNT', 'DU123456'),
            enable_trading=True,  # Enable IB trading
            account_balance=100000.0,
            risk_per_trade=0.01  # 1% risk per trade
        )

    # Setup signal handlers
    engine.setup_signal_handlers()

    # Start and run
    await engine.start()
    await engine.run()


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Run
    asyncio.run(main())
