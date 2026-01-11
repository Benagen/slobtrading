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
from collections import deque
from typing import Dict, List, Optional, Tuple, Deque
from datetime import datetime, time, timedelta, timezone
from dataclasses import dataclass

from .setup_state import (
    SetupState,
    SetupCandidate,
    StateTransitionValidator,
    InvalidationReason,
    TradeDirection
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
    consol_max_duration: int = 120  # minutes (strategy: 15-120 min)
    consol_min_range_pct: float = 0.1  # minimum range percentage (0.1%)
    consol_max_range_pct: float = 0.5  # maximum range percentage (0.5%) - Q18 answer

    # LIQ #2 timing (Q4 answer)
    liq2_minimum_wait_minutes: int = 5  # Minimum wait from consol confirmation to LIQ #2

    # ATR parameters (for statistics only, not validation)
    atr_period: int = 14

    # No-wick parameters (using fixed 20% threshold for backtest alignment)

    # Entry parameters
    max_entry_wait_candles: int = 20  # max candles to wait for entry
    max_retracement_pips: float = 100.0  # max retracement above no-wick high

    # Risk parameters
    sl_buffer_pips: float = 1.0  # buffer above LIQ #2 high for SL
    tp_buffer_pips: float = 1.0  # buffer below LSE Low for TP

    # Spike rule parameters
    spike_rule_buffer_pips: float = 2.0  # Buffer above LIQ #2 body for SL (spike detection)

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
        # Use deque with maxlen for O(1) rolling window (auto-evicts oldest)
        self.recent_candles: Deque[Dict] = deque(maxlen=self.config.atr_period + 1)
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
            # Log periodically (every 10 candles) to confirm tracking
            # Note: recent_candles maxlen is atr_period+1 (typically 15), so use % 10
            if len(self.recent_candles) % 10 == 0:
                logger.info(f"📊 LSE session tracking: High={self.lse_high:.2f}, Low={self.lse_low:.2f}")
            return CandleUpdate(message="LSE session - tracking levels")

        # NYSE Session: Track setups
        elif self._is_nyse_session(timestamp):
            # Check if LSE levels established
            if self.lse_high is None or self.lse_low is None:
                return CandleUpdate(message="NYSE session - waiting for LSE levels")

            # Check for new LIQ #1 (create new candidate)
            direction = self._check_for_liq1(candle)
            if direction:
                candidate = self._create_candidate_from_liq1(candle, direction)
                self.active_candidates[candidate.id] = candidate
                self.stats['liq1_detected'] += 1
                self.stats['candidates_active'] = len(self.active_candidates)

                if direction == TradeDirection.SHORT:
                    logger.info(
                        f"🔵 LIQ #1 SHORT detected @ {timestamp.strftime('%H:%M')} "
                        f"(break up: {candle['high']:.2f}, LSE High: {self.lse_high:.2f})"
                    )
                else:  # LONG
                    logger.info(
                        f"🔵 LIQ #1 LONG detected @ {timestamp.strftime('%H:%M')} "
                        f"(break down: {candle['low']:.2f}, LSE Low: {self.lse_low:.2f})"
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
        """Check if timestamp is in LSE session (09:00-15:30 UTC)."""
        # Convert to UTC first to ensure correct comparison
        if timestamp.tzinfo is not None:
            utc_time = timestamp.astimezone(timezone.utc).time()
        else:
            # Assume naive timestamps are already UTC
            utc_time = timestamp.time()
        return self.config.lse_open <= utc_time < self.config.lse_close

    def _is_nyse_session(self, timestamp: datetime) -> bool:
        """Check if timestamp is in NYSE session (>=15:30 UTC)."""
        # Convert to UTC first to ensure correct comparison
        if timestamp.tzinfo is not None:
            utc_time = timestamp.astimezone(timezone.utc).time()
        else:
            # Assume naive timestamps are already UTC
            utc_time = timestamp.time()
        return utc_time >= self.config.nyse_open

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
        # Deque automatically evicts oldest when maxlen exceeded (O(1))
        self.recent_candles.append(candle)

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

    def _check_for_liq1(self, candle: Dict) -> Optional[TradeDirection]:
        """
        Check if current candle is a LIQ #1 (breaks LSE High or Low).

        Returns:
            TradeDirection.SHORT if breaks LSE High (reversal down expected)
            TradeDirection.LONG if breaks LSE Low (reversal up expected)
            None if no breakout detected
        """
        # Check for SHORT setup: Break ABOVE LSE High
        if candle['high'] > self.lse_high:
            # Check if we already have a SHORT candidate too recently
            for candidate in self.active_candidates.values():
                if candidate.direction == TradeDirection.SHORT and candidate.state == SetupState.WATCHING_CONSOL:
                    time_diff = (candle['timestamp'] - candidate.liq1_time).total_seconds() / 60
                    if time_diff < 5:
                        return None
            return TradeDirection.SHORT

        # Check for LONG setup: Break BELOW LSE Low
        if candle['low'] < self.lse_low:
            # Check if we already have a LONG candidate too recently
            for candidate in self.active_candidates.values():
                if candidate.direction == TradeDirection.LONG and candidate.state == SetupState.WATCHING_CONSOL:
                    time_diff = (candle['timestamp'] - candidate.liq1_time).total_seconds() / 60
                    if time_diff < 5:
                        return None
            return TradeDirection.LONG

        return None

    def _create_candidate_from_liq1(self, candle: Dict, direction: TradeDirection) -> SetupCandidate:
        """Create new setup candidate from LIQ #1 detection."""
        candidate = SetupCandidate(
            symbol=self.config.symbol,
            direction=direction,
            lse_high=self.lse_high,
            lse_low=self.lse_low,
            lse_close_time=self.lse_close_time,
            state=SetupState.WATCHING_LIQ1
        )

        # Mark LIQ #1 detected
        candidate.liq1_detected = True
        candidate.liq1_time = candle['timestamp']

        # Set LIQ #1 price based on direction
        if direction == TradeDirection.SHORT:
            candidate.liq1_price = candle['high']  # Break above LSE high
        else:  # LONG
            candidate.liq1_price = candle['low']   # Break below LSE low

        candidate.liq1_confidence = self._calculate_liq1_confidence(candle)

        # Transition to WATCHING_CONSOL
        StateTransitionValidator.transition_to(
            candidate,
            SetupState.WATCHING_CONSOL,
            reason=f"LIQ #1 {direction.value} @ {candidate.liq1_price:.2f}"
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

        # Check if min duration reached
        if len(candidate.consol_candles) >= self.config.consol_min_duration:
            # Validate range percentage (CORRECT validation per strategy spec)
            if not self._validate_consolidation_range(
                candidate.consol_high,
                candidate.consol_low
            ):
                range_pct = ((candidate.consol_high - candidate.consol_low) /
                             candidate.consol_high) * 100
                StateTransitionValidator.invalidate(
                    candidate,
                    InvalidationReason.CONSOL_RANGE_INVALID
                )
                return CandleUpdate(
                    setup_invalidated=True,
                    candidate=candidate,
                    message=f"Range {range_pct:.3f}% invalid "
                           f"(must be {self.config.consol_min_range_pct}-"
                           f"{self.config.consol_max_range_pct}%)"
                )

            # Set quality score for backward compatibility
            candidate.consol_quality_score = 1.0

            # Find no-wick candle based on direction
            nowick = self._find_nowick_in_consolidation(candidate.consol_candles, candidate.direction)

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

        # Check retracement based on direction (Q15 answer: min(100 pips, 1% of price))
        if candidate.direction == TradeDirection.SHORT:
            # SHORT: Check if price went too far above no-wick high
            # Dynamic limit: min(100 pips, 1% of current price) - whichever is stricter
            current_price = candle['high']
            max_retracement = min(self.config.max_retracement_pips, current_price * 0.01)

            if candle['high'] > candidate.nowick_high + max_retracement:
                StateTransitionValidator.invalidate(
                    candidate,
                    InvalidationReason.RETRACEMENT_EXCEEDED
                )
                return CandleUpdate(
                    setup_invalidated=True,
                    candidate=candidate,
                    message=f"Retracement exceeded: {candle['high']:.2f} > {candidate.nowick_high + max_retracement:.2f}"
                )
        else:  # LONG
            # LONG: Check if price went too far below no-wick low
            # Dynamic limit: min(100 pips, 1% of current price) - whichever is stricter
            current_price = candle['low']
            max_retracement = min(self.config.max_retracement_pips, current_price * 0.01)

            if candle['low'] < candidate.nowick_low - max_retracement:
                StateTransitionValidator.invalidate(
                    candidate,
                    InvalidationReason.RETRACEMENT_EXCEEDED
                )
                return CandleUpdate(
                    setup_invalidated=True,
                    candidate=candidate,
                    message=f"Retracement exceeded: {candle['low']:.2f} < {candidate.nowick_low - max_retracement:.2f}"
                )

        # Check 5-minute minimum wait before allowing LIQ #2 (Q4 answer)
        if candidate.consol_confirmed_time is not None:
            minutes_since_consol = (candle['timestamp'] - candidate.consol_confirmed_time).total_seconds() / 60

            if minutes_since_consol < self.config.liq2_minimum_wait_minutes:
                return CandleUpdate(
                    message=f"Waiting for {self.config.liq2_minimum_wait_minutes}-min minimum "
                           f"(elapsed: {minutes_since_consol:.1f} min)"
                )

        # Check if LIQ #2 based on direction
        liq2_detected = False
        liq2_price = None

        if candidate.direction == TradeDirection.SHORT:
            # SHORT: Break ABOVE consolidation high
            if candle['high'] > candidate.consol_high:
                liq2_detected = True
                liq2_price = candle['high']
        else:  # LONG
            # LONG: Break BELOW consolidation low
            if candle['low'] < candidate.consol_low:
                liq2_detected = True
                liq2_price = candle['low']

        if liq2_detected:
            # LIQ #2 detected!
            candidate.liq2_detected = True
            candidate.liq2_time = candle['timestamp']
            candidate.liq2_price = liq2_price

            # Store LIQ #2 candle OHLC for spike rule calculation
            candidate.liq2_candle = {
                'open': candle['open'],
                'high': candle['high'],
                'low': candle['low'],
                'close': candle['close']
            }

            # Initialize spike tracking (will be updated in WAITING_ENTRY)
            if candidate.direction == TradeDirection.SHORT:
                candidate.spike_high = candle['high']
                candidate.spike_high_time = candle['timestamp']
            else:  # LONG
                candidate.spike_low = candle['low']
                candidate.spike_low_time = candle['timestamp']

            # Transition to WAITING_ENTRY
            success = StateTransitionValidator.transition_to(
                candidate,
                SetupState.WAITING_ENTRY,
                reason=f"LIQ #2 {candidate.direction.value} @ {liq2_price:.2f}"
            )

            if success:
                logger.info(
                    f"🔵 LIQ #2 {candidate.direction.value} detected: {candidate.id[:8]} @ {candidate.liq2_price:.2f}"
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
        - Update spike high (track highest price after LIQ #2)
        - Check if candle closes below no-wick low (entry trigger)
        - Calculate entry price (next candle open)
        - Calculate SL/TP (using spike high, not just LIQ #2 price)
        - Transition to SETUP_COMPLETE
        - Invalidate if timeout
        """
        # Update spike high/low based on direction (track for SL calculation)
        if candidate.direction == TradeDirection.SHORT:
            if candle['high'] > candidate.spike_high:
                candidate.spike_high = candle['high']
                candidate.spike_high_time = candle['timestamp']
                logger.debug(
                    f"Spike high updated: {candidate.id[:8]} @ {candidate.spike_high:.2f}"
                )
        else:  # LONG
            if candle['low'] < candidate.spike_low:
                candidate.spike_low = candle['low']
                candidate.spike_low_time = candle['timestamp']
                logger.debug(
                    f"Spike low updated: {candidate.id[:8]} @ {candidate.spike_low:.2f}"
                )

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

        # Check if entry trigger based on direction
        entry_triggered = False
        if candidate.direction == TradeDirection.SHORT:
            # SHORT: close below no-wick low
            entry_triggered = candle['close'] < candidate.nowick_low
        else:  # LONG
            # LONG: close above no-wick high
            entry_triggered = candle['close'] > candidate.nowick_high

        if entry_triggered:
            # Entry trigger fired!
            candidate.entry_triggered = True
            candidate.entry_trigger_time = candle['timestamp']

            # Entry price = NEXT candle's open (we don't know it yet in live!)
            # For now, estimate as current close
            # In real trading, order will be placed at next open
            candidate.entry_price = candle['close']

            # Calculate SL/TP based on direction
            liq2_candle = candidate.liq2_candle
            body = abs(liq2_candle['close'] - liq2_candle['open'])

            if candidate.direction == TradeDirection.SHORT:
                # SHORT: Calculate SL using spike rule (backtest alignment)
                upper_wick = liq2_candle['high'] - max(liq2_candle['close'], liq2_candle['open'])

                # Apply spike rule: if upper wick > 2x body, use body top instead of spike high
                if upper_wick > 2 * body and body > 0:
                    # Spike detected - use body top + buffer (backtest alignment)
                    body_top = max(liq2_candle['close'], liq2_candle['open'])
                    candidate.sl_price = body_top + self.config.spike_rule_buffer_pips
                    logger.info(f"SHORT Spike rule: body_top {body_top:.2f} + {self.config.spike_rule_buffer_pips:.1f} = {candidate.sl_price:.2f}")
                else:
                    # Normal candle - use spike high + buffer
                    candidate.sl_price = candidate.spike_high + self.config.sl_buffer_pips
                    logger.info(f"SHORT SL: spike_high {candidate.spike_high:.2f} + {self.config.sl_buffer_pips:.1f} = {candidate.sl_price:.2f}")

                # SHORT: TP at LSE low
                candidate.tp_price = self.lse_low - self.config.tp_buffer_pips

                # Calculate risk/reward for SHORT
                risk = candidate.sl_price - candidate.entry_price
                reward = candidate.entry_price - candidate.tp_price

            else:  # LONG
                # LONG: Calculate SL using spike rule (inverted)
                lower_wick = min(liq2_candle['close'], liq2_candle['open']) - liq2_candle['low']

                # Apply spike rule: if lower wick > 2x body, use body bottom instead of spike low
                if lower_wick > 2 * body and body > 0:
                    # Spike detected - use body bottom - buffer (backtest alignment)
                    body_bottom = min(liq2_candle['close'], liq2_candle['open'])
                    candidate.sl_price = body_bottom - self.config.spike_rule_buffer_pips
                    logger.info(f"LONG Spike rule: body_bottom {body_bottom:.2f} - {self.config.spike_rule_buffer_pips:.1f} = {candidate.sl_price:.2f}")
                else:
                    # Normal candle - use spike low - buffer
                    candidate.sl_price = candidate.spike_low - self.config.sl_buffer_pips
                    logger.info(f"LONG SL: spike_low {candidate.spike_low:.2f} - {self.config.sl_buffer_pips:.1f} = {candidate.sl_price:.2f}")

                # LONG: TP at LSE high
                candidate.tp_price = self.lse_high + self.config.tp_buffer_pips

                # Calculate risk/reward for LONG
                risk = candidate.entry_price - candidate.sl_price
                reward = candidate.tp_price - candidate.entry_price

            candidate.risk_reward_ratio = reward / risk if risk > 0 else 0

            # Filter negative R:R setups (Q16 answer: "ta trades som ger positiv R:R")
            if candidate.risk_reward_ratio <= 0:
                logger.warning(
                    f"Negative R:R filtered: {candidate.id[:8]} "
                    f"R:R={candidate.risk_reward_ratio:.2f}"
                )

                StateTransitionValidator.invalidate(
                    candidate,
                    InvalidationReason.NEGATIVE_RISK_REWARD
                )

                return CandleUpdate(
                    setup_invalidated=True,
                    candidate=candidate,
                    message=f"Negative R:R filtered: {candidate.risk_reward_ratio:.2f}"
                )

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

    def _validate_consolidation_range(self, consol_high: float, consol_low: float) -> bool:
        """
        Validate consolidation range using PERCENTAGE-based limits.

        Strategy requirement: Range must be 0.1% to 0.3% of price.
        This is the CORRECT validation per strategy creator interview.

        Old ATR-based formula was WRONG and caused 100% failure rate.

        Args:
            consol_high: Consolidation high price
            consol_low: Consolidation low price

        Returns:
            True if range is within percentage limits
        """
        if consol_high <= 0 or consol_low <= 0:
            return False

        # Calculate percentage range
        range_pct = ((consol_high - consol_low) / consol_high) * 100

        # Validate against limits (0.1-0.3%)
        is_valid = (self.config.consol_min_range_pct <= range_pct <=
                    self.config.consol_max_range_pct)

        self.logger.debug(
            f"Consolidation range: {consol_high:.2f} - {consol_low:.2f} = "
            f"{range_pct:.3f}% | Valid: {is_valid}"
        )

        return is_valid

    def _find_nowick_in_consolidation(
        self,
        candles: List[Dict],
        direction: TradeDirection
    ) -> Optional[Dict]:
        """
        Find no-wick candle using FIXED 20% threshold.
        Aligned with backtest for consistency.

        For SHORT: Bullish candle, upper wick < 20% of body
        For LONG: Bearish candle, lower wick < 20% of body

        Returns:
            Dict with no-wick candle info or None
        """
        if len(candles) < 3:
            return None

        MAX_WICK_RATIO = 0.20  # Fixed threshold (backtest alignment)

        # Find candle based on direction
        for c in candles:
            body_size = abs(c['close'] - c['open'])

            # Skip candles with no body
            if body_size <= 0:
                continue

            if direction == TradeDirection.SHORT:
                # SHORT: Bullish candle with small upper wick
                if c['close'] <= c['open']:
                    continue

                upper_wick = c['high'] - c['close']
                wick_ratio = upper_wick / body_size

                if wick_ratio < MAX_WICK_RATIO:
                    self.logger.debug(
                        f"No-wick found (SHORT): body={body_size:.2f}, "
                        f"wick={upper_wick:.2f}, ratio={wick_ratio:.2%}"
                    )
                    return {
                        'timestamp': c['timestamp'],
                        'high': c['high'],
                        'low': c['low'],
                        'wick_ratio': wick_ratio
                    }

            else:  # LONG
                # LONG: Bearish candle with small lower wick
                if c['close'] >= c['open']:
                    continue

                lower_wick = c['open'] - c['low']
                wick_ratio = lower_wick / body_size

                if wick_ratio < MAX_WICK_RATIO:
                    self.logger.debug(
                        f"No-wick found (LONG): body={body_size:.2f}, "
                        f"wick={lower_wick:.2f}, ratio={wick_ratio:.2%}"
                    )
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
