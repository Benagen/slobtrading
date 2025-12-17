# 5/1 SLOB Setup State Machine Design

**Purpose**: Incremental, real-time detection of 5/1 SLOB setups with **ZERO look-ahead bias**

**File**: `slob/live/setup_state.py`

---

## Design Principles

### 1. Incremental Updates Only

```python
# ❌ BAD (backtest with look-ahead)
consolidation = detect_consolidation(df, start_idx, end_idx=start_idx+30)
# Knows consolidation end 30 minutes in advance!

# ✅ GOOD (live with NO look-ahead)
for each new_candle:
    candidate.consol_candles.append(new_candle)
    candidate.consol_high = max(c['high'] for c in candidate.consol_candles)
    # Only knows about candles that have already occurred
```

### 2. State-Based Tracking

Each setup candidate exists in exactly ONE state at a time. State transitions happen as events occur in real-time.

### 3. Multiple Concurrent Candidates

The system can track multiple setup candidates simultaneously (e.g., different LIQ #1 breakouts on same day).

---

## State Definitions

### 1. WATCHING_LIQ1

**Description**: Initial state. Waiting for first liquidity grab.

**Active during**: NYSE session (15:30-22:00 UTC)

**Criteria for this state**:
- LSE High/Low levels established (from 09:00-15:30 session)
- Currently in NYSE session
- No LIQ #1 detected yet

**Exit conditions**:
- ✅ **LIQ #1 detected** → Transition to WATCHING_CONSOL
- ❌ **Market closes** → INVALIDATED (MARKET_CLOSED)

---

### 2. WATCHING_CONSOL

**Description**: LIQ #1 detected. Accumulating consolidation candles.

**Active during**: 15-30 minutes after LIQ #1

**Criteria for this state**:
- LIQ #1 detected and confirmed
- Accumulating consolidation window
- Minimum duration (15 min) NOT yet reached

**What happens each candle**:
```python
# Add candle to consolidation window
candidate.consol_candles.append(candle)

# Update bounds (ONLY using past candles!)
candidate.consol_high = max(c['high'] for c in candidate.consol_candles)
candidate.consol_low = min(c['low'] for c in candidate.consol_candles)
candidate.consol_range = candidate.consol_high - candidate.consol_low

# Recalculate quality score
candidate.consol_quality_score = calculate_quality(candidate.consol_candles)

# Check if min duration reached + quality OK
if len(candidate.consol_candles) >= 15:
    if candidate.consol_quality_score >= 0.4:  # Minimum threshold
        # Find no-wick candle
        nowick = find_nowick_in_window(candidate.consol_candles)
        if nowick:
            candidate.consol_confirmed = True
            candidate.nowick_found = True
            # Ready to transition to WATCHING_LIQ2
```

**Exit conditions**:
- ✅ **Consolidation confirmed (min duration + quality + no-wick)** → Transition to WATCHING_LIQ2
- ❌ **Duration > 30 min without confirmation** → INVALIDATED (CONSOL_TIMEOUT)
- ❌ **Quality score < 0.4** → INVALIDATED (CONSOL_QUALITY_LOW)
- ❌ **Range > 3x ATR** → INVALIDATED (CONSOL_RANGE_TOO_WIDE)
- ❌ **No no-wick candle found** → INVALIDATED (NO_WICK_NOT_FOUND)

---

### 3. WATCHING_LIQ2

**Description**: Consolidation confirmed. Waiting for LIQ #2 breakout.

**Active during**: After consolidation confirmation, waiting for price to break consolidation high

**Criteria for this state**:
- Consolidation confirmed (min duration + quality OK)
- No-wick candle identified
- Consolidation bounds fixed (no longer updating)
- LIQ #2 NOT yet detected

**What happens each candle**:
```python
# Check if price breaks consolidation high
if candle['high'] > candidate.consol_high:
    # Confirm liquidity grab with volume/momentum
    if is_liquidity_grab(candle, candidate.consol_high):
        candidate.liq2_detected = True
        candidate.liq2_price = candle['high']
        candidate.liq2_time = candle['timestamp']
        # Ready to transition to WAITING_ENTRY

# Check retracement (invalidation condition)
if candle['high'] > candidate.nowick_high + max_retracement_pips:
    # Invalidate - price retraced too far
    invalidate(candidate, RETRACEMENT_EXCEEDED)
```

**Exit conditions**:
- ✅ **LIQ #2 detected (breaks consolidation high)** → Transition to WAITING_ENTRY
- ❌ **Timeout (20 candles without LIQ #2)** → INVALIDATED (LIQ2_TIMEOUT)
- ❌ **Price retraces > 100 pips above no-wick high** → INVALIDATED (RETRACEMENT_EXCEEDED)
- ❌ **Market closes** → INVALIDATED (MARKET_CLOSED)

---

### 4. WAITING_ENTRY

**Description**: LIQ #2 detected. Waiting for entry trigger.

**Active during**: After LIQ #2, waiting for price to close below no-wick low

**Criteria for this state**:
- LIQ #2 confirmed
- Entry trigger NOT yet fired
- Still within entry window (max 20 candles)

**What happens each candle**:
```python
# Check if candle CLOSES below no-wick low
if candle['close'] < candidate.nowick_low:
    # Entry trigger fired!
    candidate.entry_triggered = True
    candidate.entry_trigger_time = candle['timestamp']

    # Calculate entry price (next candle's OPEN)
    candidate.entry_price = next_candle['open']

    # Calculate SL/TP
    candidate.sl_price = calculate_sl(candidate.liq2_price)
    candidate.tp_price = candidate.lse_low  # Target
    candidate.risk_reward_ratio = (candidate.entry_price - candidate.tp_price) / (candidate.sl_price - candidate.entry_price)

    # Ready to transition to SETUP_COMPLETE
```

**Exit conditions**:
- ✅ **Entry trigger fired (close below no-wick low)** → Transition to SETUP_COMPLETE
- ❌ **Timeout (20 candles without entry)** → INVALIDATED (ENTRY_TIMEOUT)
- ❌ **Market closes** → INVALIDATED (MARKET_CLOSED)

---

### 5. SETUP_COMPLETE

**Description**: Setup fully detected and ready for trading.

**Criteria for this state**:
- Entry trigger fired
- Entry price calculated
- SL/TP calculated
- Risk/reward ratio acceptable

**What happens**:
- Candidate is saved to database
- Order is placed (if auto-trading enabled)
- State manager persists setup for recovery
- Monitoring begins for this trade

**This is a terminal state** - setup candidate lifecycle is complete.

---

### 6. INVALIDATED

**Description**: Setup invalidated due to failed criteria.

**Reasons**:
- `CONSOL_TIMEOUT`: Consolidation never formed within 30 minutes
- `CONSOL_QUALITY_LOW`: Consolidation quality score < 0.4
- `CONSOL_RANGE_TOO_WIDE`: Consolidation range > 3x ATR
- `NO_WICK_NOT_FOUND`: No valid no-wick candle in consolidation
- `LIQ2_TIMEOUT`: LIQ #2 never occurred (20 candles)
- `RETRACEMENT_EXCEEDED`: Price retraced > 100 pips above no-wick
- `ENTRY_TIMEOUT`: Entry trigger never fired (20 candles)
- `MARKET_CLOSED`: Market closed before setup completed

**What happens**:
- Candidate is marked invalid
- State tracking stops
- Candidate is archived for analysis
- Resources are freed

**This is a terminal state** - setup candidate lifecycle is complete.

---

## State Transition Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                       5/1 SLOB STATE MACHINE                          │
└──────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────┐
                    │  WATCHING_LIQ1  │ ← Initial State
                    │                 │
                    │  - LSE levels   │
                    │    established  │
                    │  - Waiting for  │
                    │    NYSE break   │
                    └────────┬────────┘
                             │
                    LIQ #1 Detected
                    (NYSE > LSE High)
                             │
                             ▼
                    ┌─────────────────┐
                    │ WATCHING_CONSOL │
                    │                 │
                    │  - Accumulating │
                    │    candles      │
                    │  - Updating     │
                    │    bounds       │
                    │  - Calculating  │
                    │    quality      │
                    └────────┬────────┘
                             │
              Consolidation Confirmed
              (>15min, quality>0.4, no-wick found)
                             │
                             ▼
                    ┌─────────────────┐
                    │ WATCHING_LIQ2   │
                    │                 │
                    │  - Consol fixed │
                    │  - Waiting for  │
                    │    breakout     │
                    └────────┬────────┘
                             │
                   LIQ #2 Detected
              (Price > Consol High)
                             │
                             ▼
                    ┌─────────────────┐
                    │ WAITING_ENTRY   │
                    │                 │
                    │  - Waiting for  │
                    │    close below  │
                    │    no-wick low  │
                    └────────┬────────┘
                             │
                   Entry Trigger
              (Close < No-Wick Low)
                             │
                             ▼
                    ┌─────────────────┐
                    │ SETUP_COMPLETE  │ ← Terminal State
                    │                 │
                    │  - Entry calc   │
                    │  - SL/TP set    │
                    │  - Ready to     │
                    │    trade        │
                    └─────────────────┘


                    Invalidation paths (from any state):
                             │
                             ▼
                    ┌─────────────────┐
                    │   INVALIDATED   │ ← Terminal State
                    │                 │
                    │  - Timeout      │
                    │  - Quality low  │
                    │  - Retracement  │
                    │  - Market close │
                    └─────────────────┘
```

---

## Example: Full Setup Lifecycle

### Timeline

```
09:00 - LSE session starts
15:30 - LSE session ends → LSE High = 15300, LSE Low = 15100
        Create candidate in WATCHING_LIQ1 state

15:45 - Price breaks 15300 with volume
        LIQ #1 detected!
        Transition: WATCHING_LIQ1 → WATCHING_CONSOL

15:46 - Candle 1: High=15310, Low=15295 → Add to consol_candles
15:47 - Candle 2: High=15315, Low=15300 → Update consol_high=15315
15:48 - Candle 3: High=15312, Low=15298 → Update consol_high=15315
...
16:00 - Candle 15: 15 minutes elapsed
        - consol_high = 15320
        - consol_low = 15295
        - consol_range = 25 pips
        - quality_score = 0.65 (✅ > 0.4)
        - no-wick found at 16:03
        Transition: WATCHING_CONSOL → WATCHING_LIQ2

16:15 - Price breaks 15320 (consolidation high)
        LIQ #2 detected!
        Transition: WATCHING_LIQ2 → WAITING_ENTRY

16:18 - Candle closes at 15304 (✅ below no-wick low 15305)
        Entry trigger fired!
        - Entry price: Next candle open = 15304
        - SL: LIQ #2 high + buffer = 15325
        - TP: LSE Low = 15100
        - R:R = (15304-15100)/(15325-15304) = 204/21 = 9.7:1
        Transition: WAITING_ENTRY → SETUP_COMPLETE

        → Order placed, setup complete!
```

---

## Implementation Notes

### SetupCandidate Class

**Key features**:
- Immutable ID (UUID)
- All state is mutable (updates as candles arrive)
- `to_dict()` method for serialization (Redis/SQLite)
- `is_valid()` and `is_complete()` helper methods
- Timestamp tracking for duration calculations

**Example usage**:
```python
# Create candidate when LSE session ends
candidate = SetupCandidate(
    lse_high=15300,
    lse_low=15100,
    lse_close_time=datetime.now(),
    state=SetupState.WATCHING_LIQ1
)

# Update as candles arrive
async def on_candle(candle):
    if candidate.state == SetupState.WATCHING_LIQ1:
        # Check for LIQ #1
        if candle['high'] > candidate.lse_high:
            candidate.liq1_detected = True
            candidate.liq1_price = candle['high']
            candidate.liq1_time = candle['timestamp']

            # Transition
            StateTransitionValidator.transition_to(
                candidate,
                SetupState.WATCHING_CONSOL,
                reason="LIQ #1 detected"
            )

    elif candidate.state == SetupState.WATCHING_CONSOL:
        # Add candle to consolidation
        candidate.consol_candles.append({
            'timestamp': candle['timestamp'],
            'high': candle['high'],
            'low': candle['low'],
            'close': candle['close'],
            'volume': candle['volume']
        })

        # Update bounds
        candidate.consol_high = max(c['high'] for c in candidate.consol_candles)
        candidate.consol_low = min(c['low'] for c in candidate.consol_candles)

        # Check if ready to confirm
        if len(candidate.consol_candles) >= 15:
            quality = calculate_quality(candidate.consol_candles)
            if quality >= 0.4:
                # ... find no-wick, then transition
```

### StateTransitionValidator Class

**Key features**:
- Validates all transitions before executing
- Checks required fields are populated
- Logs all transitions for debugging
- Prevents invalid state changes

**Example usage**:
```python
# Attempt transition
success = StateTransitionValidator.transition_to(
    candidate,
    SetupState.WATCHING_LIQ2,
    reason="Consolidation confirmed"
)

if not success:
    # Transition failed validation
    logger.warning("Failed to transition - missing required data")

# Invalidate
StateTransitionValidator.invalidate(
    candidate,
    InvalidationReason.CONSOL_TIMEOUT
)
```

---

## Comparison: Backtest vs Live

### Backtest (Look-Ahead Bias)

```python
def find_consolidation(df, start_idx):
    # ❌ Searches FORWARD in time
    for duration in range(15, 31):
        end_idx = start_idx + duration
        window = df.iloc[start_idx:end_idx]

        # Knows consolidation end 30 minutes in advance!
        if is_good_consolidation(window):
            return window
```

**Problem**: At time T, algorithm "knows" what happens at T+30.

### Live (NO Look-Ahead Bias)

```python
async def on_candle(candidate, candle):
    # ✅ Only uses candles up to current time
    candidate.consol_candles.append(candle)

    # Update bounds incrementally
    candidate.consol_high = max(c['high'] for c in candidate.consol_candles)

    # Only confirm when min duration reached
    if len(candidate.consol_candles) >= 15:
        if is_good_quality(candidate.consol_candles):
            candidate.consol_confirmed = True
            # Transition to next state
```

**Correct**: At time T, algorithm only knows about T and earlier.

---

## Testing Strategy

### 1. Unit Tests

Test each state transition independently:

```python
def test_transition_watching_liq1_to_watching_consol():
    candidate = SetupCandidate(
        lse_high=15300,
        state=SetupState.WATCHING_LIQ1
    )

    candidate.liq1_detected = True
    candidate.liq1_price = 15310

    success = StateTransitionValidator.transition_to(
        candidate,
        SetupState.WATCHING_CONSOL
    )

    assert success
    assert candidate.state == SetupState.WATCHING_CONSOL
```

### 2. Integration Tests

Test full lifecycle:

```python
async def test_full_setup_lifecycle():
    candidate = SetupCandidate(lse_high=15300)

    # Feed candles one by one
    for candle in historical_candles:
        await tracker.on_candle(candidate, candle)

    # Verify final state
    assert candidate.state == SetupState.SETUP_COMPLETE
    assert candidate.entry_price is not None
```

### 3. Replay Tests (NO LOOK-AHEAD VALIDATION)

**Critical test**: Verify live system detects setups at SAME or LATER time than backtest.

```python
def test_no_look_ahead_bias():
    # Run backtest
    backtest_setups = SetupFinder().find_setups(df)

    # Run live replay (feed candles one by one)
    live_setups = []
    tracker = SetupTracker()
    for idx, candle in df.iterrows():
        result = await tracker.on_candle(candle)
        if result.is_complete():
            live_setups.append(result)

    # Compare detection timing
    for backtest, live in zip(backtest_setups, live_setups):
        # Live should detect at SAME or LATER time (never earlier!)
        assert live.liq1_time >= backtest['liq1_time']
        assert live.entry_trigger_time >= backtest['entry_trigger_time']
```

---

## Benefits of State Machine Design

### ✅ 1. No Look-Ahead Bias

State machine forces incremental updates. Impossible to "peek" into future.

### ✅ 2. Clear Transition Logic

Each state has explicit entry/exit conditions. Easy to understand and debug.

### ✅ 3. Multiple Concurrent Setups

Can track many candidates simultaneously (different LIQ #1 breakouts).

### ✅ 4. State Persistence

Can serialize candidate state to Redis/SQLite for crash recovery.

### ✅ 5. Validation Built-In

StateTransitionValidator prevents invalid state changes.

### ✅ 6. Audit Trail

Every transition is logged for debugging and analysis.

---

## Next Steps

1. ✅ State machine design complete
2. ⏭️ Implement SetupTracker (uses this state machine)
3. ⏭️ Implement incremental pattern detectors (consolidation, liquidity)
4. ⏭️ Write unit tests for state machine
5. ⏭️ Write replay tests (NO look-ahead validation)

---

**Last Updated**: 2025-12-17
**Status**: Design complete, ready for implementation
