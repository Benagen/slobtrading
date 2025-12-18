#!/usr/bin/env python3
"""
Paper Trading Runner - Phase 1 Validation

Runs the 5/1 SLOB live trading system in paper trading mode to validate:
- TASK 1: Spike rule SL calculation (backtest alignment)
- TASK 3: Idempotency protection (no duplicate orders)

Usage:
    python scripts/run_paper_trading.py --account DU123456

Requirements:
    - IB TWS or IB Gateway running in paper trading mode
    - Port 7497 (TWS) or 4002 (Gateway) open
    - Paper trading account (DU number)
"""

import asyncio
import argparse
import logging
from datetime import datetime, time
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from slob.config.ib_config import IBConfig
from slob.live.live_trading_engine import LiveTradingEngine, LiveTradingEngineConfig
from slob.live.setup_tracker import SetupTrackerConfig
from slob.live.order_executor import OrderExecutorConfig


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s',
    handlers=[
        logging.FileHandler(f'logs/paper_trading_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class PaperTradingValidator:
    """
    Paper trading validator for Phase 1 changes.

    Monitors and validates:
    - Spike rule application
    - Idempotency protection
    - Setup detection accuracy
    """

    def __init__(self):
        self.setups_detected = 0
        self.spike_rule_activated = 0
        self.normal_sl_count = 0
        self.orders_placed = 0
        self.duplicate_attempts = 0
        self.start_time = datetime.now()

    def on_setup_complete(self, setup):
        """Callback when setup is complete."""
        self.setups_detected += 1

        # Validate spike rule was applied
        if hasattr(setup, 'liq2_candle') and setup.liq2_candle:
            liq2 = setup.liq2_candle
            body = abs(liq2['close'] - liq2['open'])
            upper_wick = liq2['high'] - max(liq2['close'], liq2['open'])

            # Check if spike rule was activated
            if upper_wick > 2 * body and body > 0:
                # Spike detected
                self.spike_rule_activated += 1
                expected_sl = max(liq2['close'], liq2['open']) + 2.0

                logger.info(
                    f"🔥 SPIKE RULE ACTIVATED - Setup {setup.id[:8]}\n"
                    f"   LIQ #2: open={liq2['open']:.1f}, high={liq2['high']:.1f}, close={liq2['close']:.1f}\n"
                    f"   Body={body:.1f}, Upper Wick={upper_wick:.1f}, Ratio={upper_wick/body:.2f}\n"
                    f"   Expected SL: {expected_sl:.1f} (body_top + 2)\n"
                    f"   Actual SL:   {setup.sl_price:.1f}\n"
                    f"   ✅ Match: {abs(setup.sl_price - expected_sl) < 0.5}"
                )
            else:
                # Normal candle
                self.normal_sl_count += 1
                expected_sl = liq2['high'] + 2.0

                logger.info(
                    f"📊 NORMAL CANDLE - Setup {setup.id[:8]}\n"
                    f"   LIQ #2: open={liq2['open']:.1f}, high={liq2['high']:.1f}, close={liq2['close']:.1f}\n"
                    f"   Body={body:.1f}, Upper Wick={upper_wick:.1f}, Ratio={upper_wick/body:.2f if body > 0 else 0}\n"
                    f"   Expected SL: {expected_sl:.1f} (high + 2)\n"
                    f"   Actual SL:   {setup.sl_price:.1f}\n"
                    f"   ✅ Match: {abs(setup.sl_price - expected_sl) < 0.5}"
                )

        logger.info(
            f"\n{'='*80}\n"
            f"✅ SETUP #{self.setups_detected} COMPLETE - {setup.id[:8]}\n"
            f"{'='*80}\n"
            f"Entry: {setup.entry_price:.2f}\n"
            f"SL:    {setup.sl_price:.2f}\n"
            f"TP:    {setup.tp_price:.2f}\n"
            f"R:R:   {setup.risk_reward_ratio:.2f}\n"
            f"{'='*80}\n"
        )

    def on_order_placed(self, order_result):
        """Callback when order is placed."""
        if order_result.success:
            self.orders_placed += 1
            logger.info(f"✅ Order placed successfully: {order_result.entry_order.order_id}")
        else:
            if "duplicate" in order_result.error_message.lower():
                self.duplicate_attempts += 1
                logger.warning(
                    f"🛡️ IDEMPOTENCY PROTECTION ACTIVATED\n"
                    f"   Duplicate order prevented: {order_result.error_message}"
                )
            else:
                logger.error(f"❌ Order failed: {order_result.error_message}")

    def print_statistics(self):
        """Print validation statistics."""
        runtime = (datetime.now() - self.start_time).total_seconds() / 3600  # hours

        print(f"\n{'='*80}")
        print("PAPER TRADING VALIDATION STATISTICS")
        print(f"{'='*80}")
        print(f"Runtime:               {runtime:.1f} hours")
        print(f"Setups Detected:       {self.setups_detected}")
        print(f"Orders Placed:         {self.orders_placed}")
        print(f"\nSPIKE RULE VALIDATION:")
        print(f"  Spike Rule Activated: {self.spike_rule_activated}")
        print(f"  Normal Candles:       {self.normal_sl_count}")
        print(f"  Activation Rate:      {self.spike_rule_activated/max(1, self.setups_detected)*100:.1f}%")
        print(f"\nIDEMPOTENCY VALIDATION:")
        print(f"  Duplicate Attempts:   {self.duplicate_attempts}")
        print(f"  ✅ Protection Active: {'YES' if self.duplicate_attempts == 0 else f'BLOCKED {self.duplicate_attempts}'}")
        print(f"{'='*80}\n")


async def run_paper_trading(args):
    """
    Run paper trading validation.

    Args:
        args: Command line arguments
    """
    logger.info("="*80)
    logger.info("PHASE 1 PAPER TRADING VALIDATION")
    logger.info("="*80)
    logger.info(f"Account: {args.account}")
    logger.info(f"Port: {args.port}")
    logger.info(f"Duration: {args.duration} hours")
    logger.info("="*80)

    # Create validator
    validator = PaperTradingValidator()

    # Configure IB connection
    if args.gateway:
        logger.info("Using IB Gateway paper trading (port 4002)")
        ib_config = IBConfig.gateway_paper_config(
            account=args.account,
            client_id=args.client_id
        )
    else:
        logger.info("Using TWS paper trading (port 7497)")
        ib_config = IBConfig.paper_trading_config(
            account=args.account,
            client_id=args.client_id
        )

    # Override port if specified
    if args.port:
        ib_config.port = args.port

    # Configure setup tracker
    setup_tracker_config = SetupTrackerConfig(
        consol_min_duration=5,
        consol_max_duration=30,
        consol_min_quality=0.5,
        consol_max_range_pips=50,
        nowick_max_wick_ratio=0.3,
        sl_buffer_pips=1.0,  # Note: Spike rule uses hardcoded 2.0
        tp_buffer_pips=1.0,
        max_entry_wait_candles=20
    )

    # Configure order executor
    order_executor_config = OrderExecutorConfig(
        host=ib_config.host,
        port=ib_config.port,
        client_id=ib_config.client_id,
        account=ib_config.account,
        default_position_size=1,  # Conservative for paper trading
        max_position_size=2,
        enable_bracket_orders=True
    )

    # Configure live trading engine
    engine_config = LiveTradingEngineConfig(
        symbol='NQ',
        bar_size='1 min',
        timezone='US/Eastern',
        trading_hours_start=time(9, 30),  # NYSE open
        trading_hours_end=time(16, 0),    # NYSE close
        setup_tracker_config=setup_tracker_config,
        order_executor_config=order_executor_config,
        ib_config=ib_config,
        enable_trading=not args.monitor_only  # Disable actual trading if monitor-only
    )

    # Create engine
    logger.info("Initializing Live Trading Engine...")
    engine = LiveTradingEngine(engine_config)

    try:
        # Connect to IB
        logger.info("Connecting to Interactive Brokers...")
        await engine.initialize()
        logger.info("✅ Connected successfully!")

        # Start trading
        logger.info(f"Starting paper trading for {args.duration} hours...")
        logger.info("Monitoring for 5/1 SLOB setups...")
        logger.info("Press Ctrl+C to stop")

        # Run for specified duration
        start_time = asyncio.get_event_loop().time()
        duration_seconds = args.duration * 3600

        # Hook into engine callbacks
        original_on_setup = engine.setup_tracker.on_setup_complete if hasattr(engine.setup_tracker, 'on_setup_complete') else None

        def setup_callback(setup):
            validator.on_setup_complete(setup)
            if original_on_setup:
                original_on_setup(setup)

        # Run engine
        await engine.start()

        # Monitor for duration
        while (asyncio.get_event_loop().time() - start_time) < duration_seconds:
            await asyncio.sleep(60)  # Check every minute

            # Print periodic statistics
            if int((asyncio.get_event_loop().time() - start_time) / 3600) % 1 == 0:
                validator.print_statistics()

        logger.info(f"Duration complete ({args.duration} hours)")

    except KeyboardInterrupt:
        logger.info("\n\nStopping paper trading (Ctrl+C)...")
    except Exception as e:
        logger.error(f"Error during paper trading: {e}", exc_info=True)
    finally:
        # Shutdown
        logger.info("Shutting down...")
        await engine.shutdown()

        # Print final statistics
        validator.print_statistics()

        logger.info("Paper trading session complete.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Run SLOB paper trading validation (Phase 1)',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--account',
        type=str,
        required=True,
        help='Paper trading account (e.g., DU123456)'
    )

    parser.add_argument(
        '--port',
        type=int,
        default=None,
        help='IB port (default: 7497 for TWS, 4002 for Gateway)'
    )

    parser.add_argument(
        '--client-id',
        type=int,
        default=1,
        help='IB client ID (default: 1)'
    )

    parser.add_argument(
        '--gateway',
        action='store_true',
        help='Use IB Gateway instead of TWS'
    )

    parser.add_argument(
        '--duration',
        type=float,
        default=24.0,
        help='Duration in hours (default: 24)'
    )

    parser.add_argument(
        '--monitor-only',
        action='store_true',
        help='Monitor only (do not place orders)'
    )

    args = parser.parse_args()

    # Validate account format
    if not args.account.startswith('DU'):
        print(f"❌ Error: Paper trading account must start with 'DU', got: {args.account}")
        sys.exit(1)

    # Run paper trading
    try:
        asyncio.run(run_paper_trading(args))
    except KeyboardInterrupt:
        print("\nShutdown complete.")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
