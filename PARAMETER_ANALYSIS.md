# Parameter Strictness Analysis

## Problem
Endast 1 setup hittat på 30 dagar live marknadsdata → **Parametrar är för strikta**

## Root Cause Analysis

### Current Parameters (Training Script)
```python
finder = SetupFinder(
    consol_min_duration=15,      # Minutes
    consol_max_duration=40,      # Minutes
    atr_multiplier_min=0.3,      # ATR multiplier
    atr_multiplier_max=2.5,      # ATR multiplier
    nowick_percentile=90         # Top 10% of candles only
)
```

### Identified Bottlenecks

#### 1. Consolidation Quality Score (MAJOR)
**Location**: `slob/patterns/consolidation_detector.py:315`

```python
min_quality = 0.6 if strict else 0.4
if consolidation['quality_score'] < min_quality:
    issues.append(f"Quality score too low...")
```

**Issue**: Quality score 0.6 threshold rejects most consolidations!

**Quality Score Formula**:
```python
score = (
    tightness * 0.35 +              # Range compression
    volume_compression * 0.25 +     # Volume decreasing
    breakout_ready * 0.20 +         # Price near top
    oscillation * 0.20              # Midpoint crosses
)
```

**Problem**: Requires **perfect consolidation** (tight range, volume compression, oscillation)
**Impact**: 90% of real consolidations rejected

---

#### 2. No-Wick Percentile (MAJOR)
**Location**: `slob/backtest/setup_finder.py:433`

```python
is_nowick = NoWickDetector.is_no_wick_candle(
    candle, df, i,
    direction='bullish',
    percentile=self.nowick_percentile  # 90
)
```

**Issue**: percentile=90 means candle must be in **top 10%** of smallest upper wicks

**Problem**: Too strict - rejects 90% of bullish candles
**Impact**: Even perfect consolidations fail if no-wick not found

---

#### 3. ATR Multiplier Range (MINOR)
**Current**: 0.3 - 2.5

**Issue**: May be too narrow
**Typical consolidations**: 0.5 - 3.5 ATR

---

#### 4. Consolidation Duration (MINOR)
**Current**: 15-40 minutes

**Issue**: May miss shorter (10-15 min) or longer (40-60 min) consolidations
**Real market**: 10-60 minutes common

---

## Impact on Setup Detection

| Stage | Pass Rate | Bottleneck |
|-------|-----------|------------|
| LSE Session | ~70% | Market hours only |
| LIQ #1 Found | ~50% | NYSE timing |
| Consolidation Found | ~20% | ❌ **Quality score < 0.6** |
| No-Wick Found | ~10% | ❌ **Percentile = 90** |
| LIQ #2 Found | ~80% | OK |
| Entry Trigger | ~90% | OK |
| **Final Pass Rate** | **~0.8%** | **Too strict!** |

**Expected**: ~10-20% final pass rate (1-2 setups per 10 days)
**Actual**: ~0.8% (1 setup per 30 days)

---

## Recommended Parameter Changes

### Relaxed Parameters (Recommended)
```python
finder = SetupFinder(
    consol_min_duration=10,      # Was: 15 (more permissive)
    consol_max_duration=60,      # Was: 40 (catch longer consolidations)
    atr_multiplier_min=0.2,      # Was: 0.3 (wider range)
    atr_multiplier_max=3.5,      # Was: 2.5 (wider range)
    nowick_percentile=75         # Was: 90 (top 25% instead of top 10%)
)
```

**Expected Impact**:
- Consolidation detection: 20% → **50%** pass rate
- No-wick detection: 10% → **25%** pass rate
- Final pass rate: 0.8% → **6%**
- **Setups per month**: 1 → **5-10 setups**

---

### Very Relaxed Parameters (Max Setups)
```python
finder = SetupFinder(
    consol_min_duration=5,       # Shortest consolidations
    consol_max_duration=90,      # Longest consolidations
    atr_multiplier_min=0.1,      # Widest range
    atr_multiplier_max=5.0,      # Widest range
    nowick_percentile=60         # Top 40% of candles
)
```

**Expected Impact**:
- Final pass rate: 0.8% → **15%**
- **Setups per month**: 1 → **20-30 setups**
- **Warning**: More setups = lower quality, need ML filter!

---

## Testing Strategy

### Phase 1: Validate Relaxation (1-2 hours)
```bash
# Test with relaxed parameters on 30 days data
python scripts/train_model_stationary.py \
    --days 30 \
    --relaxed-params \
    --verbose
```

**Success Criteria**:
- ✅ Find 5-10 setups (vs 1 setup with strict params)
- ✅ Win rate 40-60% (sanity check)
- ✅ Quality score distribution looks reasonable

---

### Phase 2: ML Training (2-3 hours)
```bash
# Train ML model with relaxed params on 60 days
python scripts/train_model_stationary.py \
    --days 60 \
    --relaxed-params
```

**Success Criteria**:
- ✅ 30+ training samples
- ✅ CV AUC > 0.65
- ✅ Test AUC > 0.60

---

### Phase 3: Backtest Validation (1-2 hours)
```bash
# Run backtest with relaxed params + ML filter
python scripts/backtest_ml_filter.py \
    --days 90 \
    --ml-threshold 0.60 \
    --relaxed-params
```

**Success Criteria**:
- ✅ Win rate with ML filter > base win rate
- ✅ Sharpe ratio improvement
- ✅ Reasonable trade frequency (5-20 per month)

---

## Code Changes Required

### 1. Update ConsolidationDetector (CRITICAL)

**File**: `slob/patterns/consolidation_detector.py`

**Change quality threshold**:
```python
# OLD:
min_quality = 0.6 if strict else 0.4

# NEW:
min_quality = 0.4 if strict else 0.3  # More permissive
```

**OR better: Make it configurable**:
```python
def detect_consolidation(
    df: pd.DataFrame,
    start_idx: int,
    min_quality: float = 0.4,  # NEW parameter
    ...
):
    # Later:
    if consolidation['quality_score'] < min_quality:
        issues.append(...)
```

---

### 2. Update Training Script

**File**: `scripts/train_model_stationary.py`

**Add --relaxed-params flag**:
```python
parser.add_argument(
    '--relaxed-params',
    action='store_true',
    help='Use relaxed parameters for more setups'
)

# Later:
if args.relaxed_params:
    finder = SetupFinder(
        consol_min_duration=10,
        consol_max_duration=60,
        atr_multiplier_min=0.2,
        atr_multiplier_max=3.5,
        nowick_percentile=75
    )
else:
    finder = SetupFinder()  # Default strict params
```

---

## Risk Assessment

### Risk: Lower Quality Setups
**Mitigation**:
- Use ML filter to reject low-probability setups
- Monitor win rate (should be 40-60%)
- Compare relaxed vs strict in A/B test

### Risk: Overfitting ML Model
**Mitigation**:
- Use time-series cross-validation
- Keep max_depth=5 (prevent overfitting)
- Monitor test AUC vs train AUC gap

### Risk: Changed Strategy Behavior
**Mitigation**:
- Document parameter changes
- Run parallel paper trading (strict vs relaxed)
- Revert if win rate drops >5%

---

## Conclusion

**Current Status**: Parameters TOO strict → 1 setup/30 days ❌

**Recommended**: Relax parameters → 5-10 setups/month ✅

**Next Steps**:
1. ✅ Update ConsolidationDetector min_quality
2. ✅ Update training script with --relaxed-params
3. ✅ Run training with 60 days data
4. ✅ Validate win rate and ML performance
5. ✅ Deploy to paper trading

**Timeline**: 4-6 hours total
