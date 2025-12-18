"""
Setup State Machine

Defines states and transitions for incremental 5/1 SLOB setup detection in live trading.

Key design principle: NO LOOK-AHEAD BIAS
- Each state transition happens in real-time as candles arrive
- Consolidation is NOT confirmed until LIQ #2 breaks out
- All decisions use only past + current candle data

State flow:
    WATCHING_LIQ1 → WATCHING_CONSOL → WATCHING_LIQ2 → WAITING_ENTRY → SETUP_COMPLETE
                 ↓        ↓                  ↓               ↓
                 └────────┴──────────────────┴──→ INVALIDATED
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict
from uuid import uuid4


class SetupState(Enum):
    """
    States in the 5/1 SLOB setup detection state machine.

    Transitions:
        WATCHING_LIQ1 → WATCHING_CONSOL: LIQ #1 detected (NYSE breaks LSE High)
        WATCHING_CONSOL → WATCHING_LIQ2: Consolidation formed (min duration reached)
        WATCHING_LIQ2 → WAITING_ENTRY: LIQ #2 detected (breaks consolidation high)
        WAITING_ENTRY → SETUP_COMPLETE: Entry trigger fired (close below no-wick low)

        Any state → INVALIDATED: Invalidation condition met
    """

    # Initial state - waiting for LIQ #1
    WATCHING_LIQ1 = 1

    # LIQ #1 detected, accumulating consolidation candles
    WATCHING_CONSOL = 2

    # Consolidation formed, waiting for LIQ #2 breakout
    WATCHING_LIQ2 = 3

    # LIQ #2 detected, waiting for entry trigger
    WAITING_ENTRY = 4

    # Entry trigger fired - setup complete
    SETUP_COMPLETE = 5

    # Setup invalidated (timeout, retracement, etc.)
    INVALIDATED = 6


class InvalidationReason(Enum):
    """Reasons why a setup candidate gets invalidated."""

    # Consolidation never formed (timeout)
    CONSOL_TIMEOUT = "consolidation_timeout"

    # Consolidation quality too low
    CONSOL_QUALITY_LOW = "consolidation_quality_low"

    # Consolidation range too wide
    CONSOL_RANGE_TOO_WIDE = "consolidation_range_too_wide"

    # No valid no-wick candle found
    NO_WICK_NOT_FOUND = "no_wick_not_found"

    # LIQ #2 never occurred (timeout)
    LIQ2_TIMEOUT = "liq2_timeout"

    # Price retraced too far above no-wick high
    RETRACEMENT_EXCEEDED = "retracement_exceeded"

    # Entry trigger never fired (timeout)
    ENTRY_TIMEOUT = "entry_timeout"

    # Market closed before setup completed
    MARKET_CLOSED = "market_closed"


@dataclass
class SetupCandidate:
    """
    A candidate 5/1 SLOB setup being tracked in real-time.

    This class maintains ALL state for an in-progress setup detection.
    As each candle arrives, the state machine updates this object
    and potentially transitions to the next state.

    Design principle: INCREMENTAL UPDATES ONLY
    - No forward-looking
    - All fields represent what we know UP TO current candle
    - Consolidation bounds update as new candles arrive
    """

    # Unique identifier
    id: str = field(default_factory=lambda: str(uuid4()))

    # Current state
    state: SetupState = SetupState.WATCHING_LIQ1

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)

    # ─────────────────────────────────────────────────────────────
    # LSE SESSION (09:00-15:30)
    # ─────────────────────────────────────────────────────────────

    lse_high: Optional[float] = None
    lse_low: Optional[float] = None
    lse_close_time: Optional[datetime] = None

    # ─────────────────────────────────────────────────────────────
    # LIQ #1 (NYSE breaks LSE High)
    # ─────────────────────────────────────────────────────────────

    liq1_detected: bool = False
    liq1_time: Optional[datetime] = None
    liq1_price: Optional[float] = None
    liq1_confidence: Optional[float] = None

    # ─────────────────────────────────────────────────────────────
    # CONSOLIDATION (15-30 min sideways)
    # ─────────────────────────────────────────────────────────────

    # Consolidation window (accumulates as candles arrive)
    consol_candles: List[Dict] = field(default_factory=list)

    # Consolidation bounds (updated incrementally)
    consol_high: Optional[float] = None
    consol_low: Optional[float] = None
    consol_range: Optional[float] = None

    # Consolidation quality (recalculated each candle)
    consol_quality_score: Optional[float] = None

    # Consolidation confirmation (set when min duration reached + quality OK)
    consol_confirmed: bool = False
    consol_confirmed_time: Optional[datetime] = None

    # ─────────────────────────────────────────────────────────────
    # NO-WICK CANDLE (bullish with minimal upper wick)
    # ─────────────────────────────────────────────────────────────

    nowick_found: bool = False
    nowick_time: Optional[datetime] = None
    nowick_high: Optional[float] = None
    nowick_low: Optional[float] = None
    nowick_wick_ratio: Optional[float] = None

    # ─────────────────────────────────────────────────────────────
    # LIQ #2 (breaks consolidation high)
    # ─────────────────────────────────────────────────────────────

    liq2_detected: bool = False
    liq2_time: Optional[datetime] = None
    liq2_price: Optional[float] = None  # Initial breakout price

    # Spike high tracking (highest price after LIQ #2 detected)
    # This is used for SL calculation to account for spike after breakout
    spike_high: Optional[float] = None
    spike_high_time: Optional[datetime] = None

    # ─────────────────────────────────────────────────────────────
    # ENTRY TRIGGER (close below no-wick low)
    # ─────────────────────────────────────────────────────────────

    entry_triggered: bool = False
    entry_trigger_time: Optional[datetime] = None
    entry_price: Optional[float] = None

    # ─────────────────────────────────────────────────────────────
    # SL/TP
    # ─────────────────────────────────────────────────────────────

    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    risk_reward_ratio: Optional[float] = None

    # ─────────────────────────────────────────────────────────────
    # INVALIDATION
    # ─────────────────────────────────────────────────────────────

    invalidation_reason: Optional[InvalidationReason] = None
    invalidation_time: Optional[datetime] = None

    # ─────────────────────────────────────────────────────────────
    # METADATA
    # ─────────────────────────────────────────────────────────────

    symbol: str = "NQ"
    candles_processed: int = 0

    def update_timestamp(self):
        """Update last_updated timestamp."""
        self.last_updated = datetime.now()

    def is_valid(self) -> bool:
        """Check if setup is still valid (not invalidated)."""
        return self.state != SetupState.INVALIDATED

    def is_complete(self) -> bool:
        """Check if setup is complete and ready for trading."""
        return self.state == SetupState.SETUP_COMPLETE

    def get_duration_seconds(self) -> float:
        """Get total duration since candidate was created."""
        return (datetime.now() - self.created_at).total_seconds()

    def get_consol_duration_minutes(self) -> int:
        """Get consolidation duration in minutes."""
        if not self.consol_candles:
            return 0
        return len(self.consol_candles)

    def to_dict(self) -> Dict:
        """
        Convert to dict for serialization (Redis/SQLite).

        Returns:
            Dict with all setup data
        """
        return {
            'id': self.id,
            'state': self.state.name,
            'created_at': self.created_at.isoformat(),
            'last_updated': self.last_updated.isoformat(),

            # LSE
            'lse_high': self.lse_high,
            'lse_low': self.lse_low,
            'lse_close_time': self.lse_close_time.isoformat() if self.lse_close_time else None,

            # LIQ #1
            'liq1_detected': self.liq1_detected,
            'liq1_time': self.liq1_time.isoformat() if self.liq1_time else None,
            'liq1_price': self.liq1_price,
            'liq1_confidence': self.liq1_confidence,

            # Consolidation
            'consol_candles_count': len(self.consol_candles),
            'consol_high': self.consol_high,
            'consol_low': self.consol_low,
            'consol_range': self.consol_range,
            'consol_quality_score': self.consol_quality_score,
            'consol_confirmed': self.consol_confirmed,
            'consol_confirmed_time': self.consol_confirmed_time.isoformat() if self.consol_confirmed_time else None,

            # No-wick
            'nowick_found': self.nowick_found,
            'nowick_time': self.nowick_time.isoformat() if self.nowick_time else None,
            'nowick_high': self.nowick_high,
            'nowick_low': self.nowick_low,
            'nowick_wick_ratio': self.nowick_wick_ratio,

            # LIQ #2
            'liq2_detected': self.liq2_detected,
            'liq2_time': self.liq2_time.isoformat() if self.liq2_time else None,
            'liq2_price': self.liq2_price,

            # Entry
            'entry_triggered': self.entry_triggered,
            'entry_trigger_time': self.entry_trigger_time.isoformat() if self.entry_trigger_time else None,
            'entry_price': self.entry_price,

            # SL/TP
            'sl_price': self.sl_price,
            'tp_price': self.tp_price,
            'risk_reward_ratio': self.risk_reward_ratio,

            # Invalidation
            'invalidation_reason': self.invalidation_reason.value if self.invalidation_reason else None,
            'invalidation_time': self.invalidation_time.isoformat() if self.invalidation_time else None,

            # Metadata
            'symbol': self.symbol,
            'candles_processed': self.candles_processed
        }

    def __repr__(self) -> str:
        """String representation for logging."""
        return (
            f"SetupCandidate(id={self.id[:8]}, "
            f"state={self.state.name}, "
            f"liq1={self.liq1_detected}, "
            f"consol={len(self.consol_candles)}min, "
            f"liq2={self.liq2_detected}, "
            f"entry={self.entry_triggered})"
        )


class StateTransitionValidator:
    """
    Validates and executes state transitions for setup candidates.

    Ensures that all transitions follow proper rules and all required
    data is present before advancing to next state.
    """

    @staticmethod
    def can_transition_to_watching_consol(candidate: SetupCandidate) -> tuple[bool, str]:
        """
        Check if candidate can transition to WATCHING_CONSOL.

        Requirements:
        - Current state = WATCHING_LIQ1
        - LIQ #1 detected
        - LSE levels established

        Returns:
            (can_transition, reason)
        """
        if candidate.state != SetupState.WATCHING_LIQ1:
            return False, f"Invalid current state: {candidate.state.name}"

        if not candidate.liq1_detected:
            return False, "LIQ #1 not detected"

        if candidate.lse_high is None or candidate.lse_low is None:
            return False, "LSE levels not established"

        return True, "Valid"

    @staticmethod
    def can_transition_to_watching_liq2(candidate: SetupCandidate) -> tuple[bool, str]:
        """
        Check if candidate can transition to WATCHING_LIQ2.

        Requirements:
        - Current state = WATCHING_CONSOL
        - Consolidation confirmed (min duration + quality OK)
        - No-wick candle found

        Returns:
            (can_transition, reason)
        """
        if candidate.state != SetupState.WATCHING_CONSOL:
            return False, f"Invalid current state: {candidate.state.name}"

        if not candidate.consol_confirmed:
            return False, "Consolidation not confirmed"

        if not candidate.nowick_found:
            return False, "No-wick candle not found"

        if candidate.consol_high is None or candidate.consol_low is None:
            return False, "Consolidation bounds not set"

        return True, "Valid"

    @staticmethod
    def can_transition_to_waiting_entry(candidate: SetupCandidate) -> tuple[bool, str]:
        """
        Check if candidate can transition to WAITING_ENTRY.

        Requirements:
        - Current state = WATCHING_LIQ2
        - LIQ #2 detected

        Returns:
            (can_transition, reason)
        """
        if candidate.state != SetupState.WATCHING_LIQ2:
            return False, f"Invalid current state: {candidate.state.name}"

        if not candidate.liq2_detected:
            return False, "LIQ #2 not detected"

        return True, "Valid"

    @staticmethod
    def can_transition_to_setup_complete(candidate: SetupCandidate) -> tuple[bool, str]:
        """
        Check if candidate can transition to SETUP_COMPLETE.

        Requirements:
        - Current state = WAITING_ENTRY
        - Entry trigger fired
        - SL/TP calculated

        Returns:
            (can_transition, reason)
        """
        if candidate.state != SetupState.WAITING_ENTRY:
            return False, f"Invalid current state: {candidate.state.name}"

        if not candidate.entry_triggered:
            return False, "Entry trigger not fired"

        if candidate.sl_price is None or candidate.tp_price is None:
            return False, "SL/TP not calculated"

        return True, "Valid"

    @staticmethod
    def transition_to(
        candidate: SetupCandidate,
        new_state: SetupState,
        reason: Optional[str] = None
    ) -> bool:
        """
        Execute state transition with validation.

        Args:
            candidate: Setup candidate to transition
            new_state: Target state
            reason: Optional reason for transition

        Returns:
            True if transition successful, False otherwise
        """
        # Validate transition
        if new_state == SetupState.WATCHING_CONSOL:
            can_transition, msg = StateTransitionValidator.can_transition_to_watching_consol(candidate)
        elif new_state == SetupState.WATCHING_LIQ2:
            can_transition, msg = StateTransitionValidator.can_transition_to_watching_liq2(candidate)
        elif new_state == SetupState.WAITING_ENTRY:
            can_transition, msg = StateTransitionValidator.can_transition_to_waiting_entry(candidate)
        elif new_state == SetupState.SETUP_COMPLETE:
            can_transition, msg = StateTransitionValidator.can_transition_to_setup_complete(candidate)
        elif new_state == SetupState.INVALIDATED:
            # Invalidation can happen from any state
            can_transition = True
            msg = reason or "Invalidated"
        else:
            can_transition = False
            msg = f"Unknown target state: {new_state}"

        if not can_transition:
            import logging
            logger = logging.getLogger(__name__)
            # Handle invalid state types
            new_state_name = new_state.name if hasattr(new_state, 'name') else str(new_state)
            logger.warning(
                f"Invalid state transition: {candidate.state.name} → {new_state_name}. "
                f"Reason: {msg}"
            )
            return False

        # Execute transition
        old_state = candidate.state
        candidate.state = new_state
        candidate.update_timestamp()

        import logging
        logger = logging.getLogger(__name__)
        logger.info(
            f"State transition: {old_state.name} → {new_state.name} "
            f"[{candidate.id[:8]}] {msg}"
        )

        return True

    @staticmethod
    def invalidate(
        candidate: SetupCandidate,
        reason: InvalidationReason
    ):
        """
        Invalidate a setup candidate.

        Args:
            candidate: Setup candidate to invalidate
            reason: Reason for invalidation
        """
        candidate.state = SetupState.INVALIDATED
        candidate.invalidation_reason = reason
        candidate.invalidation_time = datetime.now()
        candidate.update_timestamp()

        import logging
        logger = logging.getLogger(__name__)
        logger.info(
            f"Setup invalidated: {candidate.id[:8]} - {reason.value}"
        )
