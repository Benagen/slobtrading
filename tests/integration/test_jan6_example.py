"""
Integration Test: Jan 6, 2026 Setup Replay

This test replays the actual Jan 6, 2026 NQ setup that prompted the
Phase 1+2+3 strategy refinement.

Timeline (all times UTC):
- 15:30: LIQ #1 @ $25,452 (breaks LSE High $25,450)
- 15:31-15:50: Consolidation builds
- 16:01: Internal HIGH @ $25,587
- 16:06: HIGH confirmed (5 min without break)
- 16:11: Internal LOW @ $25,542
- 16:14: LOW confirmed (3 min without break)
- 16:20-16:25: Consolidation continues (NO no-wick requirement - Phase 3!)
- 16:26: LIQ #2 breaks HIGH @ $25,587
- 16:26-16:30: Searching for no-wick (Phase 3 new state)
- 16:27: No-wick found (bullish candle, minimal upper wick)
- 16:31: Entry trigger (close below no-wick LOW @ $25,572)

Expected Results:
- Consolidation range: 0.176% (within 0.1-0.5%) ✓
- Duration: ~20 min (within 15-120 min) ✓
- LIQ #2 wait: ~12 min (> 5 min minimum) ✓
- No-wick found AFTER LIQ #2 (Phase 3) ✓
- Setup completes successfully ✓
"""

import pytest
import asyncio
from datetime import datetime, time, timedelta
from typing import List, Dict

from slob.live.setup_tracker import SetupTracker, SetupTrackerConfig
from slob.live.setup_state import SetupState, TradeDirection


def create_candle(timestamp: datetime, open_price: float, high: float,
                  low: float, close: float, volume: int = 1000) -> Dict:
    """Create a candle dictionary."""
    return {
        'timestamp': timestamp,
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    }


def generate_jan6_setup() -> List[Dict]:
    """
    Generate the Jan 6, 2026 setup candle sequence.

    NOTE: Candles are designed to be gap-free for testing purposes.
    Each candle's open/close is within the previous candle's range.

    Returns:
        List of 5-min candles from 09:00-17:00 UTC
    """
    base_date = datetime(2026, 1, 6, 0, 0, 0)
    candles = []

    # ================================================================
    # LSE SESSION (09:00 - 15:30) - Build to HIGH $25,450
    # ================================================================

    # 09:00-15:00: Gradual climb to establish LSE High (gap-free)
    current_close = 25300.0
    lse_high = 25450.0

    for hour in range(9, 15):
        for minute in [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]:
            ts = base_date.replace(hour=hour, minute=minute)

            # Gradual climb
            progress = ((hour - 9) * 12 + minute // 5) / ((15 - 9) * 12)
            target_price = 25300 + (lse_high - 25300) * progress

            # Create candle with small range, no gaps
            open_p = current_close  # Open at previous close (no gap!)
            high_p = max(open_p, target_price) + 5.0
            low_p = min(open_p, target_price) - 5.0
            close_p = target_price

            candles.append(create_candle(ts, open_p, high_p, low_p, close_p))
            current_close = close_p  # Track close for next candle

    # 15:00-15:25: Reach LSE High $25,450 (gap-free)
    for minute in [0, 5, 10, 15, 20, 25]:
        ts = base_date.replace(hour=15, minute=minute)
        open_p = current_close
        high_p = 25450.0  # LSE High
        low_p = current_close - 5.0
        close_p = 25448.0
        candles.append(create_candle(ts, open_p, high_p, low_p, close_p))
        current_close = close_p

    # ================================================================
    # 15:30: LIQ #1 - NYSE BREAKS LSE HIGH @ $25,452 (gap-free)
    # ================================================================
    open_p = current_close
    candles.append(create_candle(
        base_date.replace(hour=15, minute=30),
        open_price=open_p,
        high=25452.0,  # LIQ #1 breaks LSE High
        low=min(open_p, 25448.0),
        close=25451.0
    ))
    current_close = 25451.0

    # ================================================================
    # 15:35-16:01: BUILD CONSOLIDATION TO HIGH @ $25,587 (gap-free)
    # ================================================================
    # Smooth progression from 25451 to 25587 over 7 candles (need 15+ min for duration!)

    consolidation_prices = [25460, 25475, 25495, 25515, 25535, 25550, 25570, 25585]

    for i, minute in enumerate([35, 40, 45, 50, 55, 0, 1, 2], start=0):
        hour = 15 if minute >= 35 else 16
        target_price = consolidation_prices[i]

        open_p = current_close  # No gap!
        high_p = max(open_p, target_price) + 5.0 if i < 7 else 25587.0  # HIGH at 16:02
        low_p = min(open_p, target_price) - 5.0
        close_p = target_price

        candles.append(create_candle(
            base_date.replace(hour=hour, minute=minute),
            open_p, high_p, low_p, close_p
        ))
        current_close = close_p

    # ================================================================
    # 16:03-16:11: Hold below $25,587, then pull back toward LOW (gap-free)
    # ================================================================
    pullback_targets = [25580, 25578, 25576, 25574, 25570, 25565, 25560, 25555, 25550]

    for i, minute in enumerate(range(3, 12)):
        target = pullback_targets[i]
        open_p = current_close
        high_p = max(open_p, target) + 3.0
        low_p = min(open_p, target) - 3.0
        close_p = target

        # Keep HIGH just below 25587 for confirmation
        if high_p > 25586:
            high_p = 25586.0

        candles.append(create_candle(
            base_date.replace(hour=16, minute=minute),
            open_p, high_p, low_p, close_p
        ))
        current_close = close_p

    # ================================================================
    # 16:12: INTERNAL LOW @ $25,542 (will be confirmed @ 16:15) (gap-free)
    # ================================================================
    open_p = current_close
    candles.append(create_candle(
        base_date.replace(hour=16, minute=12),
        open_price=open_p,
        high=max(open_p, 25545.0),
        low=25542.0,  # Internal LOW
        close=25545.0
    ))
    current_close = 25545.0

    # ================================================================
    # 16:13-16:26: CONSOLIDATION CONTINUES (gap-free)
    # Hold in range 25542-25587 for minimum duration (need 15 min total!)
    # ================================================================
    consolidation_targets = [25546, 25548, 25550, 25555, 25560, 25558, 25562, 25560, 25565, 25568, 25570, 25572, 25574, 25574]

    for i, minute in enumerate(range(13, 27)):
        target = consolidation_targets[i]
        open_p = current_close
        high_p = max(open_p, target) + 3.0
        low_p = min(open_p, target) - 3.0
        close_p = target

        # Keep within consolidation range
        if high_p > 25586:
            high_p = 25586.0
        if low_p < 25543:
            low_p = 25543.0

        candles.append(create_candle(
            base_date.replace(hour=16, minute=minute),
            open_p, high_p, low_p, close_p
        ))
        current_close = close_p

    # ================================================================
    # 16:27: LIQ #2 - BREAKS CONSOLIDATION HIGH @ $25,587 (gap-free)
    # This triggers transition to SEARCHING_NOWICK_AFTER_LIQ2 (Phase 3!)
    # ================================================================
    open_p = current_close
    candles.append(create_candle(
        base_date.replace(hour=16, minute=27),
        open_price=open_p,
        high=25590.0,  # LIQ #2 breaks 25587
        low=min(open_p, 25572.0),
        close=25588.0
    ))
    current_close = 25588.0

    # ================================================================
    # 16:28: NO-WICK CANDLE (found AFTER LIQ #2 - Phase 3!) (gap-free)
    # Bullish candle with minimal upper wick
    # ================================================================
    open_p = current_close
    candles.append(create_candle(
        base_date.replace(hour=16, minute=28),
        open_price=open_p,
        high=25592.0,  # Minimal upper wick: 592 - 591 = 1 pip
        low=min(open_p, 25587.0),
        close=25591.0  # Body: 591 - 588 = 3 pips
    ))
    current_close = 25591.0

    # ================================================================
    # 16:29-16:31: Move up after no-wick (gap-free)
    # ================================================================
    for minute in [29, 30, 31]:
        open_p = current_close
        candles.append(create_candle(
            base_date.replace(hour=16, minute=minute),
            open_price=open_p,
            high=25595.0,
            low=min(open_p, 25588.0),
            close=25593.0
        ))
        current_close = 25593.0

    # ================================================================
    # 16:32: ENTRY TRIGGER - Close BELOW no-wick LOW @ $25,587 (gap-free)
    # ================================================================
    open_p = current_close
    candles.append(create_candle(
        base_date.replace(hour=16, minute=32),
        open_price=open_p,
        high=max(open_p, 25595.0),
        low=25570.0,
        close=25575.0  # ENTRY TRIGGER (below no-wick low 25587)
    ))
    current_close = 25575.0

    # ================================================================
    # 16:33-17:00: Continue trading (gap-free)
    # ================================================================
    for minute in range(33, 60, 5):
        open_p = current_close
        candles.append(create_candle(
            base_date.replace(hour=16, minute=minute),
            open_price=open_p,
            high=max(open_p, 25580.0),
            low=min(open_p, 25570.0),
            close=25576.0
        ))
        current_close = 25576.0

    return candles


@pytest.mark.asyncio
async def test_jan6_2026_setup_replay():
    """
    Test Jan 6, 2026 setup with Phase 1+2+3 implementation.

    This is the CRITICAL validation test - if this passes, we know
    the entire strategy refinement is correctly implemented.
    """
    # ================================================================
    # SETUP: Create tracker with Phase 1+2+3 config
    # ================================================================

    config = SetupTrackerConfig(
        # Session times
        lse_open=time(9, 0),
        lse_close=time(15, 30),
        nyse_open=time(15, 30),

        # Phase 1: Consolidation parameters
        consol_min_duration=15,
        consol_max_duration=120,
        consol_min_range_pct=0.1,
        consol_max_range_pct=0.7,  # Updated: 0.3 → 0.5 → 0.7

        # Phase 1: LIQ #2 timing
        liq2_minimum_wait_minutes=5,  # Phase 1: 15 → 5 min

        # Phase 3: No-wick search
        no_wick_search_window=10,

        # Phase 1: Retracement
        max_retracement_pips=100.0,

        # Phase 2: Daily invalidation
        daily_invalidation_hour=22,
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

    tracker = SetupTracker(config)
    candles = generate_jan6_setup()

    print(f"\n{'='*80}")
    print(f"JAN 6, 2026 SETUP REPLAY TEST")
    print(f"{'='*80}\n")
    print(f"Processing {len(candles)} candles from 09:00-17:00 UTC")
    print(f"Expected: Complete setup with Phase 1+2+3 flow\n")

    # ================================================================
    # EXECUTE: Process all candles
    # ================================================================

    liq1_detected = False
    consol_confirmed = False
    liq2_detected = False
    nowick_search_started = False
    nowick_found = False
    entry_triggered = False
    setup_complete = False

    candidate = None

    for i, candle in enumerate(candles):
        result = await tracker.on_candle(candle)

        # Track candidate state
        if result.candidate:
            candidate = result.candidate

            # Check milestones
            if candidate.liq1_detected and not liq1_detected:
                liq1_detected = True
                print(f"✓ LIQ #1 detected @ {candle['timestamp'].strftime('%H:%M')}")
                print(f"  Price: ${candidate.liq1_price:.2f}")
                print(f"  Direction: {candidate.direction.value}\n")

            if candidate.consol_confirmed and not consol_confirmed:
                consol_confirmed = True
                range_pct = (candidate.consol_range / candidate.consol_high) * 100
                print(f"✓ Consolidation confirmed @ {candle['timestamp'].strftime('%H:%M')}")
                print(f"  Duration: {len(candidate.consol_candles)} min")
                print(f"  Range: ${candidate.consol_range:.2f} ({range_pct:.3f}%)")
                print(f"  HIGH: ${candidate.consol_high:.2f}")
                print(f"  LOW: ${candidate.consol_low:.2f}")
                print(f"  State: {candidate.state.name}\n")

            if candidate.liq2_detected and not liq2_detected:
                liq2_detected = True
                print(f"✓ LIQ #2 detected @ {candle['timestamp'].strftime('%H:%M')}")
                print(f"  Price: ${candidate.liq2_price:.2f}")
                print(f"  State: {candidate.state.name}\n")

            if candidate.state == SetupState.SEARCHING_NOWICK_AFTER_LIQ2 and not nowick_search_started:
                nowick_search_started = True
                print(f"✓ No-wick search started (Phase 3!) @ {candle['timestamp'].strftime('%H:%M')}")
                print(f"  State: {candidate.state.name}")
                print(f"  Search window: {config.no_wick_search_window} candles\n")

            if candidate.nowick_found and not nowick_found:
                nowick_found = True
                print(f"✓ No-wick found @ {candle['timestamp'].strftime('%H:%M')}")
                print(f"  HIGH: ${candidate.nowick_high:.2f}")
                print(f"  LOW: ${candidate.nowick_low:.2f}")
                print(f"  State: {candidate.state.name}\n")

            if candidate.entry_triggered and not entry_triggered:
                entry_triggered = True
                print(f"✓ Entry trigger @ {candle['timestamp'].strftime('%H:%M')}")
                print(f"  Entry price: ${candidate.entry_price:.2f}")
                print(f"  State: {candidate.state.name}\n")

        if result.setup_completed and not setup_complete:
            setup_complete = True
            print(f"{'='*80}")
            print(f"✅ SETUP COMPLETE @ {candle['timestamp'].strftime('%H:%M')}")
            print(f"{'='*80}\n")
            print(f"Setup ID: {candidate.id[:8]}")
            print(f"Direction: {candidate.direction.value}")
            print(f"Entry: ${candidate.entry_price:.2f}")
            print(f"SL: ${candidate.sl_price:.2f}")
            print(f"TP: ${candidate.tp_price:.2f}")
            print(f"R:R: {candidate.risk_reward_ratio:.2f}")
            print(f"\n{'='*80}\n")

    # ================================================================
    # VALIDATE: Check all expected milestones were reached
    # ================================================================

    print(f"VALIDATION:")
    print(f"{'='*80}\n")

    # Check each milestone
    assert liq1_detected, "❌ FAILED: LIQ #1 not detected"
    print(f"✅ LIQ #1 detected")

    assert consol_confirmed, "❌ FAILED: Consolidation not confirmed"
    print(f"✅ Consolidation confirmed")

    # Validate consolidation range
    assert candidate is not None, "❌ FAILED: No candidate found"
    range_pct = (candidate.consol_range / candidate.consol_high) * 100
    assert 0.1 <= range_pct <= 0.5, f"❌ FAILED: Range {range_pct:.3f}% outside 0.1-0.5%"
    print(f"✅ Consolidation range valid: {range_pct:.3f}% (within 0.1-0.5%)")

    # Validate duration
    duration = len(candidate.consol_candles)
    assert 15 <= duration <= 120, f"❌ FAILED: Duration {duration} min outside 15-120 min"
    print(f"✅ Consolidation duration valid: {duration} min (within 15-120 min)")

    assert liq2_detected, "❌ FAILED: LIQ #2 not detected"
    print(f"✅ LIQ #2 detected")

    # Validate LIQ #2 wait time (Phase 1: min 5 min)
    if candidate.consol_confirmed_time and candidate.liq2_time:
        wait_minutes = (candidate.liq2_time - candidate.consol_confirmed_time).total_seconds() / 60
        assert wait_minutes >= 5, f"❌ FAILED: LIQ #2 wait {wait_minutes:.1f} min < 5 min"
        print(f"✅ LIQ #2 wait time valid: {wait_minutes:.1f} min (>= 5 min)")

    # Phase 3 validation: No-wick search started
    assert nowick_search_started, "❌ FAILED: No-wick search not started (Phase 3)"
    print(f"✅ No-wick search started after LIQ #2 (Phase 3)")

    assert nowick_found, "❌ FAILED: No-wick not found"
    print(f"✅ No-wick found")

    assert entry_triggered, "❌ FAILED: Entry not triggered"
    print(f"✅ Entry triggered")

    assert setup_complete, "❌ FAILED: Setup not completed"
    print(f"✅ Setup completed")

    # Validate R:R is positive (Phase 1)
    assert candidate.risk_reward_ratio > 0, f"❌ FAILED: R:R {candidate.risk_reward_ratio:.2f} not positive"
    print(f"✅ R:R positive: {candidate.risk_reward_ratio:.2f}")

    print(f"\n{'='*80}")
    print(f"✅ ALL VALIDATIONS PASSED - JAN 6 SETUP WORKS WITH PHASE 1+2+3!")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    # Run test standalone
    asyncio.run(test_jan6_2026_setup_replay())
