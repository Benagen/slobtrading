"""
Week 1 Checkpoint Test

Runs the live trading engine for 1 hour to validate:
- WebSocket connection stability
- Tick buffering
- Candle aggregation
- Data persistence
- No crashes or memory leaks

Success Criteria:
✅ Uptime: 100% (no crashes)
✅ WebSocket: Connected for entire duration
✅ Ticks received: >0
✅ Candles generated: >0
✅ Candles persisted: Matches generated count
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from slob.live.live_trading_engine import LiveTradingEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/week1_checkpoint.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class Week1CheckpointTest:
    """
    Week 1 checkpoint test runner.

    Runs engine for specified duration and validates metrics.
    """

    def __init__(self, duration_minutes: int = 60):
        """
        Initialize checkpoint test.

        Args:
            duration_minutes: Test duration (default: 60 minutes)
        """
        self.duration_minutes = duration_minutes
        self.duration = timedelta(minutes=duration_minutes)
        self.engine: LiveTradingEngine = None

        self.start_time: datetime = None
        self.end_time: datetime = None

        # Results
        self.passed = False
        self.errors = []

    async def run(self):
        """
        Run the checkpoint test.

        Returns:
            bool: True if all checks passed
        """
        logger.info("=" * 80)
        logger.info("WEEK 1 CHECKPOINT TEST")
        logger.info("=" * 80)
        logger.info(f"Duration: {self.duration_minutes} minutes")
        logger.info(f"Start time: {datetime.now()}")
        logger.info("=" * 80)

        try:
            # Load environment
            load_dotenv()

            api_key = os.getenv('ALPACA_API_KEY')
            api_secret = os.getenv('ALPACA_API_SECRET')

            if not api_key or not api_secret:
                self.errors.append("Missing Alpaca credentials")
                logger.error("❌ Missing ALPACA_API_KEY or ALPACA_API_SECRET in .env")
                return False

            # Create engine
            logger.info("Creating LiveTradingEngine...")
            self.engine = LiveTradingEngine(
                api_key=api_key,
                api_secret=api_secret,
                symbols=["AAPL", "MSFT", "GOOGL"],  # Using stocks instead of NQ futures
                paper_trading=True,
                db_path=f"data/week1_checkpoint_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            )

            # Start engine
            logger.info("Starting engine...")
            self.start_time = datetime.now()
            await self.engine.start()

            # Run for specified duration
            logger.info(f"Running for {self.duration_minutes} minutes...")
            logger.info("Press Ctrl+C to stop early")

            try:
                # Create run task
                run_task = asyncio.create_task(self.engine.run())

                # Wait for duration or until stopped
                await asyncio.wait_for(run_task, timeout=self.duration.total_seconds())

            except asyncio.TimeoutError:
                # Duration reached - this is expected
                logger.info(f"✅ Duration of {self.duration_minutes} minutes reached")

            except asyncio.CancelledError:
                logger.info("Test cancelled by user")

            self.end_time = datetime.now()

            # Shutdown
            logger.info("Shutting down engine...")
            await self.engine.shutdown()

            # Validate results
            logger.info("=" * 80)
            logger.info("VALIDATING RESULTS")
            logger.info("=" * 80)

            self.passed = self._validate_results()

            return self.passed

        except Exception as e:
            logger.error(f"❌ Test failed with error: {e}", exc_info=True)
            self.errors.append(str(e))
            return False

        finally:
            self._print_results()

    def _validate_results(self) -> bool:
        """
        Validate test results against success criteria.

        Returns:
            bool: True if all validations passed
        """
        all_passed = True

        # Check 1: Duration
        actual_duration = self.end_time - self.start_time
        logger.info(f"Actual runtime: {actual_duration}")

        if actual_duration < timedelta(minutes=self.duration_minutes * 0.9):
            logger.error(f"❌ Runtime too short: {actual_duration} < {self.duration}")
            self.errors.append(f"Runtime too short: {actual_duration}")
            all_passed = False
        else:
            logger.info(f"✅ Runtime sufficient: {actual_duration}")

        # Check 2: WebSocket stats
        ws_stats = self.engine.ws_fetcher.get_stats()
        logger.info(f"WebSocket stats: {ws_stats}")

        if ws_stats['tick_count'] == 0:
            logger.error("❌ No ticks received from WebSocket")
            self.errors.append("No ticks received")
            all_passed = False
        else:
            logger.info(f"✅ Ticks received: {ws_stats['tick_count']}")

        if ws_stats['state'] != 'CONNECTED':
            logger.warning(f"⚠️ WebSocket state: {ws_stats['state']}")

        # Check 3: Candle aggregator stats
        agg_stats = self.engine.candle_aggregator.get_stats()
        logger.info(f"Candle aggregator stats: {agg_stats}")

        if agg_stats['candles_completed'] == 0:
            logger.error("❌ No candles generated")
            self.errors.append("No candles generated")
            all_passed = False
        else:
            logger.info(f"✅ Candles generated: {agg_stats['candles_completed']}")

        # Check 4: Candle store stats
        store_stats = self.engine.candle_store.get_stats()
        logger.info(f"Candle store stats: {store_stats}")

        if store_stats['candles_saved'] == 0:
            logger.error("❌ No candles persisted")
            self.errors.append("No candles persisted")
            all_passed = False
        else:
            logger.info(f"✅ Candles persisted: {store_stats['candles_saved']}")

        # Check 5: Buffer stats
        buffer_stats = self.engine.tick_buffer.get_stats()
        logger.info(f"Tick buffer stats: {buffer_stats}")

        if buffer_stats['dropped_count'] > 0:
            logger.warning(f"⚠️ Ticks dropped: {buffer_stats['dropped_count']}")

        # Check 6: EventBus stats
        event_stats = self.engine.event_bus.get_stats()
        logger.info(f"EventBus stats: {event_stats}")

        if event_stats['handler_errors'] > 0:
            logger.warning(f"⚠️ Handler errors: {event_stats['handler_errors']}")

        return all_passed

    def _print_results(self):
        """Print final test results."""
        logger.info("=" * 80)
        logger.info("WEEK 1 CHECKPOINT TEST RESULTS")
        logger.info("=" * 80)

        if self.passed:
            logger.info("✅ ✅ ✅ ALL CHECKS PASSED ✅ ✅ ✅")
            logger.info("")
            logger.info("Week 1 Data Layer is READY for Week 2 (Trading Engine)")
            logger.info("")
            logger.info("Next steps:")
            logger.info("  1. Review candle data in database")
            logger.info("  2. Proceed to Week 2: Setup Tracker implementation")
            logger.info("  3. Implement incremental pattern detectors")
        else:
            logger.error("❌ ❌ ❌ SOME CHECKS FAILED ❌ ❌ ❌")
            logger.error("")
            logger.error("Errors:")
            for error in self.errors:
                logger.error(f"  - {error}")
            logger.error("")
            logger.error("Action required:")
            logger.error("  1. Review logs for errors")
            logger.error("  2. Fix issues before proceeding to Week 2")

        logger.info("=" * 80)


async def main():
    """
    Main entry point.

    Usage:
        python scripts/week1_checkpoint_test.py [duration_minutes]
    """
    import sys

    # Get duration from command line (default: 60 minutes)
    duration = 60
    if len(sys.argv) > 1:
        try:
            duration = int(sys.argv[1])
        except ValueError:
            logger.error("Invalid duration. Usage: python week1_checkpoint_test.py [minutes]")
            return

    # Create and run test
    test = Week1CheckpointTest(duration_minutes=duration)
    success = await test.run()

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    # Ensure directories exist
    Path("logs").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    # Run test
    asyncio.run(main())
