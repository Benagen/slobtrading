"""
Setup Tracker

Real-time 5/1 SLOB setup detection using incremental state machine.

Key design principle: NO LOOK-AHEAD BIAS
- All decisions based on past + current candle only
- Consolidation bounds update incrementally
- Consolidation confirmed only on LIQ #2 breakout
- Multiple concurrent setup candidates supported

Usage:
    tracker = SetupTracker(config)

    # Feed candles one by one
    async for candle in candle_stream:
        result = await tracker.on_candle(candle)

        if result.setup_completed:
            # Place order
            await order_executor.place_order(result.candidate)
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, time, timedelta
from dataclasses import dataclass

from .setup_state import (
    SetupState,
    SetupCandidate,
    StateTransitionValidator,
    InvalidationReason
)

logger = logging.getLogger(__name__)


@dataclass
class SetupTrackerConfig:
    """Configuration for SetupTracker."""

    # Session times (UTC)
    lse_open: time = time(9, 0)
    lse_close: time = time(15, 30)
    nyse_open: time = time(15, 30)

    # Consolidation parameters
    consol_min_duration: int = 15  # minutes
    consol_max_duration: int = 30  # minutes
    consol_min_quality: float = 0.4  # minimum quality score

    # ATR parameters (for consolidation range validation)
    atr_period: int = 14
    atr_multiplier_max: float = 3.0  # max ATR multiplier for consol range

    # No-wick parameters
    nowick_percentile: int = 90  # percentile threshold for wick size
    nowick_min_body_percentile: int = 30
    nowick_max_body_percentile: int = 70

    # Entry parameters
    max_entry_wait_candles: int = 20  # max candles to wait for entry
    max_retracement_pips: float = 100.0  # max retracement above no-wick high

    # Risk parameters
    sl_buffer_pips: float = 1.0  # buffer above LIQ #2 high for SL
    tp_buffer_pips: float = 1.0  # buffer below LSE Low for TP

    # Symbol
    symbol: str = "NQ"


@dataclass
class CandleUpdate:
    """Result from on_candle() processing."""

    setup_completed: bool = False
    setup_invalidated: bool = False
    candidate: Optional[SetupCandidate] = None
    message: Optional[str] = None


class SetupTracker:
    """
    Real-time 5/1 SLOB setup detection.

    Tracks multiple concurrent setup candidates using state machine.
    All updates are incremental with NO look-ahead bias.

    Flow:
        LSE Session (09:00-15:30) → Track LSE High/Low
        NYSE Session (15:30+) →
            LIQ #1 detected → Create candidate (WATCHING_CONSOL)
            Consolidation forms → Confirm (WATCHING_LIQ2)
            LIQ #2 detected → Transition (WAITING_ENTRY)
            Entry trigger → Complete (SETUP_COMPLETE)
    """

    def __init__(self, config: Optional[SetupTrackerConfig] = None):
        """
        Initialize SetupTracker.

        Args:
            config: Configuration object
        """
        self.config = config or SetupTrackerConfig()

        # Current session state
        self.current_date: Optional[datetime] = None
        self.lse_high: Optional[float] = None
        self.lse_low: Optional[float] = None
        self.lse_close_time: Optional[datetime] = None

        # Active setup candidates (key = candidate.id)
        self.active_candidates: Dict[str, SetupCandidate] = {}

        # Completed/invalidated setups (for analysis)
        self.completed_setups: List[SetupCandidate] = []
        self.invalidated_setups: List[SetupCandidate] = []

        # ATR tracking (for consolidation range validation)
        self.recent_candles: List[Dict] = []  # Last N candles for ATR
        self.atr_value: Optional[float] = None

        # Statistics
        self.stats = {
            'candles_processed': 0,
            'liq1_detected': 0,
            'setups_completed': 0,
            'setups_invalidated': 0,
            'candidates_active': 0
        }

        logger.info(f"✅ SetupTracker initialized for {self.config.symbol}")

    async def on_candle(self, candle: Dict) -> CandleUpdate:
        """
        Process new candle.

        This is the main entry point - called for each new candle.

        Args:
            candle: Dict with keys: timestamp, open, high, low, close, volume

        Returns:
            CandleUpdate with setup completion/invalidation info
        """
        self.stats['candles_processed'] += 1
        timestamp = candle['timestamp']

        # Update ATR
        self._update_atr(candle)

        # Check if new day
        if self.current_date != timestamp.date():
            self._start_new_day(timestamp)

        # LSE Session: Track LSE High/Low
        if self._is_lse_session(timestamp):
            self._update_lse_levels(candle)
            return CandleUpdate(message="LSE session - tracking levels")

        # NYSE Session: Track setups
        elif self._is_nyse_session(timestamp):
            # Check if LSE levels established
            if self.lse_high is None or self.lse_low is None:
                return CandleUpdate(message="NYSE session - waiting for LSE levels")

            # Check for new LIQ #1 (create new candidate)
            if self._check_for_liq1(candle):
                candidate = self._create_candidate_from_liq1(candle)
                self.active_candidates[candidate.id] = candidate
                self.stats['liq1_detected'] += 1
                self.stats['candidates_active'] = len(self.active_candidates)

                logger.info(
                    f"🔵 LIQ #1 detected @ {timestamp.strftime('%H:%M')} "
                    f"(price: {candle['high']:.2f}, LSE High: {self.lse_high:.2f})"
                )

            # Update all active candidates (skip just-created candidates)
            results = []
            for candidate_id in list(self.active_candidates.keys()):
                candidate = self.active_candidates[candidate_id]

                # Skip updating candidate if this is the LIQ #1 candle that created it
                # (prevents LIQ #1 from being added to consolidation candles)
                if candidate.liq1_time and candidate.liq1_time == candle['timestamp']:
                    continue

                result = await self._update_candidate(candidate, candle)

                if result.setup_completed or result.setup_invalidated:
                    results.append(result)

                    # Remove from active
                    del self.active_candidates[candidate_id]
                    self.stats['candidates_active'] = len(self.active_candidates)

                    # Add to completed/invalidated
                    if result.setup_completed:
                        self.completed_setups.append(candidate)
                        self.stats['setups_completed'] += 1
                    else:
                        self.invalidated_setups.append(candidate)
                        self.stats['setups_invalidated'] += 1

            # Return first completed/invalidated setup
            if results:
                return results[0]

            return CandleUpdate(
                message=f"NYSE session - {len(self.active_candidates)} active candidates"
            )

        # After hours
        else:
            return CandleUpdate(message="After hours - no tracking")

    def _start_new_day(self, timestamp: datetime):
        """Start new trading day - reset state."""
        self.current_date = timestamp.date()
        self.lse_high = None
        self.lse_low = None
        self.lse_close_time = None

        # Invalidate any active candidates from previous day
        for candidate in self.active_candidates.values():
            StateTransitionValidator.invalidate(
                candidate,
                InvalidationReason.MARKET_CLOSED
            )
            self.invalidated_setups.append(candidate)

        self.active_candidates.clear()
        self.stats['candidates_active'] = 0

        logger.info(f"📅 New trading day: {self.current_date}")

    def _is_lse_session(self, timestamp: datetime) -> bool:
        """Check if timestamp is in LSE session (09:00-15:30)."""
        t = timestamp.time()
        return self.config.lse_open <= t < self.config.lse_close

    def _is_nyse_session(self, timestamp: datetime) -> bool:
        """Check if timestamp is in NYSE session (>=15:30)."""
        return timestamp.time() >= self.config.nyse_open

    def _update_lse_levels(self, candle: Dict):
        """Update LSE High/Low from LSE session candles."""
        if self.lse_high is None:
            self.lse_high = candle['high']
            self.lse_low = candle['low']
        else:
            self.lse_high = max(self.lse_high, candle['high'])
            self.lse_low = min(self.lse_low, candle['low'])

        self.lse_close_time = candle['timestamp']

    def _update_atr(self, candle: Dict):
        """Update ATR calculation."""
        self.recent_candles.append(candle)

        # Keep only last N candles
        if len(self.recent_candles) > self.config.atr_period + 1:
            self.recent_candles.pop(0)

        # Calculate ATR (need at least 2 candles)
        if len(self.recent_candles) >= 2:
            true_ranges = []
            for i in range(1, len(self.recent_candles)):
                prev = self.recent_candles[i-1]
                curr = self.recent_candles[i]

                tr = max(
                    curr['high'] - curr['low'],
                    abs(curr['high'] - prev['close']),
                    abs(curr['low'] - prev['close'])
                )
                true_ranges.append(tr)

            self.atr_value = sum(true_ranges) / len(true_ranges)

    def _check_for_liq1(self, candle: Dict) -> bool:
        """
        Check if current candle is a LIQ #1 (breaks LSE High).

        Returns:
            True if LIQ #1 detected
        """
        # Must break LSE High
        if candle['high'] <= self.lse_high:
            return False

        # Check if we already have a candidate in WATCHING_CONSOL state
        # (don't create multiple LIQ #1 candidates too close together)
        for candidate in self.active_candidates.values():
            if candidate.state == SetupState.WATCHING_CONSOL:
                # If less than 5 minutes since last LIQ #1, skip
                time_diff = (candle['timestamp'] - candidate.liq1_time).total_seconds() / 60
                if time_diff < 5:
                    return False

        return True

    def _create_candidate_from_liq1(self, candle: Dict) -> SetupCandidate:
        """Create new setup candidate from LIQ #1 detection."""
        candidate = SetupCandidate(
            symbol=self.config.symbol,
            lse_high=self.lse_high,
            lse_low=self.lse_low,
            lse_close_time=self.lse_close_time,
            state=SetupState.WATCHING_LIQ1
        )

        # Mark LIQ #1 detected
        candidate.liq1_detected = True
        candidate.liq1_time = candle['timestamp']
        candidate.liq1_price = candle['high']
        candidate.liq1_confidence = self._calculate_liq1_confidence(candle)

        # Transition to WATCHING_CONSOL
        StateTransitionValidator.transition_to(
            candidate,
            SetupState.WATCHING_CONSOL,
            reason=f"LIQ #1 @ {candle['high']:.2f}"
        )

        return candidate

    def _calculate_liq1_confidence(self, candle: Dict) -> float:
        """
        Calculate confidence score for LIQ #1.

        Factors:
        - Volume spike
        - Wick rejection (price rejected back down)
        - Distance above LSE High

        Returns:
            Confidence score 0.0-1.0
        """
        # Simple version for now
        # TODO: Add volume comparison, wick analysis
        return 0.7

    async def _update_candidate(
        self,
        candidate: SetupCandidate,
        candle: Dict
    ) -> CandleUpdate:
        """
        Update setup candidate with new candle.

        This is where the magic happens - state machine updates!

        Args:
            candidate: Setup candidate to update
            candle: New candle

        Returns:
            CandleUpdate with completion/invalidation info
        """
        candidate.candles_processed += 1
        candidate.update_timestamp()

        # State: WATCHING_CONSOL
        if candidate.state == SetupState.WATCHING_CONSOL:
            return await self._update_watching_consol(candidate, candle)

        # State: WATCHING_LIQ2
        elif candidate.state == SetupState.WATCHING_LIQ2:
            return await self._update_watching_liq2(candidate, candle)

        # State: WAITING_ENTRY
        elif candidate.state == SetupState.WAITING_ENTRY:
            return await self._update_waiting_entry(candidate, candle)

        else:
            return CandleUpdate(message=f"Unknown state: {candidate.state}")

    async def _update_watching_consol(
        self,
        candidate: SetupCandidate,
        candle: Dict
    ) -> CandleUpdate:
        """
        Update candidate in WATCHING_CONSOL state.

        Actions:
        - Add candle to consolidation window
        - Update consolidation bounds (incrementally!)
        - Check if min duration reached + quality OK
        - Find no-wick candle
        - Transition to WATCHING_LIQ2 if ready
        - Invalidate if timeout/quality too low
        """
        # Add candle to consolidation window
        candidate.consol_candles.append({
            'timestamp': candle['timestamp'],
            'open': candle['open'],
            'high': candle['high'],
            'low': candle['low'],
            'close': candle['close'],
            'volume': candle['volume']
        })

        # Update bounds incrementally (CRITICAL: only past data!)
        candidate.consol_high = max(c['high'] for c in candidate.consol_candles)
        candidate.consol_low = min(c['low'] for c in candidate.consol_candles)
        candidate.consol_range = candidate.consol_high - candidate.consol_low

        # Check timeout (max duration exceeded)
        if len(candidate.consol_candles) > self.config.consol_max_duration:
            StateTransitionValidator.invalidate(
                candidate,
                InvalidationReason.CONSOL_TIMEOUT
            )
            return CandleUpdate(
                setup_invalidated=True,
                candidate=candidate,
                message=f"Consolidation timeout ({len(candidate.consol_candles)} min)"
            )

        # Calculate quality score
        candidate.consol_quality_score = self._calculate_consolidation_quality(
            candidate.consol_candles
        )

        # Check if min duration reached
        if len(candidate.consol_candles) >= self.config.consol_min_duration:
            # Check quality (only after min duration reached!)
            if candidate.consol_quality_score < self.config.consol_min_quality:
                StateTransitionValidator.invalidate(
                    candidate,
                    InvalidationReason.CONSOL_QUALITY_LOW
                )
                return CandleUpdate(
                    setup_invalidated=True,
                    candidate=candidate,
                    message=f"Consolidation quality too low ({candidate.consol_quality_score:.2f})"
                )

            # Check range (not too wide)
            if self.atr_value is not None:
                max_range = self.atr_value * self.config.atr_multiplier_max
                if candidate.consol_range > max_range:
                    StateTransitionValidator.invalidate(
                        candidate,
                        InvalidationReason.CONSOL_RANGE_TOO_WIDE
                    )
                    return CandleUpdate(
                        setup_invalidated=True,
                        candidate=candidate,
                        message=f"Consolidation range too wide ({candidate.consol_range:.2f} > {max_range:.2f})"
                    )

            # Find no-wick candle
            nowick = self._find_nowick_in_consolidation(candidate.consol_candles)

            if nowick is None:
                # Keep waiting for no-wick
                return CandleUpdate(message="Waiting for no-wick candle")

            # No-wick found! Mark it
            candidate.nowick_found = True
            candidate.nowick_time = nowick['timestamp']
            candidate.nowick_high = nowick['high']
            candidate.nowick_low = nowick['low']
            candidate.nowick_wick_ratio = nowick['wick_ratio']

            # Confirm consolidation
            candidate.consol_confirmed = True
            candidate.consol_confirmed_time = candle['timestamp']

            # CRITICAL: Remove current candle from consol_candles to freeze consolidation bounds
            # This candle may be the LIQ #2 breakout, so it shouldn't be part of the consolidation range
            candidate.consol_candles.pop()  # Remove the candle we just added

            # Recalculate bounds without this candle (frozen consolidation)
            candidate.consol_high = max(c['high'] for c in candidate.consol_candles)
            candidate.consol_low = min(c['low'] for c in candidate.consol_candles)
            candidate.consol_range = candidate.consol_high - candidate.consol_low

            # Transition to WATCHING_LIQ2
            success = StateTransitionValidator.transition_to(
                candidate,
                SetupState.WATCHING_LIQ2,
                reason=f"Consolidation confirmed ({len(candidate.consol_candles)} min, quality: {candidate.consol_quality_score:.2f})"
            )

            if success:
                logger.info(
                    f"✅ Consolidation confirmed: {candidate.id[:8]} "
                    f"(range: {candidate.consol_range:.2f}, quality: {candidate.consol_quality_score:.2f})"
                )

                # CRITICAL FIX: Re-process this candle in new state!
                # This candle might also be LIQ #2 (breaking consol_high)
                logger.debug(f"Re-processing candle in WATCHING_LIQ2 state for {candidate.id[:8]}")
                return await self._update_watching_liq2(candidate, candle)

        return CandleUpdate(
            message=f"Consolidation: {len(candidate.consol_candles)} min, "
                    f"quality: {candidate.consol_quality_score:.2f}"
        )

    async def _update_watching_liq2(
        self,
        candidate: SetupCandidate,
        candle: Dict
    ) -> CandleUpdate:
        """
        Update candidate in WATCHING_LIQ2 state.

        Actions:
        - Check if price breaks consolidation high (LIQ #2)
        - Check retracement (invalidate if too far above no-wick)
        - Transition to WAITING_ENTRY if LIQ #2 detected
        - Invalidate if timeout
        """
        # Check timeout (too many candles since consolidation)
        candles_since_consol = candidate.candles_processed - len(candidate.consol_candles)
        if candles_since_consol > self.config.max_entry_wait_candles:
            StateTransitionValidator.invalidate(
                candidate,
                InvalidationReason.LIQ2_TIMEOUT
            )
            return CandleUpdate(
                setup_invalidated=True,
                candidate=candidate,
                message=f"LIQ #2 timeout ({candles_since_consol} candles)"
            )

        # Check retracement (price went too far above no-wick high)
        if candle['high'] > candidate.nowick_high + self.config.max_retracement_pips:
            StateTransitionValidator.invalidate(
                candidate,
                InvalidationReason.RETRACEMENT_EXCEEDED
            )
            return CandleUpdate(
                setup_invalidated=True,
                candidate=candidate,
                message=f"Retracement exceeded ({candle['high'] - candidate.nowick_high:.2f} pips)"
            )

        # Check if LIQ #2 (breaks consolidation high)
        if candle['high'] > candidate.consol_high:
            # LIQ #2 detected!
            candidate.liq2_detected = True
            candidate.liq2_time = candle['timestamp']
            candidate.liq2_price = candle['high']

            # Transition to WAITING_ENTRY
            success = StateTransitionValidator.transition_to(
                candidate,
                SetupState.WAITING_ENTRY,
                reason=f"LIQ #2 @ {candle['high']:.2f}"
            )

            if success:
                logger.info(
                    f"🔵 LIQ #2 detected: {candidate.id[:8]} @ {candidate.liq2_price:.2f}"
                )

        return CandleUpdate(message="Waiting for LIQ #2")

    async def _update_waiting_entry(
        self,
        candidate: SetupCandidate,
        candle: Dict
    ) -> CandleUpdate:
        """
        Update candidate in WAITING_ENTRY state.

        Actions:
        - Check if candle closes below no-wick low (entry trigger)
        - Calculate entry price (next candle open)
        - Calculate SL/TP
        - Transition to SETUP_COMPLETE
        - Invalidate if timeout
        """
        # Check timeout
        candles_since_liq2 = candidate.candles_processed - len(candidate.consol_candles) - 1
        if candles_since_liq2 > self.config.max_entry_wait_candles:
            StateTransitionValidator.invalidate(
                candidate,
                InvalidationReason.ENTRY_TIMEOUT
            )
            return CandleUpdate(
                setup_invalidated=True,
                candidate=candidate,
                message=f"Entry timeout ({candles_since_liq2} candles)"
            )

        # Check if entry trigger (close below no-wick low)
        if candle['close'] < candidate.nowick_low:
            # Entry trigger fired!
            candidate.entry_triggered = True
            candidate.entry_trigger_time = candle['timestamp']

            # Entry price = NEXT candle's open (we don't know it yet in live!)
            # For now, estimate as current close
            # In real trading, order will be placed at next open
            candidate.entry_price = candle['close']

            # Calculate SL/TP
            candidate.sl_price = candidate.liq2_price + self.config.sl_buffer_pips
            candidate.tp_price = self.lse_low - self.config.tp_buffer_pips

            # Calculate risk/reward
            risk = candidate.sl_price - candidate.entry_price
            reward = candidate.entry_price - candidate.tp_price
            candidate.risk_reward_ratio = reward / risk if risk > 0 else 0

            # Transition to SETUP_COMPLETE
            success = StateTransitionValidator.transition_to(
                candidate,
                SetupState.SETUP_COMPLETE,
                reason=f"Entry trigger @ {candle['close']:.2f}"
            )

            if success:
                logger.info(
                    f"🎯 Setup COMPLETE: {candidate.id[:8]} | "
                    f"Entry: {candidate.entry_price:.2f}, "
                    f"SL: {candidate.sl_price:.2f}, "
                    f"TP: {candidate.tp_price:.2f}, "
                    f"R:R: {candidate.risk_reward_ratio:.1f}"
                )

                return CandleUpdate(
                    setup_completed=True,
                    candidate=candidate,
                    message=f"Setup complete (R:R: {candidate.risk_reward_ratio:.1f})"
                )

        return CandleUpdate(message="Waiting for entry trigger")

    def _calculate_consolidation_quality(self, candles: List[Dict]) -> float:
        """
        Calculate consolidation quality score (0.0-1.0).

        Factors:
        - Tightness (lower range = higher score)
        - Volume compression
        - Breakout readiness

        Returns:
            Quality score 0.0-1.0
        """
        if len(candles) < 3:
            return 0.0

        # Calculate range tightness
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        range_val = max(highs) - min(lows)

        # Normalize by ATR (if available)
        if self.atr_value is not None and self.atr_value > 0:
            range_score = max(0, 1.0 - (range_val / (self.atr_value * 2.0)))
        else:
            # Fallback: use absolute range
            range_score = max(0, 1.0 - (range_val / 50.0))  # Assume 50 pips = bad

        # TODO: Add volume compression factor
        # TODO: Add breakout readiness factor

        return range_score

    def _find_nowick_in_consolidation(
        self,
        candles: List[Dict]
    ) -> Optional[Dict]:
        """
        Find no-wick candle in consolidation window.

        No-wick = Bullish candle (for SHORT) with minimal upper wick.

        Returns:
            Dict with no-wick candle info or None
        """
        # Need at least 3 candles for percentile calculation
        if len(candles) < 3:
            return None

        # Calculate percentiles for wick sizes
        upper_wicks = []
        body_sizes = []

        for c in candles:
            body_size = abs(c['close'] - c['open'])
            upper_wick = c['high'] - max(c['open'], c['close'])

            body_sizes.append(body_size)
            upper_wicks.append(upper_wick)

        # Sort for percentile calculation
        upper_wicks_sorted = sorted(upper_wicks)
        body_sizes_sorted = sorted(body_sizes)

        # Percentile thresholds
        p90_idx = int(len(upper_wicks_sorted) * 0.90)
        p30_idx = int(len(body_sizes_sorted) * 0.30)
        p70_idx = int(len(body_sizes_sorted) * 0.70)

        wick_threshold = upper_wicks_sorted[p90_idx]
        body_min = body_sizes_sorted[p30_idx]
        body_max = body_sizes_sorted[p70_idx]

        # Find bullish candle with small upper wick
        for c in candles:
            # Must be bullish (close > open)
            if c['close'] <= c['open']:
                continue

            body_size = c['close'] - c['open']
            upper_wick = c['high'] - c['close']

            # Check criteria
            if (upper_wick < wick_threshold and
                body_min <= body_size <= body_max):

                wick_ratio = upper_wick / body_size if body_size > 0 else 999

                return {
                    'timestamp': c['timestamp'],
                    'high': c['high'],
                    'low': c['low'],
                    'wick_ratio': wick_ratio
                }

        return None

    def get_stats(self) -> Dict:
        """Get tracker statistics."""
        return {
            **self.stats,
            'lse_high': self.lse_high,
            'lse_low': self.lse_low,
            'atr': self.atr_value,
            'completed_setups': len(self.completed_setups),
            'invalidated_setups': len(self.invalidated_setups)
        }

    def get_active_candidates(self) -> List[SetupCandidate]:
        """Get list of currently active candidates."""
        return list(self.active_candidates.values())
