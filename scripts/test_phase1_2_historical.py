#!/usr/bin/env python3
"""
Test Phase 1+2 Changes on Historical Data

Tests the new trading logic (Phase 1+2) on historical NQ data:
- Phase 1: Config changes (0.5% range, 5-min LIQ #2 wait, dynamic retracement, R:R filter)
- Phase 2: Safety features (gap detection, internal HIGH/LOW, 22:00 invalidation)

Usage:
    python scripts/test_phase1_2_historical.py
    python scripts/test_phase1_2_historical.py --data data/nq_6mo_clean.csv --days 30
"""

import asyncio
import argparse
import logging
import pandas as pd
import sys
from pathlib import Path
from datetime import datetime, time
from typing import Dict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from slob.live.setup_tracker import SetupTracker, SetupTrackerConfig
from slob.live.setup_state import SetupState, InvalidationReason
from slob.monitoring.logging_config import setup_logging

# Setup logging
setup_logging(log_dir='logs/', console_level=logging.INFO, file_level=logging.DEBUG)
logger = logging.getLogger(__name__)


def load_historical_data(file_path: str, days: int = None) -> pd.DataFrame:
    """
    Load historical NQ data from CSV.

    Args:
        file_path: Path to CSV file
        days: Number of days to load (None = all)

    Returns:
        DataFrame with OHLCV data
    """
    logger.info(f"Loading historical data from {file_path}")

    df = pd.read_csv(file_path, parse_dates=['Date'])
    df = df.set_index('Date')

    # Ensure timezone-aware DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC')
    else:
        df.index = df.index.tz_convert('UTC')

    # Limit to last N days if specified
    if days:
        cutoff_date = df.index[-1] - pd.Timedelta(days=days)
        df = df[df.index >= cutoff_date]

    logger.info(f"✅ Loaded {len(df)} candles")
    logger.info(f"   Date range: {df.index[0]} to {df.index[-1]}")
    logger.info(f"   Price range: ${df['Low'].min():.2f} - ${df['High'].max():.2f}")

    return df


async def run_historical_test(df: pd.DataFrame, verbose: bool = True):
    """
    Run SetupTracker on historical data to test Phase 1+2 changes.

    Args:
        df: Historical OHLCV DataFrame
        verbose: Print detailed progress
    """
    logger.info("="*80)
    logger.info("TESTING PHASE 1+2 ON HISTORICAL DATA")
    logger.info("="*80)

    # Create config with Phase 1+2 parameters
    config = SetupTrackerConfig(
        # Session times
        lse_open=time(9, 0),
        lse_close=time(15, 30),
        nyse_open=time(15, 30),

        # Phase 1: Consolidation parameters
        consol_min_duration=15,
        consol_max_duration=120,
        consol_min_range_pct=0.1,
        consol_max_range_pct=0.5,  # CHANGED from 0.3 (Q18)

        # Phase 1: LIQ #2 timing
        liq2_minimum_wait_minutes=5,  # CHANGED from 15 (Q4)

        # Phase 1: Retracement (dynamic in code: min(100, price*0.01))
        max_retracement_pips=100.0,

        # Phase 2: Daily invalidation
        daily_invalidation_hour=22,  # 22:00 Swedish time
        daily_invalidation_timezone="Europe/Stockholm",
        skip_weekend=True,
        monday_restart_hour=9,

        # Other parameters
        atr_period=14,
        max_entry_wait_candles=20,
        sl_buffer_pips=1.0,
        tp_buffer_pips=1.0,
        spike_rule_buffer_pips=2.0,
        symbol="NQ"
    )

    logger.info("\n📋 Phase 1+2 Configuration:")
    logger.info(f"   Max consolidation range: 0.5% (was 0.3%)")
    logger.info(f"   LIQ #2 minimum wait: 5 min (was 15 min)")
    logger.info(f"   Dynamic retracement: min(100 pips, 1% of price)")
    logger.info(f"   R:R filter: Positive only")
    logger.info(f"   Gap detection: Active on every candle after LIQ #1")
    logger.info(f"   Internal HIGH/LOW: 5-min HIGH, 3-min LOW confirmation")
    logger.info(f"   Daily invalidation: 22:00 Swedish time + weekend mode")

    # Create tracker
    tracker = SetupTracker(config)

    # Statistics tracking
    stats = {
        'candles_processed': 0,
        'liq1_detected': 0,
        'consolidations_confirmed': 0,
        'liq2_detected': 0,
        'setups_complete': 0,
        'setups_invalidated': 0,
        'invalidation_reasons': {},
        'gap_detections': 0,
        'internal_high_confirmed': 0,
        'internal_low_confirmed': 0,
        'negative_rr_filtered': 0,
        '22_00_invalidations': 0,
        'range_0_3_to_0_5': 0,  # Consolidations in 0.3-0.5% range
    }

    complete_setups = []

    logger.info(f"\n🔄 Processing {len(df)} candles...")

    # Process each candle
    for idx, (timestamp, row) in enumerate(df.iterrows()):
        candle = {
            'timestamp': timestamp,
            'open': row['Open'],
            'high': row['High'],
            'low': row['Low'],
            'close': row['Close'],
            'volume': row['Volume']
        }

        # Process candle
        result = await tracker.on_candle(candle)
        stats['candles_processed'] += 1

        # Track events through candidate state
        if result.candidate:
            candidate = result.candidate

            # Track LIQ #1 detection (new candidate in WATCHING_CONSOL state)
            if candidate.state == SetupState.WATCHING_CONSOL and candidate.liq1_detected:
                # Only count once per candidate
                if not hasattr(candidate, '_liq1_counted'):
                    stats['liq1_detected'] += 1
                    candidate._liq1_counted = True
                    if verbose:
                        logger.info(f"   LIQ #1 detected @ {timestamp.strftime('%Y-%m-%d %H:%M')}")

            # Track consolidation confirmation
            if candidate.consol_confirmed and candidate.state == SetupState.WATCHING_LIQ2:
                # Only count once per candidate
                if not hasattr(candidate, '_consol_counted'):
                    stats['consolidations_confirmed'] += 1
                    candidate._consol_counted = True

                    # Check if range is in 0.3-0.5% (new range that was previously rejected)
                    if candidate.consol_range:
                        range_pct = (candidate.consol_range / candidate.consol_high) * 100
                        if 0.3 < range_pct <= 0.5:
                            stats['range_0_3_to_0_5'] += 1
                            if verbose:
                                logger.info(f"   ✅ Consolidation in NEW range: {range_pct:.3f}% (was rejected before)")

            # Track LIQ #2
            if candidate.liq2_detected:
                # Only count once per candidate
                if not hasattr(candidate, '_liq2_counted'):
                    stats['liq2_detected'] += 1
                    candidate._liq2_counted = True

            # Track gap detection
            if candidate.gap_detected:
                stats['gap_detections'] += 1
                if verbose:
                    logger.info(f"   🚫 Gap detected: {candidate.gap_type} ({candidate.gap_size_pips:.2f} pips)")

            # Track internal HIGH/LOW confirmation
            if candidate.internal_high_confirmed:
                stats['internal_high_confirmed'] += 1
            if candidate.internal_low_confirmed:
                stats['internal_low_confirmed'] += 1

        # Track setup completion
        if result.setup_completed and result.candidate:
            stats['setups_complete'] += 1
            complete_setups.append(result.candidate)

            if verbose:
                candidate = result.candidate
                logger.info(f"\n✅ SETUP COMPLETE:")
                logger.info(f"   ID: {candidate.id[:8]}")
                logger.info(f"   Entry: ${candidate.entry_price:.2f}")
                logger.info(f"   SL: ${candidate.sl_price:.2f}")
                logger.info(f"   TP: ${candidate.tp_price:.2f}")
                logger.info(f"   R:R: {candidate.risk_reward_ratio:.2f}")

        # Track invalidations
        if result.setup_invalidated and result.candidate:
            stats['setups_invalidated'] += 1
            reason = result.candidate.invalidation_reason

            if reason:
                reason_str = reason.value if hasattr(reason, 'value') else str(reason)
                stats['invalidation_reasons'][reason_str] = stats['invalidation_reasons'].get(reason_str, 0) + 1

                # Track specific Phase 1+2 invalidations
                if reason == InvalidationReason.GAP_DETECTED:
                    stats['gap_detections'] += 1
                elif reason == InvalidationReason.NEGATIVE_RISK_REWARD:
                    stats['negative_rr_filtered'] += 1
                elif reason == InvalidationReason.MARKET_CLOSED:
                    stats['22_00_invalidations'] += 1

        # Progress update
        if verbose and (idx + 1) % 1000 == 0:
            logger.info(f"   Processed {idx + 1}/{len(df)} candles...")

    return stats, complete_setups, tracker


def print_results(stats: Dict, complete_setups: list):
    """Print test results."""
    logger.info("\n" + "="*80)
    logger.info("PHASE 1+2 TEST RESULTS")
    logger.info("="*80)

    logger.info(f"\n📊 PROCESSING STATISTICS:")
    logger.info(f"   Candles processed:        {stats['candles_processed']:,}")
    logger.info(f"   LIQ #1 detected:          {stats['liq1_detected']}")
    logger.info(f"   Consolidations confirmed: {stats['consolidations_confirmed']}")
    logger.info(f"   LIQ #2 detected:          {stats['liq2_detected']}")
    logger.info(f"   Setups complete:          {stats['setups_complete']}")
    logger.info(f"   Setups invalidated:       {stats['setups_invalidated']}")

    logger.info(f"\n🆕 PHASE 1 IMPACT (Config Changes):")
    logger.info(f"   Consolidations in 0.3-0.5% range: {stats['range_0_3_to_0_5']} (NEW - was rejected before)")
    logger.info(f"   Negative R:R filtered:            {stats['negative_rr_filtered']} (NEW filter)")

    logger.info(f"\n🆕 PHASE 2 IMPACT (Safety Features):")
    logger.info(f"   Gap detections:                   {stats['gap_detections']} (NEW filter)")
    logger.info(f"   Internal HIGH confirmed:          {stats['internal_high_confirmed']} (NEW tracking)")
    logger.info(f"   Internal LOW confirmed:           {stats['internal_low_confirmed']} (NEW tracking)")
    logger.info(f"   22:00 invalidations:              {stats['22_00_invalidations']} (NEW daily reset)")

    if stats['invalidation_reasons']:
        logger.info(f"\n🚫 INVALIDATION REASONS:")
        for reason, count in sorted(stats['invalidation_reasons'].items(), key=lambda x: x[1], reverse=True):
            logger.info(f"   {reason:30s}: {count}")

    if complete_setups:
        logger.info(f"\n🎯 COMPLETE SETUPS ANALYSIS ({len(complete_setups)} setups):")

        # Analyze setups
        short_setups = [s for s in complete_setups if s.direction and s.direction.value == 'SHORT']
        long_setups = [s for s in complete_setups if s.direction and s.direction.value == 'LONG']

        logger.info(f"   SHORT setups: {len(short_setups)}")
        logger.info(f"   LONG setups:  {len(long_setups)}")

        # Average metrics
        avg_rr = sum(s.risk_reward_ratio for s in complete_setups if s.risk_reward_ratio) / len(complete_setups)
        logger.info(f"   Average R:R:  {avg_rr:.2f}")

        # Range analysis
        ranges = []
        for s in complete_setups:
            if s.consol_range and s.consol_high:
                range_pct = (s.consol_range / s.consol_high) * 100
                ranges.append(range_pct)

        if ranges:
            logger.info(f"   Range analysis:")
            logger.info(f"      Min: {min(ranges):.3f}%")
            logger.info(f"      Max: {max(ranges):.3f}%")
            logger.info(f"      Avg: {sum(ranges)/len(ranges):.3f}%")

            # Count how many would have been rejected with old 0.3% limit
            rejected_by_old_limit = sum(1 for r in ranges if r > 0.3)
            logger.info(f"      Would be rejected by old 0.3% limit: {rejected_by_old_limit} ({rejected_by_old_limit/len(ranges)*100:.1f}%)")

    logger.info("\n" + "="*80)

    # Summary
    if stats['setups_complete'] > 0:
        logger.info("✅ Phase 1+2 changes are WORKING!")
        logger.info(f"   Found {stats['setups_complete']} complete setups with new logic")
    else:
        logger.info("⚠️  No complete setups found")
        logger.info("   This may be normal if market conditions don't produce setups")

    if stats['range_0_3_to_0_5'] > 0:
        logger.info(f"✅ Range expansion WORKING: {stats['range_0_3_to_0_5']} consolidations in NEW 0.3-0.5% range")

    if stats['gap_detections'] > 0:
        logger.info(f"✅ Gap detection WORKING: {stats['gap_detections']} gaps detected and filtered")

    if stats['22_00_invalidations'] > 0:
        logger.info(f"✅ Daily invalidation WORKING: {stats['22_00_invalidations']} setups invalidated at 22:00")

    logger.info("\n" + "="*80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='Test Phase 1+2 changes on historical data',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--data',
        type=str,
        default='data/nq_6mo_clean.csv',
        help='Path to historical CSV file'
    )

    parser.add_argument(
        '--days',
        type=int,
        default=None,
        help='Number of days to process (default: all)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Print detailed progress'
    )

    args = parser.parse_args()

    try:
        # Load data
        df = load_historical_data(args.data, days=args.days)

        # Run test
        stats, complete_setups, tracker = asyncio.run(
            run_historical_test(df, verbose=args.verbose)
        )

        # Print results
        print_results(stats, complete_setups)

        return 0

    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
