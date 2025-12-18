# Known Issues - SLOB Live Trading System

## 1. LIQ #2 Detection Edge Case ✅ FIXED

**Status**: Fixed (2025-12-18)

**Problem**:
When a candle triggers both:
1. Consolidation completion (no-wick found) → transition to WATCHING_LIQ2
2. LIQ #2 breakout (high > consol_high)

The candle is only processed by `_update_watching_consol()` and NOT by `_update_watching_liq2()`, causing LIQ #2 to be missed.

**Location**: `slob/live/setup_tracker.py`, lines 383-493

**Root Cause**:
```python
async def _update_candidate(self, candidate, candle):
    if candidate.state == SetupState.WATCHING_CONSOL:
        return await self._update_watching_consol(candidate, candle)
    elif candidate.state == SetupState.WATCHING_LIQ2:
        return await self._update_watching_liq2(candidate, candle)
```

When `_update_watching_consol` transitions to WATCHING_LIQ2, it returns without re-processing the candle in the new state.

**Proposed Fix**:
```python
async def _update_watching_consol(self, candidate, candle):
    # ... existing logic ...

    # After transition to WATCHING_LIQ2:
    if success:  # Transition succeeded
        logger.info(f"✅ Consolidation confirmed: {candidate.id[:8]}")

        # CRITICAL: Re-process this candle in new state!
        # This candle might also be LIQ #2
        return await self._update_watching_liq2(candidate, candle)

    return CandleUpdate(...)
```

**Workaround**:
In real trading, this edge case is rare because:
- Consolidation typically needs 5-10 candles before no-wick is found
- LIQ #2 usually occurs 1-3 candles AFTER transition
- The next candle will correctly detect LIQ #2 if missed on transition candle

**Impact**:
- Low impact in production (setup detected 1 candle later)
- Affects integration test validation
- Does NOT introduce look-ahead bias

**Testing**:
- Unit tests: ✅ Pass (16/16)
- Integration test: ⚠️ Fails on this edge case
- OHLCV accuracy test: ✅ Pass

**Solution Implemented**:
1. Freeze consolidation bounds at transition by removing current candle from `consol_candles`
2. Re-process transition candle in WATCHING_LIQ2 state
3. This allows LIQ #2 detection on same candle as consolidation completion

**Changes Made** (`setup_tracker.py:477-503`):
```python
# Before transition, remove current candle to freeze consolidation bounds
candidate.consol_candles.pop()
candidate.consol_high = max(c['high'] for c in candidate.consol_candles)

# After transition, re-process candle in new state
if success:
    return await self._update_watching_liq2(candidate, candle)
```

**Verification**:
- ✅ Integration test passing (test_complete_5_1_setup_simplified)
- ✅ Unit tests still passing (16/16)
- ✅ LIQ #2 detected on same candle as transition

**Action Items**:
- [x] Apply proposed fix to `_update_watching_consol()`
- [x] Update integration test to verify fix
- [ ] Test in paper trading environment

---

**Notes**:
- This was discovered during Week 2 Task 2.2 (SetupTracker) completion
- All other setup detection logic works correctly
- System is safe for paper trading with this known limitation
