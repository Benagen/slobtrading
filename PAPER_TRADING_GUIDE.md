# Paper Trading Validation Guide - Phase 1

**Phase**: 1 (Spike Rule + Idempotency)
**Duration**: 24-48 hours recommended
**Status**: Ready to start

---

## Quick Start

### 1. Start IB TWS/Gateway in Paper Trading Mode

**Option A: TWS (Trader Workstation)**
```bash
# Open TWS and select "Paper Trading" account
# Port: 7497
# Make sure API is enabled (Configure → API → Settings)
```

**Option B: IB Gateway**
```bash
# Open IB Gateway and select "Paper Trading"
# Port: 4002
# API enabled by default
```

### 2. Run Paper Trading Script

```bash
# Basic run (24 hours, place orders)
python3 scripts/run_paper_trading.py --account DU123456

# Custom duration (48 hours)
python3 scripts/run_paper_trading.py --account DU123456 --duration 48

# Monitor only (no orders placed)
python3 scripts/run_paper_trading.py --account DU123456 --monitor-only

# With IB Gateway
python3 scripts/run_paper_trading.py --account DU123456 --gateway
```

### 3. Monitor Output

The script will:
- ✅ Connect to IB TWS/Gateway
- ✅ Start monitoring for 5/1 SLOB setups
- ✅ Validate spike rule application
- ✅ Validate idempotency protection
- ✅ Log all activity to `logs/paper_trading_*.log`
- ✅ Print statistics every hour

---

## What to Watch For

### 🔥 TASK 1: Spike Rule Validation

**Expected Behavior**:
```
🔥 SPIKE RULE ACTIVATED - Setup abc12345
   LIQ #2: open=15290.0, high=15350.0, close=15305.0
   Body=15.0, Upper Wick=45.0, Ratio=3.00
   Expected SL: 15307.0 (body_top + 2)
   Actual SL:   15307.0
   ✅ Match: True
```

**Verification**:
- Spike ratio > 2.0 → SL at body_top + 2
- Normal candle → SL at high + 2
- SL matches backtest calculation exactly

### 🛡️ TASK 3: Idempotency Validation

**Expected Behavior**:
```
🛡️ IDEMPOTENCY PROTECTION ACTIVATED
   Duplicate order prevented: Duplicate order detected - order already placed for this setup
```

**Verification**:
- No duplicate orders placed
- orderRef present on all orders
- Duplicate detection survives reconnections

---

## Expected Statistics (After 24 Hours)

```
================================================================================
PAPER TRADING VALIDATION STATISTICS
================================================================================
Runtime:               24.0 hours
Setups Detected:       3-5 (typical daily count)
Orders Placed:         3-5

SPIKE RULE VALIDATION:
  Spike Rule Activated: 1-2 (20-40% of setups)
  Normal Candles:       2-3 (60-80% of setups)
  Activation Rate:      30%

IDEMPOTENCY VALIDATION:
  Duplicate Attempts:   0
  ✅ Protection Active: YES
================================================================================
```

---

## Configuration

### Setup Tracker Settings

Located in `scripts/run_paper_trading.py`:

```python
setup_tracker_config = SetupTrackerConfig(
    consol_min_duration=5,      # Min 5 candles consolidation
    consol_max_duration=30,     # Max 30 candles
    consol_min_quality=0.5,     # 50% quality threshold
    consol_max_range_pips=50,   # Max 50 pips range
    nowick_max_wick_ratio=0.3,  # Max 30% wick
    sl_buffer_pips=1.0,         # Note: Spike rule uses 2.0
    tp_buffer_pips=1.0,
    max_entry_wait_candles=20
)
```

### Order Executor Settings

```python
order_executor_config = OrderExecutorConfig(
    default_position_size=1,  # Conservative for paper trading
    max_position_size=2,
    enable_bracket_orders=True
)
```

---

## Logs

### Location
```
logs/paper_trading_YYYYMMDD_HHMMSS.log
```

### What's Logged
- Setup detection events (LIQ #1, consolidation, LIQ #2, entry)
- Spike rule calculations
- Order placement results
- Idempotency checks
- Connection status
- Errors/warnings

### Example Log Entry
```
2025-12-18 10:35:42 | INFO     | SetupTracker              | 🔵 LIQ #2 detected: abc12345 @ 15350.00
2025-12-18 10:36:15 | INFO     | SetupTracker              | 🎯 Setup COMPLETE: abc12345
2025-12-18 10:36:15 | INFO     | PaperTradingValidator     | 🔥 SPIKE RULE ACTIVATED - Setup abc12345
2025-12-18 10:36:15 | INFO     | OrderExecutor             | Placing bracket order for setup abc12345
2025-12-18 10:36:16 | INFO     | OrderExecutor             | ✅ Bracket order placed: abc12345
```

---

## Troubleshooting

### Connection Issues

**Problem**: "IB not connected"
```bash
# Check if TWS/Gateway is running
# Check port (7497 for TWS, 4002 for Gateway)
# Enable API in TWS settings
```

**Problem**: "Socket connection refused"
```bash
# TWS/Gateway must allow API connections
# Configure → API → Settings → Enable ActiveX and Socket Clients
# Enable "Download open orders on connection"
```

### No Setups Detected

**Problem**: "No setups found after 8 hours"
```bash
# This is normal! 5/1 SLOB is a rare setup
# Typical: 3-5 setups per day
# Continue monitoring for full 24-48 hours
```

### Order Placement Fails

**Problem**: "Order rejected by IB"
```bash
# Check account has sufficient buying power
# Check NQ futures permissions
# Check market hours (9:30 AM - 4:00 PM ET)
```

---

## Manual Validation Checklist

### After First Setup

- [ ] Check log for spike rule calculation
- [ ] Verify SL matches expected value (body_top+2 or high+2)
- [ ] Check TWS for order placement
- [ ] Verify orderRef format: `SLOB_{setup_id}_{timestamp}_{type}`

### After 24 Hours

- [ ] Review all setup detections in log
- [ ] Count spike rule activations
- [ ] Verify no duplicate orders placed
- [ ] Check R:R ratios match backtest expectations
- [ ] Review order fill status in TWS

### After 48 Hours

- [ ] Generate final statistics
- [ ] Compare with backtest metrics
- [ ] Document any anomalies
- [ ] Approve for live trading if all checks pass

---

## Success Criteria

### ✅ PASS Conditions

1. **Spike Rule**:
   - 100% of setups have correct SL calculation
   - Spike ratio correctly detected (wick > 2x body)
   - SL matches backtest within ±0.5 pips

2. **Idempotency**:
   - Zero duplicate orders placed
   - orderRef present on all orders
   - Duplicate detection working (test by attempting manual retry)

3. **System Stability**:
   - No crashes or disconnections
   - All setups detected correctly
   - Orders placed successfully

### ❌ FAIL Conditions

1. **SL Mismatch**:
   - SL differs from backtest by >1 pip
   - Spike rule not applied correctly
   - Wrong buffer used

2. **Duplicate Orders**:
   - Any duplicate orders placed
   - orderRef missing
   - Idempotency check failed

3. **System Issues**:
   - Frequent disconnections
   - Setup detection errors
   - Order placement failures

---

## Next Steps

### If PASS
1. ✅ Document results in validation report
2. ✅ Proceed to Phase 2 (RiskManager Integration)
3. ✅ Consider enabling live trading with 1 contract

### If FAIL
1. ❌ Review logs for error patterns
2. ❌ Identify root cause
3. ❌ Fix issue and re-run validation
4. ❌ Do NOT proceed to Phase 2 until fixed

---

## Phase 2 Preview

**After successful Phase 1 validation**, proceed to:

**TASK 2**: RiskManager Integration
- Sophisticated position sizing (Kelly Criterion)
- Drawdown protection (15% / 25% thresholds)
- Account balance sync from IBKR
- ATR-based volatility adjustment

**Estimated Time**: 12 hours implementation + 7 days validation

---

## Commands Reference

```bash
# Start paper trading (24 hours)
python3 scripts/run_paper_trading.py --account DU123456

# Monitor only (no orders)
python3 scripts/run_paper_trading.py --account DU123456 --monitor-only

# 48 hour run
python3 scripts/run_paper_trading.py --account DU123456 --duration 48

# With IB Gateway
python3 scripts/run_paper_trading.py --account DU123456 --gateway --port 4002

# Check logs
tail -f logs/paper_trading_*.log

# View statistics
grep "STATISTICS" logs/paper_trading_*.log -A 20
```

---

**Status**: Ready for validation
**Estimated Duration**: 24-48 hours
**Approval**: Required before live trading
**Contact**: Review logs and report any issues
