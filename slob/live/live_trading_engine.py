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

    Week 2+ Will Add:
    - Setup tracking
    - Order execution
    - Position management
    - Risk management

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
        api_key: str,
        api_secret: str,
        symbols: List[str],
        paper_trading: bool = True,
        db_path: str = "data/candles.db"
    ):
        """
        Initialize live trading engine.

        Args:
            api_key: Alpaca API key
            api_secret: Alpaca API secret
            symbols: List of symbols to trade (e.g., ["NQ"])
            paper_trading: Use paper trading (default: True)
            db_path: Path to candle database
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbols = symbols
        self.paper_trading = paper_trading
        self.db_path = db_path

        # Components (will be initialized in start())
        self.event_bus: Optional[EventBus] = None
        self.ws_fetcher: Optional[AlpacaWSFetcher] = None
        self.tick_buffer: Optional[TickBuffer] = None
        self.candle_aggregator: Optional[CandleAggregator] = None
        self.candle_store: Optional[CandleStore] = None

        # State
        self.started_at: Optional[datetime] = None
        self.should_stop = False

        # Background tasks
        self.tasks: List[asyncio.Task] = []

        logger.info(
            f"LiveTradingEngine initialized "
            f"(symbols={symbols}, paper={paper_trading})"
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

        # Initialize AlpacaWSFetcher
        logger.info("Initializing AlpacaWSFetcher...")
        self.ws_fetcher = AlpacaWSFetcher(
            api_key=self.api_key,
            api_secret=self.api_secret,
            paper_trading=self.paper_trading,
            on_tick=self._on_tick,
            on_error=self._on_error
        )

        # Connect to WebSocket
        logger.info("Connecting to Alpaca WebSocket...")
        await self.ws_fetcher.connect()

        # Subscribe to symbols
        logger.info(f"Subscribing to symbols: {self.symbols}")
        await self.ws_fetcher.subscribe(self.symbols)

        # Emit system event
        await self.event_bus.emit(
            EventType.WEBSOCKET_CONNECTED,
            {'symbols': self.symbols, 'paper': self.paper_trading}
        )

        logger.info("=" * 60)
        logger.info("✅ LIVE TRADING ENGINE STARTED")
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
        python -m slob.live.live_trading_engine
    """
    import os
    from dotenv import load_dotenv

    # Load environment variables
    load_dotenv()

    # Get Alpaca credentials
    api_key = os.getenv('ALPACA_API_KEY')
    api_secret = os.getenv('ALPACA_API_SECRET')

    if not api_key or not api_secret:
        logger.error("Missing Alpaca credentials in environment variables")
        return

    # Create engine
    engine = LiveTradingEngine(
        api_key=api_key,
        api_secret=api_secret,
        symbols=["NQ"],  # NQ = Nasdaq 100 E-mini futures
        paper_trading=True,
        db_path="data/candles.db"
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
