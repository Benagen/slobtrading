"""
IB Checkpoint Test

Tests IB WebSocket fetcher with real NQ futures data.

Requirements:
1. IB Gateway or TWS running on localhost
2. Paper trading account (DU number)
3. API enabled in TWS settings
4. CME market data subscription

Usage:
    python scripts/ib_checkpoint_test.py [duration_minutes] [account]

Example:
    python scripts/ib_checkpoint_test.py 60 DU123456
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from slob.live.live_trading_engine import LiveTradingEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/ib_checkpoint.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class IBCheckpointTest:
    """
    IB checkpoint test runner.

    Validates IB integration with NQ futures.
    """

    def __init__(self, duration_minutes: int = 60, ib_account: str = None):
        """
        Initialize checkpoint test.

        Args:
            duration_minutes: Test duration (default: 60 minutes)
            ib_account: IB paper trading account (DU number)
        """
        self.duration_minutes = duration_minutes
        self.duration = timedelta(minutes=duration_minutes)
        self.ib_account = ib_account
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
        logger.info("IB CHECKPOINT TEST - NQ FUTURES")
        logger.info("=" * 80)
        logger.info(f"Duration: {self.duration_minutes} minutes")
        logger.info(f"Start time: {datetime.now()}")
        logger.info(f"Account: {self.ib_account}")
        logger.info("=" * 80)

        try:
            # Create engine with IB
            logger.info("Creating LiveTradingEngine with IB...")
            self.engine = LiveTradingEngine(
                data_source='ib',
                ib_host='127.0.0.1',
                ib_port=7497,  # TWS paper trading
                ib_client_id=1,
                ib_account=self.ib_account,
                symbols=['NQ'],
                paper_trading=True,
                db_path=f"data/ib_checkpoint_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
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

        # Check 2: IB connection stats
        ws_stats = self.engine.ws_fetcher.get_stats()
        logger.info(f"IB stats: {ws_stats}")

        if ws_stats['tick_count'] == 0:
            logger.error("❌ No ticks received from IB")
            self.errors.append("No ticks received - check CME subscription")
            all_passed = False
        else:
            logger.info(f"✅ Ticks received: {ws_stats['tick_count']}")

        if ws_stats['state'] != 'CONNECTED':
            logger.warning(f"⚠️ IB state: {ws_stats['state']}")

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

        return all_passed

    def _print_results(self):
        """Print final test results."""
        logger.info("=" * 80)
        logger.info("IB CHECKPOINT TEST RESULTS")
        logger.info("=" * 80)

        if self.passed:
            logger.info("✅ ✅ ✅ ALL CHECKS PASSED ✅ ✅ ✅")
            logger.info("")
            logger.info("IB integration is READY for NQ futures trading!")
            logger.info("")
            logger.info("Next steps:")
            logger.info("  1. Review NQ candle data in database")
            logger.info("  2. Run 30-day paper trading validation")
            logger.info("  3. Proceed with SetupTracker integration")
        else:
            logger.error("❌ ❌ ❌ SOME CHECKS FAILED ❌ ❌ ❌")
            logger.error("")
            logger.error("Errors:")
            for error in self.errors:
                logger.error(f"  - {error}")
            logger.error("")
            logger.error("Common issues:")
            logger.error("  - TWS/Gateway not running (check localhost:7497)")
            logger.error("  - CME market data not subscribed")
            logger.error("  - API not enabled in TWS settings")
            logger.error("  - Wrong account number")

        logger.info("=" * 80)


async def main():
    """
    Main entry point.

    Usage:
        python scripts/ib_checkpoint_test.py [duration_minutes] [account]
    """
    import sys

    # Get duration from command line (default: 60 minutes)
    duration = 60
    account = None

    if len(sys.argv) > 1:
        try:
            duration = int(sys.argv[1])
        except ValueError:
            logger.error("Invalid duration. Usage: python ib_checkpoint_test.py [minutes] [account]")
            return

    if len(sys.argv) > 2:
        account = sys.argv[2]

    if not account:
        logger.warning("No IB account specified. Using None (will use default account)")
        logger.warning("Recommended: python ib_checkpoint_test.py 60 DU123456")

    # Create and run test
    test = IBCheckpointTest(duration_minutes=duration, ib_account=account)
    success = await test.run()

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    # Ensure directories exist
    Path("logs").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    # Run test
    asyncio.run(main())
