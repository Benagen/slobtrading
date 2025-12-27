# SLOB Trading System - Quick Start Guide

**Account:** DUO282477 (Paper Trading)
**Status:** ✅ System Ready for Testing
**Date:** 2025-12-27

---

## 🚀 Quick Commands

### Weekend 24h Validation (Optional)
```bash
# Start 24-hour validation run
./scripts/start_weekend_validation.sh

# Monitor in another terminal
tail -f logs/trading.log
```

### Monday Morning Live Test
```bash
# Start Monday morning (monitor-only mode)
./scripts/start_monday_morning.sh

# Or manually:
python3 scripts/run_paper_trading.py --account DUO282477 --gateway --duration 8 --monitor-only
```

### Enable Trading (After monitoring looks good)
```bash
# Stop current session (Ctrl+C), then restart without --monitor-only:
python3 scripts/run_paper_trading.py --account DUO282477 --gateway --duration 8
```

---

## ✅ System Status

### Critical Bugfixes (All Complete)
- [x] Paper trading flag enforcement
- [x] Account loading from secrets
- [x] Account balance verification
- [x] OCA groups for bracket orders
- [x] Real-time market data (Type 1 with fallback to Type 3)
- [x] Port unified to 4002 (IB Gateway)
- [x] Client ID conflicts resolved

### Configuration (All Complete)
- [x] Secrets directory: `secrets/*.txt`
- [x] Account: DUO282477
- [x] .env configured
- [x] Database migrated
- [x] All tests passed

### Files Modified
- `slob/live/order_executor.py` (4 fixes)
- `slob/live/live_trading_engine.py` (2 fixes)
- `slob/live/ib_ws_fetcher.py` (1 fix)

---

## 📁 Important Files

### Startup Scripts
- `scripts/start_weekend_validation.sh` - 24h validation
- `scripts/start_monday_morning.sh` - Monday morning startup
- `scripts/run_paper_trading.py` - Main runner

### Documentation
- `MONDAY_STARTUP_GUIDE.md` - Detailed Monday checklist
- `QUICK_START.md` - This file
- `CHANGELOG.md` - All changes documented

### Configuration
- `.env` - Environment variables (IB account, ports, etc.)
- `secrets/*.txt` - IB credentials (not in git)
- `data/slob_state.db` - SQLite database

### Logs
- `logs/trading.log` - Main application log
- Rotates daily, keeps 30 days

---

## 🔍 Health Checks

### Quick System Check
```bash
# Check IB Gateway connection
nc -zv localhost 4002

# Verify account
python3 -c "from slob.config.secrets import get_secret; print(get_secret('ib_account', 'IB_ACCOUNT'))"

# Check database
sqlite3 data/slob_state.db "SELECT COUNT(*) FROM active_setups;"
```

### Monitor Logs
```bash
# Real-time logs
tail -f logs/trading.log

# Search for errors
grep -i "ERROR\|CRITICAL" logs/trading.log

# Count setups detected today
grep "SETUP.*COMPLETE" logs/trading.log | wc -l
```

### Check Database State
```bash
# Active setups
sqlite3 data/slob_state.db "SELECT id, state, entry_price FROM active_setups WHERE state != 'INVALIDATED';"

# Recent trades
sqlite3 data/slob_state.db "SELECT * FROM trades ORDER BY entry_time DESC LIMIT 5;"

# Session state
sqlite3 data/slob_state.db "SELECT * FROM session_state ORDER BY session_date DESC LIMIT 1;"
```

---

## 🎯 Testing Checklist

### Basic Tests (All Passed ✅)
- [x] IB Gateway connection (localhost:4002)
- [x] Secrets loading (account, username, password)
- [x] Database migration (4 tables, 9 indexes)
- [x] Paper trading flag (orders blocked when enabled)
- [x] Market data subscription (real-time Type 1)

### Live Test Checklist (Monday)
- [ ] Pre-market setup (08:00-09:00)
- [ ] System starts without errors
- [ ] Real-time market data flowing
- [ ] No CRITICAL/ERROR messages
- [ ] First 30 min monitoring successful
- [ ] Enable trading if all looks good
- [ ] Monitor throughout trading day

---

## ⚠️ Important Notes

### Paper Trading Safety
- All orders go to paper trading account (DUO282477)
- No real money at risk
- Use this to validate system before live trading

### Market Data
- Real-time (Type 1) requires IB subscription
- Falls back to delayed (Type 3) if unavailable
- Your friend is setting up real-time access by Monday

### Order Execution
- Paper trading flag is enforced (orders blocked in paper mode)
- Bracket orders use OCA groups (one-cancels-all)
- Idempotency protection prevents duplicate orders
- Max position size: 2 contracts (conservative for testing)

---

## 🆘 Emergency Procedures

### Stop System Immediately
```bash
# Press Ctrl+C in terminal running system
# System will gracefully shutdown
```

### Force Close All Positions
1. Open IB Gateway/TWS
2. Go to Account → Trades
3. Select all positions
4. Right click → Close All

### Check What Went Wrong
```bash
# View recent logs
tail -100 logs/trading.log

# Search for errors
grep -i "ERROR\|CRITICAL" logs/trading.log

# Check database
sqlite3 data/slob_state.db "SELECT * FROM active_setups WHERE state != 'INVALIDATED';"
```

---

## 📞 Troubleshooting Quick Reference

| Problem | Solution |
|---------|----------|
| Can't connect to IB Gateway | Check port 4002, restart IB Gateway |
| No market data | Verify market hours, check subscription |
| Orders not placing | Verify paper_trading=False, check balance |
| Dashboard not loading | Check port 5000, verify process running |
| Database errors | Run `python3 scripts/migrate_database.py` |
| Secrets not loading | Check `secrets/*.txt` files have .txt extension |

---

## 📊 Expected Behavior

### Normal Startup Sequence
```
✅ Connected successfully!
✅ Requested Market Data Type 1 (Real-time)
✅ Subscribed to: NQ
✅ Account loaded: DUO282477
✅ Account balance: $1,000,000.00
Monitoring for 5/1 SLOB setups...
```

### Setup Detection Sequence
```
INFO - ✅ LSE High detected: 19450.50
INFO - ✅ LIQ #1 detected: 19455.75
INFO - ✅ Consolidation confirmed (quality: 0.85)
INFO - ✅ No-wick candle found
INFO - ✅ LIQ #2 detected: 19462.00
INFO - ✅ Entry triggered at 19458.00
INFO - ✅ Bracket order placed successfully!
```

### Order Placement (If Trading Enabled)
```
INFO - 📤 Placing bracket order...
INFO - Parent Order: SELL 1 NQ @ 19458.00
INFO - Stop Loss: BUY 1 NQ @ 19464.00
INFO - Take Profit: BUY 1 NQ @ 19358.00
INFO - ✅ Orders submitted to IB
INFO - Order IDs: Parent=123, SL=124, TP=125
```

---

## 🎉 You're All Set!

The system is fully configured and tested. You can:

1. **Run weekend validation** (optional but recommended):
   ```bash
   ./scripts/start_weekend_validation.sh
   ```

2. **Start Monday morning test**:
   ```bash
   ./scripts/start_monday_morning.sh
   ```

3. **Monitor and verify** everything works correctly

4. **Enable live trading** once confident

---

**For detailed Monday checklist:** See `MONDAY_STARTUP_GUIDE.md`

**For all changes made:** See `CHANGELOG.md`

**Good luck! 🚀**
