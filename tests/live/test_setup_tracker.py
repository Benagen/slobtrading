"""
Unit tests for SetupTracker

Tests real-time setup detection with NO look-ahead bias.
"""

import pytest
from datetime import datetime, time, timedelta
from slob.live.setup_tracker import SetupTracker, SetupTrackerConfig
from slob.live.setup_state import SetupState


@pytest.fixture
def config():
    """Test configuration."""
    return SetupTrackerConfig(
        lse_open=time(9, 0),
        lse_close=time(15, 30),
        nyse_open=time(15, 30),
        consol_min_duration=3,  # Lower for testing
        consol_max_duration=10,
        consol_min_quality=0.4,
        max_entry_wait_candles=5
    )


@pytest.fixture
def tracker(config):
    """Setup tracker instance."""
    return SetupTracker(config)


def create_candle(timestamp, open_price, high, low, close, volume=1000):
    """Helper to create candle dict."""
    return {
        'timestamp': timestamp,
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    }


class TestSetupTrackerInitialization:
    """Test SetupTracker initialization."""

    def test_initialization_defaults(self):
        """Test default initialization."""
        tracker = SetupTracker()

        assert tracker.config is not None
        assert tracker.lse_high is None
        assert tracker.lse_low is None
        assert len(tracker.active_candidates) == 0
        assert len(tracker.completed_setups) == 0
        assert tracker.stats['candles_processed'] == 0

    def test_initialization_with_config(self, config):
        """Test initialization with custom config."""
        tracker = SetupTracker(config)

        assert tracker.config.consol_min_duration == 3
        assert tracker.config.symbol == "NQ"


class TestLSESessionTracking:
    """Test LSE session level tracking."""

    @pytest.mark.asyncio
    async def test_lse_high_low_tracking(self, tracker):
        """Test that LSE High/Low are tracked correctly."""
        base_time = datetime(2024, 1, 15, 9, 0)  # 09:00

        # Feed LSE session candles
        for i in range(10):
            candle = create_candle(
                base_time + timedelta(minutes=i),
                15290 + i,  # open
                15300 + i,  # high
                15280 + i,  # low
                15295 + i,  # close
            )
            await tracker.on_candle(candle)

        # Verify LSE levels
        assert tracker.lse_high == 15309  # Max high
        assert tracker.lse_low == 15280  # Min low

    @pytest.mark.asyncio
    async def test_lse_session_detection(self, tracker):
        """Test LSE session time detection."""
        # LSE session
        lse_time = datetime(2024, 1, 15, 10, 30)
        assert tracker._is_lse_session(lse_time) is True

        # NYSE session
        nyse_time = datetime(2024, 1, 15, 16, 0)
        assert tracker._is_lse_session(nyse_time) is False

        # After hours
        after_time = datetime(2024, 1, 15, 23, 0)
        assert tracker._is_lse_session(after_time) is False


class TestLIQ1Detection:
    """Test LIQ #1 detection."""

    @pytest.mark.asyncio
    async def test_liq1_creates_candidate(self, tracker):
        """Test that LIQ #1 detection creates a new candidate."""
        # Set up LSE levels
        tracker.lse_high = 15300
        tracker.lse_low = 15100
        tracker.lse_close_time = datetime(2024, 1, 15, 15, 30)
        tracker.current_date = datetime(2024, 1, 15).date()

        # Feed NYSE candle that breaks LSE High
        liq1_time = datetime(2024, 1, 15, 15, 45)
        candle = create_candle(liq1_time, 15295, 15320, 15290, 15305)

        result = await tracker.on_candle(candle)

        # Should create candidate
        assert len(tracker.active_candidates) == 1
        assert tracker.stats['liq1_detected'] == 1

        # Check candidate state
        candidate = list(tracker.active_candidates.values())[0]
        assert candidate.state == SetupState.WATCHING_CONSOL
        assert candidate.liq1_detected is True
        assert candidate.liq1_price == 15320

    @pytest.mark.asyncio
    async def test_liq1_not_detected_below_lse_high(self, tracker):
        """Test that candles below LSE High don't trigger LIQ #1."""
        tracker.lse_high = 15300
        tracker.lse_low = 15100
        tracker.current_date = datetime(2024, 1, 15).date()

        # Feed candle that DOESN'T break LSE High
        candle = create_candle(
            datetime(2024, 1, 15, 15, 45),
            15290, 15295, 15285, 15290  # high=15295 < LSE High
        )

        result = await tracker.on_candle(candle)

        # Should NOT create candidate
        assert len(tracker.active_candidates) == 0
        assert tracker.stats['liq1_detected'] == 0


class TestConsolidationTracking:
    """Test incremental consolidation tracking."""

    @pytest.mark.asyncio
    async def test_consolidation_bounds_update_incrementally(self):
        """Test that consolidation bounds update as candles arrive."""
        # Use permissive config (no quality/timeout checks for this test)
        config = SetupTrackerConfig(
            consol_min_duration=10,  # Higher than test candles
            consol_min_quality=0.0,  # Disable quality check
            consol_max_duration=20
        )
        tracker = SetupTracker(config)

        # Setup: Create candidate in WATCHING_CONSOL
        tracker.lse_high = 15300
        tracker.lse_low = 15100
        tracker.current_date = datetime(2024, 1, 15).date()

        # Trigger LIQ #1
        liq1_time = datetime(2024, 1, 15, 15, 45)
        await tracker.on_candle(create_candle(liq1_time, 15295, 15320, 15290, 15305))

        candidate = list(tracker.active_candidates.values())[0]

        # Feed consolidation candles
        base_time = datetime(2024, 1, 15, 15, 46)
        for i in range(5):
            candle = create_candle(
                base_time + timedelta(minutes=i),
                15305,
                15310 + i,  # Gradually increasing high
                15300 - i,  # Gradually decreasing low
                15305
            )
            await tracker.on_candle(candle)

        # Verify bounds updated incrementally
        assert candidate.consol_high == 15314  # Max high from 5 candles
        assert candidate.consol_low == 15296  # Min low from 5 candles
        assert len(candidate.consol_candles) == 5

    @pytest.mark.asyncio
    async def test_consolidation_timeout_invalidation(self, tracker, config):
        """Test that consolidation timeout invalidates setup."""
        tracker.lse_high = 15300
        tracker.lse_low = 15100
        tracker.current_date = datetime(2024, 1, 15).date()

        # Trigger LIQ #1
        await tracker.on_candle(create_candle(
            datetime(2024, 1, 15, 15, 45),
            15295, 15320, 15290, 15305
        ))

        # Feed too many consolidation candles (exceed max_duration)
        # Use candles BELOW LSE High to avoid triggering new LIQ #1
        base_time = datetime(2024, 1, 15, 15, 46)
        invalidation_found = False
        for i in range(config.consol_max_duration + 2):
            result = await tracker.on_candle(create_candle(
                base_time + timedelta(minutes=i),
                15295, 15298, 15290, 15295
            ))
            if result.setup_invalidated:
                invalidation_found = True

        # Should be invalidated
        assert invalidation_found is True
        assert len(tracker.active_candidates) == 0
        assert len(tracker.invalidated_setups) == 1

    @pytest.mark.asyncio
    async def test_consolidation_quality_calculation(self, tracker):
        """Test consolidation quality score calculation."""
        tracker.lse_high = 15300
        tracker.lse_low = 15100
        tracker.current_date = datetime(2024, 1, 15).date()
        tracker.atr_value = 25.0  # Set ATR

        # Trigger LIQ #1
        await tracker.on_candle(create_candle(
            datetime(2024, 1, 15, 15, 45),
            15295, 15320, 15290, 15305
        ))

        candidate = list(tracker.active_candidates.values())[0]

        # Feed tight consolidation (high quality)
        base_time = datetime(2024, 1, 15, 15, 46)
        for i in range(5):
            await tracker.on_candle(create_candle(
                base_time + timedelta(minutes=i),
                15305, 15308, 15302, 15305  # Tight range
            ))

        # Quality should be high (tight range relative to ATR)
        assert candidate.consol_quality_score >= 0.5


class TestNoWickDetection:
    """Test no-wick candle detection."""

    @pytest.mark.asyncio
    async def test_nowick_found_in_consolidation(self, tracker, config):
        """Test that no-wick candle is detected in consolidation."""
        tracker.lse_high = 15300
        tracker.lse_low = 15100
        tracker.current_date = datetime(2024, 1, 15).date()

        # Trigger LIQ #1
        await tracker.on_candle(create_candle(
            datetime(2024, 1, 15, 15, 45),
            15295, 15320, 15290, 15305
        ))

        # Feed consolidation with bullish candles (some with small wicks)
        base_time = datetime(2024, 1, 15, 15, 46)
        for i in range(config.consol_min_duration):
            if i == 2:
                # Create bullish no-wick candle
                await tracker.on_candle(create_candle(
                    base_time + timedelta(minutes=i),
                    15302,  # open
                    15307,  # high (close = high, minimal upper wick)
                    15302,  # low
                    15307   # close
                ))
            else:
                await tracker.on_candle(create_candle(
                    base_time + timedelta(minutes=i),
                    15305, 15310, 15300, 15305
                ))

        candidate = list(tracker.active_candidates.values())[0]

        # Should find no-wick
        assert candidate.nowick_found is True
        assert candidate.nowick_high is not None


class TestLIQ2Detection:
    """Test LIQ #2 detection."""

    @pytest.mark.asyncio
    async def test_liq2_detected_on_breakout(self, tracker, config):
        """Test that LIQ #2 is detected when price breaks consolidation high."""
        # Setup: Get candidate to WATCHING_LIQ2 state
        tracker.lse_high = 15300
        tracker.lse_low = 15100
        tracker.current_date = datetime(2024, 1, 15).date()

        # LIQ #1
        await tracker.on_candle(create_candle(
            datetime(2024, 1, 15, 15, 45),
            15295, 15320, 15290, 15305
        ))

        # Consolidation (min duration with no-wick)
        base_time = datetime(2024, 1, 15, 15, 46)
        for i in range(config.consol_min_duration):
            if i == 1:
                # No-wick candle
                await tracker.on_candle(create_candle(
                    base_time + timedelta(minutes=i),
                    15302, 15307, 15302, 15307
                ))
            else:
                await tracker.on_candle(create_candle(
                    base_time + timedelta(minutes=i),
                    15305, 15310, 15300, 15305
                ))

        candidate = list(tracker.active_candidates.values())[0]

        # Should be in WATCHING_LIQ2 state
        assert candidate.state == SetupState.WATCHING_LIQ2

        # Feed LIQ #2 (breaks consolidation high=15310)
        liq2_time = base_time + timedelta(minutes=config.consol_min_duration + 1)
        result = await tracker.on_candle(create_candle(
            liq2_time,
            15312, 15325, 15310, 15320  # high=15325 breaks 15310
        ))

        # Should transition to WAITING_ENTRY
        assert candidate.state == SetupState.WAITING_ENTRY
        assert candidate.liq2_detected is True
        assert candidate.liq2_price == 15325


class TestEntryTrigger:
    """Test entry trigger detection."""

    @pytest.mark.asyncio
    async def test_entry_trigger_on_close_below_nowick(self, tracker, config):
        """Test that entry trigger fires when candle closes below no-wick low."""
        # Setup: Get to WAITING_ENTRY state
        tracker.lse_high = 15300
        tracker.lse_low = 15100
        tracker.current_date = datetime(2024, 1, 15).date()

        # LIQ #1
        await tracker.on_candle(create_candle(
            datetime(2024, 1, 15, 15, 45),
            15295, 15320, 15290, 15305
        ))

        # Consolidation with no-wick
        base_time = datetime(2024, 1, 15, 15, 46)
        for i in range(config.consol_min_duration):
            if i == 1:
                await tracker.on_candle(create_candle(
                    base_time + timedelta(minutes=i),
                    15302, 15307, 15300, 15307  # nowick_low = 15300
                ))
            else:
                await tracker.on_candle(create_candle(
                    base_time + timedelta(minutes=i),
                    15305, 15310, 15300, 15305
                ))

        # LIQ #2
        await tracker.on_candle(create_candle(
            base_time + timedelta(minutes=config.consol_min_duration + 1),
            15312, 15325, 15310, 15320
        ))

        candidate = list(tracker.active_candidates.values())[0]
        assert candidate.state == SetupState.WAITING_ENTRY

        # Entry trigger (close below no-wick low = 15300)
        result = await tracker.on_candle(create_candle(
            base_time + timedelta(minutes=config.consol_min_duration + 2),
            15305, 15305, 15295, 15297  # close=15297 < 15300
        ))

        # Should complete setup
        assert result.setup_completed is True
        assert candidate.state == SetupState.SETUP_COMPLETE
        assert candidate.entry_triggered is True
        assert candidate.sl_price is not None
        assert candidate.tp_price is not None


class TestSLTPCalculation:
    """Test SL/TP calculation."""

    @pytest.mark.asyncio
    async def test_sl_tp_calculated_correctly(self, tracker, config):
        """Test that SL/TP are calculated correctly."""
        # Get to SETUP_COMPLETE
        tracker.lse_high = 15300
        tracker.lse_low = 15100
        tracker.current_date = datetime(2024, 1, 15).date()

        # Go through full flow
        await tracker.on_candle(create_candle(
            datetime(2024, 1, 15, 15, 45),
            15295, 15320, 15290, 15305
        ))

        base_time = datetime(2024, 1, 15, 15, 46)
        for i in range(config.consol_min_duration):
            if i == 1:
                await tracker.on_candle(create_candle(
                    base_time + timedelta(minutes=i),
                    15302, 15307, 15300, 15307
                ))
            else:
                await tracker.on_candle(create_candle(
                    base_time + timedelta(minutes=i),
                    15305, 15310, 15300, 15305
                ))

        await tracker.on_candle(create_candle(
            base_time + timedelta(minutes=config.consol_min_duration + 1),
            15312, 15325, 15310, 15320  # LIQ #2 price = 15325
        ))

        await tracker.on_candle(create_candle(
            base_time + timedelta(minutes=config.consol_min_duration + 2),
            15305, 15305, 15295, 15297  # Entry trigger
        ))

        candidate = list(tracker.completed_setups)[0]

        # Verify SL/TP
        # SL = LIQ #2 price + buffer = 15325 + 1 = 15326
        assert candidate.sl_price == 15326

        # TP = LSE Low - buffer = 15100 - 1 = 15099
        assert candidate.tp_price == 15099

        # Risk/Reward should be calculated
        assert candidate.risk_reward_ratio > 0


class TestMultipleConcurrentCandidates:
    """Test multiple concurrent setup candidates."""

    @pytest.mark.asyncio
    async def test_multiple_liq1_create_multiple_candidates(self):
        """Test that multiple LIQ #1 breakouts create multiple candidates."""
        # Use permissive config to prevent quality-based invalidation
        config = SetupTrackerConfig(
            consol_min_duration=10,
            consol_min_quality=0.0,  # Disable quality check
            consol_max_duration=50
        )
        tracker = SetupTracker(config)

        tracker.lse_high = 15300
        tracker.lse_low = 15100
        tracker.current_date = datetime(2024, 1, 15).date()

        # First LIQ #1
        await tracker.on_candle(create_candle(
            datetime(2024, 1, 15, 15, 45),
            15295, 15320, 15290, 15305
        ))

        assert len(tracker.active_candidates) == 1

        # Feed a few consolidation candles (below LSE High to avoid triggering new LIQ #1)
        for i in range(3):
            await tracker.on_candle(create_candle(
                datetime(2024, 1, 15, 15, 46 + i),
                15295, 15298, 15290, 15295
            ))

        # First candidate should still be active
        assert len(tracker.active_candidates) == 1, \
            f"First candidate invalidated. Candidates: {tracker.active_candidates}"

        # Second LIQ #1 (6 minutes later - should create new candidate)
        await tracker.on_candle(create_candle(
            datetime(2024, 1, 15, 15, 52),
            15310, 15335, 15308, 15320
        ))

        # Should have 2 active candidates
        assert len(tracker.active_candidates) == 2


class TestNewDayReset:
    """Test new day reset behavior."""

    @pytest.mark.asyncio
    async def test_new_day_resets_state(self, tracker):
        """Test that new day resets LSE levels and invalidates old candidates."""
        # Day 1
        tracker.lse_high = 15300
        tracker.lse_low = 15100
        tracker.current_date = datetime(2024, 1, 15).date()

        # Create candidate
        await tracker.on_candle(create_candle(
            datetime(2024, 1, 15, 15, 45),
            15295, 15320, 15290, 15305
        ))

        assert len(tracker.active_candidates) == 1

        # Day 2 - first candle
        await tracker.on_candle(create_candle(
            datetime(2024, 1, 16, 9, 0),  # New day
            15280, 15285, 15275, 15280
        ))

        # Should reset state
        assert tracker.current_date == datetime(2024, 1, 16).date()
        assert tracker.lse_high == 15285  # New day high
        assert len(tracker.active_candidates) == 0  # Old candidate invalidated
        assert len(tracker.invalidated_setups) == 1


class TestStatistics:
    """Test statistics tracking."""

    @pytest.mark.asyncio
    async def test_statistics_tracking(self, tracker, config):
        """Test that statistics are tracked correctly."""
        tracker.lse_high = 15300
        tracker.lse_low = 15100
        tracker.current_date = datetime(2024, 1, 15).date()

        # Feed candles
        await tracker.on_candle(create_candle(
            datetime(2024, 1, 15, 15, 45),
            15295, 15320, 15290, 15305
        ))

        stats = tracker.get_stats()

        assert stats['candles_processed'] == 1
        assert stats['liq1_detected'] == 1
        assert stats['candidates_active'] == 1
        assert stats['lse_high'] == 15300
