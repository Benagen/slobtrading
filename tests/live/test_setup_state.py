"""
Unit tests for Setup State Machine

Tests state transitions, validation, and SetupCandidate lifecycle.
"""

import pytest
from datetime import datetime, timedelta
from slob.live.setup_state import (
    SetupState,
    InvalidationReason,
    SetupCandidate,
    StateTransitionValidator
)


class TestSetupState:
    """Test SetupState enum."""

    def test_all_states_defined(self):
        """Test that all required states exist."""
        assert SetupState.WATCHING_LIQ1.value == 1
        assert SetupState.WATCHING_CONSOL.value == 2
        assert SetupState.WATCHING_LIQ2.value == 3
        assert SetupState.WAITING_ENTRY.value == 4
        assert SetupState.SETUP_COMPLETE.value == 5
        assert SetupState.INVALIDATED.value == 6

    def test_state_names(self):
        """Test state names are correct."""
        assert SetupState.WATCHING_LIQ1.name == "WATCHING_LIQ1"
        assert SetupState.INVALIDATED.name == "INVALIDATED"


class TestInvalidationReason:
    """Test InvalidationReason enum."""

    def test_all_reasons_defined(self):
        """Test that all invalidation reasons exist."""
        reasons = [
            InvalidationReason.CONSOL_TIMEOUT,
            InvalidationReason.CONSOL_QUALITY_LOW,
            InvalidationReason.CONSOL_RANGE_TOO_WIDE,
            InvalidationReason.NO_WICK_NOT_FOUND,
            InvalidationReason.LIQ2_TIMEOUT,
            InvalidationReason.RETRACEMENT_EXCEEDED,
            InvalidationReason.ENTRY_TIMEOUT,
            InvalidationReason.MARKET_CLOSED
        ]
        assert len(reasons) == 8

    def test_reason_values(self):
        """Test invalidation reason values."""
        assert InvalidationReason.CONSOL_TIMEOUT.value == "consolidation_timeout"
        assert InvalidationReason.MARKET_CLOSED.value == "market_closed"


class TestSetupCandidate:
    """Test SetupCandidate dataclass."""

    def test_initialization_defaults(self):
        """Test default initialization."""
        candidate = SetupCandidate()

        assert candidate.id is not None
        assert len(candidate.id) == 36  # UUID length
        assert candidate.state == SetupState.WATCHING_LIQ1
        assert candidate.symbol == "NQ"
        assert candidate.lse_high is None
        assert candidate.consol_candles == []
        assert candidate.candles_processed == 0

    def test_initialization_with_params(self):
        """Test initialization with parameters."""
        now = datetime.now()
        candidate = SetupCandidate(
            state=SetupState.WATCHING_CONSOL,
            lse_high=15300,
            lse_low=15100,
            lse_close_time=now,
            symbol="ES"
        )

        assert candidate.state == SetupState.WATCHING_CONSOL
        assert candidate.lse_high == 15300
        assert candidate.lse_low == 15100
        assert candidate.lse_close_time == now
        assert candidate.symbol == "ES"

    def test_update_timestamp(self):
        """Test update_timestamp method."""
        candidate = SetupCandidate()
        original_time = candidate.last_updated

        # Wait a tiny bit
        import time
        time.sleep(0.01)

        candidate.update_timestamp()
        assert candidate.last_updated > original_time

    def test_is_valid(self):
        """Test is_valid method."""
        candidate = SetupCandidate()
        assert candidate.is_valid() is True

        candidate.state = SetupState.SETUP_COMPLETE
        assert candidate.is_valid() is True

        candidate.state = SetupState.INVALIDATED
        assert candidate.is_valid() is False

    def test_is_complete(self):
        """Test is_complete method."""
        candidate = SetupCandidate()
        assert candidate.is_complete() is False

        candidate.state = SetupState.WAITING_ENTRY
        assert candidate.is_complete() is False

        candidate.state = SetupState.SETUP_COMPLETE
        assert candidate.is_complete() is True

    def test_get_duration_seconds(self):
        """Test get_duration_seconds method."""
        # Create candidate with past created_at
        past_time = datetime.now() - timedelta(seconds=10)
        candidate = SetupCandidate(created_at=past_time)

        duration = candidate.get_duration_seconds()
        assert duration >= 10  # At least 10 seconds
        assert duration < 15  # But not too long

    def test_get_consol_duration_minutes(self):
        """Test get_consol_duration_minutes method."""
        candidate = SetupCandidate()
        assert candidate.get_consol_duration_minutes() == 0

        # Add consolidation candles
        candidate.consol_candles = [
            {'timestamp': datetime.now(), 'high': 15310},
            {'timestamp': datetime.now(), 'high': 15315},
            {'timestamp': datetime.now(), 'high': 15312}
        ]

        assert candidate.get_consol_duration_minutes() == 3

    def test_to_dict(self):
        """Test to_dict serialization."""
        now = datetime.now()
        candidate = SetupCandidate(
            lse_high=15300,
            lse_low=15100,
            lse_close_time=now,
            state=SetupState.WATCHING_CONSOL
        )

        candidate.liq1_detected = True
        candidate.liq1_price = 15310
        candidate.liq1_time = now

        data = candidate.to_dict()

        assert data['id'] == candidate.id
        assert data['state'] == 'WATCHING_CONSOL'
        assert data['lse_high'] == 15300
        assert data['lse_low'] == 15100
        assert data['liq1_detected'] is True
        assert data['liq1_price'] == 15310
        assert data['symbol'] == 'NQ'

    def test_to_dict_with_invalidation(self):
        """Test to_dict with invalidation data."""
        candidate = SetupCandidate()
        candidate.state = SetupState.INVALIDATED
        candidate.invalidation_reason = InvalidationReason.CONSOL_TIMEOUT
        candidate.invalidation_time = datetime.now()

        data = candidate.to_dict()

        assert data['state'] == 'INVALIDATED'
        assert data['invalidation_reason'] == 'consolidation_timeout'
        assert data['invalidation_time'] is not None

    def test_repr(self):
        """Test string representation."""
        candidate = SetupCandidate()
        candidate.liq1_detected = True
        candidate.consol_candles = [{}] * 5  # 5 candles

        repr_str = repr(candidate)

        assert candidate.id[:8] in repr_str
        assert 'WATCHING_LIQ1' in repr_str
        assert 'liq1=True' in repr_str
        assert 'consol=5min' in repr_str


class TestStateTransitionValidator:
    """Test StateTransitionValidator class."""

    # ─────────────────────────────────────────────────────────────
    # WATCHING_LIQ1 → WATCHING_CONSOL
    # ─────────────────────────────────────────────────────────────

    def test_can_transition_to_watching_consol_valid(self):
        """Test valid transition to WATCHING_CONSOL."""
        candidate = SetupCandidate(
            state=SetupState.WATCHING_LIQ1,
            lse_high=15300,
            lse_low=15100,
            liq1_detected=True
        )

        can_transition, reason = StateTransitionValidator.can_transition_to_watching_consol(candidate)

        assert can_transition is True
        assert reason == "Valid"

    def test_can_transition_to_watching_consol_wrong_state(self):
        """Test transition from wrong state."""
        candidate = SetupCandidate(
            state=SetupState.WATCHING_CONSOL,  # Wrong state
            liq1_detected=True
        )

        can_transition, reason = StateTransitionValidator.can_transition_to_watching_consol(candidate)

        assert can_transition is False
        assert "Invalid current state" in reason

    def test_can_transition_to_watching_consol_no_liq1(self):
        """Test transition without LIQ #1 detected."""
        candidate = SetupCandidate(
            state=SetupState.WATCHING_LIQ1,
            lse_high=15300,
            liq1_detected=False  # Missing
        )

        can_transition, reason = StateTransitionValidator.can_transition_to_watching_consol(candidate)

        assert can_transition is False
        assert "LIQ #1 not detected" in reason

    def test_can_transition_to_watching_consol_no_lse_levels(self):
        """Test transition without LSE levels."""
        candidate = SetupCandidate(
            state=SetupState.WATCHING_LIQ1,
            liq1_detected=True,
            lse_high=None  # Missing
        )

        can_transition, reason = StateTransitionValidator.can_transition_to_watching_consol(candidate)

        assert can_transition is False
        assert "LSE levels not established" in reason

    # ─────────────────────────────────────────────────────────────
    # WATCHING_CONSOL → WATCHING_LIQ2
    # ─────────────────────────────────────────────────────────────

    def test_can_transition_to_watching_liq2_valid(self):
        """Test valid transition to WATCHING_LIQ2."""
        candidate = SetupCandidate(
            state=SetupState.WATCHING_CONSOL,
            consol_confirmed=True,
            nowick_found=True,
            consol_high=15320,
            consol_low=15295
        )

        can_transition, reason = StateTransitionValidator.can_transition_to_watching_liq2(candidate)

        assert can_transition is True
        assert reason == "Valid"

    def test_can_transition_to_watching_liq2_wrong_state(self):
        """Test transition from wrong state."""
        candidate = SetupCandidate(
            state=SetupState.WATCHING_LIQ1,  # Wrong
            consol_confirmed=True
        )

        can_transition, reason = StateTransitionValidator.can_transition_to_watching_liq2(candidate)

        assert can_transition is False
        assert "Invalid current state" in reason

    def test_can_transition_to_watching_liq2_no_consol_confirmed(self):
        """Test transition without consolidation confirmed."""
        candidate = SetupCandidate(
            state=SetupState.WATCHING_CONSOL,
            consol_confirmed=False,  # Not confirmed
            nowick_found=True
        )

        can_transition, reason = StateTransitionValidator.can_transition_to_watching_liq2(candidate)

        assert can_transition is False
        assert "Consolidation not confirmed" in reason

    def test_can_transition_to_watching_liq2_no_nowick(self):
        """Test transition without no-wick candle."""
        candidate = SetupCandidate(
            state=SetupState.WATCHING_CONSOL,
            consol_confirmed=True,
            nowick_found=False,  # Missing
            consol_high=15320,
            consol_low=15295
        )

        can_transition, reason = StateTransitionValidator.can_transition_to_watching_liq2(candidate)

        assert can_transition is False
        assert "No-wick candle not found" in reason

    # ─────────────────────────────────────────────────────────────
    # WATCHING_LIQ2 → WAITING_ENTRY
    # ─────────────────────────────────────────────────────────────

    def test_can_transition_to_waiting_entry_valid(self):
        """Test valid transition to WAITING_ENTRY."""
        candidate = SetupCandidate(
            state=SetupState.WATCHING_LIQ2,
            liq2_detected=True
        )

        can_transition, reason = StateTransitionValidator.can_transition_to_waiting_entry(candidate)

        assert can_transition is True
        assert reason == "Valid"

    def test_can_transition_to_waiting_entry_wrong_state(self):
        """Test transition from wrong state."""
        candidate = SetupCandidate(
            state=SetupState.WATCHING_CONSOL,  # Wrong
            liq2_detected=True
        )

        can_transition, reason = StateTransitionValidator.can_transition_to_waiting_entry(candidate)

        assert can_transition is False
        assert "Invalid current state" in reason

    def test_can_transition_to_waiting_entry_no_liq2(self):
        """Test transition without LIQ #2."""
        candidate = SetupCandidate(
            state=SetupState.WATCHING_LIQ2,
            liq2_detected=False  # Missing
        )

        can_transition, reason = StateTransitionValidator.can_transition_to_waiting_entry(candidate)

        assert can_transition is False
        assert "LIQ #2 not detected" in reason

    # ─────────────────────────────────────────────────────────────
    # WAITING_ENTRY → SETUP_COMPLETE
    # ─────────────────────────────────────────────────────────────

    def test_can_transition_to_setup_complete_valid(self):
        """Test valid transition to SETUP_COMPLETE."""
        candidate = SetupCandidate(
            state=SetupState.WAITING_ENTRY,
            entry_triggered=True,
            sl_price=15325,
            tp_price=15100
        )

        can_transition, reason = StateTransitionValidator.can_transition_to_setup_complete(candidate)

        assert can_transition is True
        assert reason == "Valid"

    def test_can_transition_to_setup_complete_wrong_state(self):
        """Test transition from wrong state."""
        candidate = SetupCandidate(
            state=SetupState.WATCHING_LIQ2,  # Wrong
            entry_triggered=True,
            sl_price=15325,
            tp_price=15100
        )

        can_transition, reason = StateTransitionValidator.can_transition_to_setup_complete(candidate)

        assert can_transition is False
        assert "Invalid current state" in reason

    def test_can_transition_to_setup_complete_no_entry(self):
        """Test transition without entry trigger."""
        candidate = SetupCandidate(
            state=SetupState.WAITING_ENTRY,
            entry_triggered=False,  # Missing
            sl_price=15325,
            tp_price=15100
        )

        can_transition, reason = StateTransitionValidator.can_transition_to_setup_complete(candidate)

        assert can_transition is False
        assert "Entry trigger not fired" in reason

    def test_can_transition_to_setup_complete_no_sl_tp(self):
        """Test transition without SL/TP."""
        candidate = SetupCandidate(
            state=SetupState.WAITING_ENTRY,
            entry_triggered=True,
            sl_price=None,  # Missing
            tp_price=None
        )

        can_transition, reason = StateTransitionValidator.can_transition_to_setup_complete(candidate)

        assert can_transition is False
        assert "SL/TP not calculated" in reason

    # ─────────────────────────────────────────────────────────────
    # transition_to() method
    # ─────────────────────────────────────────────────────────────

    def test_transition_to_success(self):
        """Test successful state transition."""
        candidate = SetupCandidate(
            state=SetupState.WATCHING_LIQ1,
            lse_high=15300,
            lse_low=15100,
            liq1_detected=True
        )

        success = StateTransitionValidator.transition_to(
            candidate,
            SetupState.WATCHING_CONSOL,
            reason="LIQ #1 detected"
        )

        assert success is True
        assert candidate.state == SetupState.WATCHING_CONSOL

    def test_transition_to_failure(self):
        """Test failed state transition."""
        candidate = SetupCandidate(
            state=SetupState.WATCHING_LIQ1,
            liq1_detected=False  # Invalid - missing LIQ #1
        )

        original_state = candidate.state

        success = StateTransitionValidator.transition_to(
            candidate,
            SetupState.WATCHING_CONSOL
        )

        assert success is False
        assert candidate.state == original_state  # State unchanged

    def test_transition_to_invalidated_always_allowed(self):
        """Test that transition to INVALIDATED is always allowed."""
        # From any state
        for state in [SetupState.WATCHING_LIQ1, SetupState.WATCHING_CONSOL,
                      SetupState.WATCHING_LIQ2, SetupState.WAITING_ENTRY]:
            candidate = SetupCandidate(state=state)

            success = StateTransitionValidator.transition_to(
                candidate,
                SetupState.INVALIDATED,
                reason="Test invalidation"
            )

            assert success is True
            assert candidate.state == SetupState.INVALIDATED

    def test_transition_to_unknown_state(self):
        """Test transition to unknown state fails."""
        candidate = SetupCandidate()

        # This should fail (unknown target state)
        success = StateTransitionValidator.transition_to(
            candidate,
            999  # Invalid state
        )

        assert success is False

    # ─────────────────────────────────────────────────────────────
    # invalidate() method
    # ─────────────────────────────────────────────────────────────

    def test_invalidate(self):
        """Test invalidate method."""
        candidate = SetupCandidate(state=SetupState.WATCHING_CONSOL)

        StateTransitionValidator.invalidate(
            candidate,
            InvalidationReason.CONSOL_TIMEOUT
        )

        assert candidate.state == SetupState.INVALIDATED
        assert candidate.invalidation_reason == InvalidationReason.CONSOL_TIMEOUT
        assert candidate.invalidation_time is not None

    def test_invalidate_from_any_state(self):
        """Test that invalidate works from any state."""
        for state in [SetupState.WATCHING_LIQ1, SetupState.WATCHING_CONSOL,
                      SetupState.WATCHING_LIQ2, SetupState.WAITING_ENTRY]:
            candidate = SetupCandidate(state=state)

            StateTransitionValidator.invalidate(
                candidate,
                InvalidationReason.MARKET_CLOSED
            )

            assert candidate.state == SetupState.INVALIDATED
            assert candidate.invalidation_reason == InvalidationReason.MARKET_CLOSED


class TestSetupCandidateLifecycle:
    """Test complete setup candidate lifecycle."""

    def test_full_lifecycle_success(self):
        """Test successful full lifecycle from WATCHING_LIQ1 to SETUP_COMPLETE."""
        now = datetime.now()

        # 1. Initial state
        candidate = SetupCandidate(
            lse_high=15300,
            lse_low=15100,
            lse_close_time=now,
            state=SetupState.WATCHING_LIQ1
        )

        assert candidate.state == SetupState.WATCHING_LIQ1

        # 2. LIQ #1 detected
        candidate.liq1_detected = True
        candidate.liq1_price = 15310
        candidate.liq1_time = now + timedelta(minutes=15)

        success = StateTransitionValidator.transition_to(
            candidate,
            SetupState.WATCHING_CONSOL
        )
        assert success is True
        assert candidate.state == SetupState.WATCHING_CONSOL

        # 3. Consolidation formed
        candidate.consol_candles = [{'high': 15315}] * 15  # 15 candles
        candidate.consol_high = 15320
        candidate.consol_low = 15295
        candidate.consol_confirmed = True
        candidate.nowick_found = True
        candidate.nowick_high = 15305
        candidate.nowick_low = 15300

        success = StateTransitionValidator.transition_to(
            candidate,
            SetupState.WATCHING_LIQ2
        )
        assert success is True
        assert candidate.state == SetupState.WATCHING_LIQ2

        # 4. LIQ #2 detected
        candidate.liq2_detected = True
        candidate.liq2_price = 15325
        candidate.liq2_time = now + timedelta(minutes=35)

        success = StateTransitionValidator.transition_to(
            candidate,
            SetupState.WAITING_ENTRY
        )
        assert success is True
        assert candidate.state == SetupState.WAITING_ENTRY

        # 5. Entry trigger
        candidate.entry_triggered = True
        candidate.entry_price = 15304
        candidate.sl_price = 15325
        candidate.tp_price = 15100

        success = StateTransitionValidator.transition_to(
            candidate,
            SetupState.SETUP_COMPLETE
        )
        assert success is True
        assert candidate.state == SetupState.SETUP_COMPLETE
        assert candidate.is_complete() is True

    def test_lifecycle_with_invalidation(self):
        """Test lifecycle that ends in invalidation."""
        candidate = SetupCandidate(
            state=SetupState.WATCHING_CONSOL,
            liq1_detected=True,
            consol_candles=[{}] * 35  # Too long!
        )

        # Invalidate due to timeout
        StateTransitionValidator.invalidate(
            candidate,
            InvalidationReason.CONSOL_TIMEOUT
        )

        assert candidate.state == SetupState.INVALIDATED
        assert candidate.is_valid() is False
        assert candidate.is_complete() is False
