# Monday Morning Startup Guide - Live Trading Test

**Date:** 2025-12-30 (måndag)
**Market Open:** 09:30 ET
**Account:** DUO282477 (Paper Trading)
**Mode:** Live testing with real-time data

---

## 📅 Timeline

- **08:00-08:30:** Pre-market setup and verification
- **08:30-09:00:** System startup and monitoring
- **09:00-09:30:** Pre-market monitoring (no trading yet)
- **09:30-10:00:** Market open - enable monitoring-only mode
- **10:00+:** Enable live trading (if monitoring looks good)

---

## ✅ Pre-Market Checklist (08:00-08:30)

### 1. IB Gateway Check
```bash
# Verify IB Gateway is running on port 4002
nc -zv localhost 4002
```
**Expected:** Connection to localhost port 4002 [tcp/*] succeeded!

**If fails:**
- [ ] Start IB Gateway
- [ ] Login with paper trading credentials
- [ ] Verify port 4002 in configuration
- [ ] Ensure "Enable ActiveX and Socket Clients" is checked

### 2. System Health Check
```bash
# Run health check script
./scripts/health_check.sh
```

**Expected outputs:**
- [x] IB Gateway: CONNECTED
- [x] Database: OK
- [x] Secrets: OK
- [x] Logs directory: OK

### 3. Verify Account Balance
```bash
python3 -c "
from ib_insync import IB

ib = IB()
ib.connect('localhost', 4002, clientId=99)

print(f'Account: {ib.managedAccounts()}')

for av in ib.accountValues():
    if av.tag in ['TotalCashValue', 'NetLiquidation', 'AvailableFunds']:
        print(f'{av.tag}: {av.currency} {av.value}')

ib.disconnect()
"
```

**Expected:**
- Account: ['DUO282477']
- TotalCashValue: USD 1000000 (eller aktuell balance)

### 4. Clear Old Logs (Optional)
```bash
# Backup old logs
mv logs/trading.log logs/trading.log.backup 2>/dev/null || true

# Start fresh
mkdir -p logs/
```

### 5. Review Weekend Validation Results (If you ran it)
```bash
# Check for critical errors
grep -i "CRITICAL\|ERROR" logs/trading.log.backup | tail -20

# Check setup detection count
grep "SETUP.*COMPLETE" logs/trading.log.backup | wc -l
```

---

## 🚀 System Startup (08:30-09:00)

### Start in Monitor-Only Mode (No Trading)

```bash
./scripts/start_monday_morning.sh
```

Or manually:
```bash
python3 scripts/run_paper_trading.py \
    --account DUO282477 \
    --gateway \
    --duration 8 \
    --monitor-only
```

**This will:**
- ✅ Connect to IB Gateway
- ✅ Subscribe to NQ market data
- ✅ Monitor for 5/1 SLOB setups
- ❌ NOT place any orders (monitor-only mode)

### Monitor Logs in Separate Terminal
```bash
# Open new terminal and run:
tail -f logs/trading.log
```

**Watch for:**
- [ ] "✅ Connected successfully!" message
- [ ] "Requested Market Data Type 1 (Real-time)" message
- [ ] No CRITICAL or ERROR messages
- [ ] Real-time tick data flowing (check timestamps)

---

## 📊 Market Open Monitoring (09:00-09:30)

### Pre-Market Checklist (09:00-09:30 ET)

**Watch dashboard:**
```bash
# Dashboard should be accessible at:
open http://localhost:5000
```

**Verify on dashboard:**
- [ ] Connection Status: CONNECTED
- [ ] Market Data: LIVE (not delayed)
- [ ] Account: DUO282477
- [ ] Balance: Correct amount
- [ ] Last Tick: < 5 seconds ago

### Manual Market Data Test (09:00-09:30)
```bash
python3 -c "
import asyncio
from slob.live.ib_ws_fetcher import IBWSFetcher
from datetime import datetime, timezone

async def test():
    fetcher = IBWSFetcher(host='localhost', port=4002, client_id=10)

    tick_count = 0

    async def on_tick(tick):
        nonlocal tick_count
        tick_count += 1

        now = datetime.now(timezone.utc)
        tick_time = tick.timestamp.replace(tzinfo=timezone.utc) if tick.timestamp.tzinfo is None else tick.timestamp
        delay = (now - tick_time).total_seconds()

        if tick_count <= 5:
            print(f'Tick #{tick_count}: \${tick.price:.2f} (delay: {delay:.2f}s)')

    fetcher.on_tick = on_tick
    await fetcher.connect()
    await fetcher.subscribe(['NQ'])
    await asyncio.sleep(30)
    await fetcher.disconnect()

    print(f'\nTotal ticks: {tick_count}')
    if tick_count > 0:
        print('✅ Market data LIVE')
    else:
        print('⚠️  No ticks (market may not be open yet)')

asyncio.run(test())
"
```

**Expected at 09:30+ ET:**
- Ticks flowing every few seconds
- Delay < 5 seconds (real-time)

---

## 🎯 Enable Trading (10:00+ if monitoring OK)

### After 30 Minutes of Successful Monitoring

**If you see:**
- ✅ No errors in logs
- ✅ Real-time market data flowing
- ✅ Connection stable
- ✅ Account balance correct

**Then you can enable trading:**

### Stop Current Session
```bash
# In terminal running system: Press Ctrl+C
```

### Restart WITH Trading Enabled
```bash
python3 scripts/run_paper_trading.py \
    --account DUO282477 \
    --gateway \
    --duration 6.5
    # Note: NO --monitor-only flag = trading enabled!
```

**This will:**
- ✅ Connect to IB Gateway
- ✅ Subscribe to NQ market data
- ✅ Monitor for 5/1 SLOB setups
- ✅ **PLACE ORDERS** when setups trigger

---

## 🔍 Active Monitoring (10:00-16:00)

### Every 30 Minutes Check

```bash
# 1. System still running?
ps aux | grep run_paper_trading

# 2. Any errors?
tail -50 logs/trading.log | grep -i "ERROR\|CRITICAL"

# 3. Any setups detected?
sqlite3 data/slob_state.db "
SELECT id, state, entry_price, created_at
FROM active_setups
WHERE DATE(created_at) = DATE('now')
ORDER BY created_at DESC
LIMIT 10;
"

# 4. Dashboard still responsive?
curl -I http://localhost:5000
```

### Watch For Setup Progression

In logs, you should see progression like:
```
INFO - ✅ LSE High detected: 19450.50
INFO - ✅ LIQ #1 detected: 19455.75
INFO - ✅ Consolidation confirmed (quality: 0.85)
INFO - ✅ No-wick candle found at 19458.25
INFO - ✅ LIQ #2 detected: 19462.00
INFO - ✅ Entry triggered at 19458.00
INFO - 📤 Placing bracket order...
INFO - ✅ Bracket order placed successfully!
```

### If You See an Order Placed

**Check in TWS/IB Gateway:**
- [ ] Parent order shows "Submitted" or "Filled"
- [ ] Stop Loss order shows as child
- [ ] Take Profit order shows as child
- [ ] Both SL and TP have same OCA group

**Check in database:**
```bash
sqlite3 data/slob_state.db "
SELECT * FROM trades
ORDER BY entry_time DESC
LIMIT 1;
"
```

---

## 🛑 Emergency Shutdown

If anything looks wrong:

### Quick Shutdown
```bash
# Press Ctrl+C in terminal running system
# System will gracefully shutdown and save state
```

### Force Close All Positions (If Needed)
```bash
# Login to IB Gateway/TWS
# Go to Account > Trades
# Select all positions
# Right click > Close All
```

### Check What Went Wrong
```bash
# View last 100 log lines
tail -100 logs/trading.log

# Search for errors
grep -i "ERROR\|CRITICAL" logs/trading.log

# Check database state
sqlite3 data/slob_state.db "SELECT * FROM active_setups WHERE state != 'INVALIDATED';"
```

---

## 📈 Success Criteria

**After 6.5 hours of trading (09:30-16:00), you should see:**

- [ ] No CRITICAL errors in logs
- [ ] Connection stable (no disconnections > 5 min)
- [ ] Real-time market data throughout session
- [ ] Any detected setups logged correctly
- [ ] If orders placed, bracket orders structured correctly (parent + SL + TP)
- [ ] No duplicate orders (idempotency working)
- [ ] State saved to database correctly

### Check Final Statistics
```bash
# Check logs for summary
tail -200 logs/trading.log | grep -A 20 "VALIDATION STATISTICS"
```

---

## 🔄 Next Steps

### If Monday Test Successful:
- Continue paper trading for rest of week
- Monitor daily for stability
- Fine-tune parameters if needed
- Prepare for live trading (with real money) when confident

### If Issues Found:
- Document the issue
- Review logs
- Fix the bug
- Re-test before continuing

---

## 🆘 Troubleshooting

### Connection Errors
**Problem:** Cannot connect to IB Gateway
**Solution:**
1. Verify IB Gateway is running
2. Check port in IB Gateway settings (should be 4002)
3. Verify "Enable ActiveX and Socket Clients" is checked
4. Restart IB Gateway

### No Market Data
**Problem:** No ticks received
**Solution:**
1. Verify market is open (09:30-16:00 ET weekdays)
2. Check market data subscription in IB Account Management
3. Try Type 3 (delayed) if Type 1 fails (will get 15-20 min delayed data)

### Orders Not Placing
**Problem:** Bracket orders fail
**Solution:**
1. Check paper_trading flag is FALSE in config
2. Verify account balance is sufficient
3. Check order logs for error messages
4. Verify margin requirements

### Dashboard Not Loading
**Problem:** http://localhost:5000 not accessible
**Solution:**
1. Check if dashboard process is running
2. Verify port 5000 is not in use by another app
3. Check firewall settings

---

**Good luck with Monday's live test! 🚀**

Remember: This is paper trading - no real money at risk. Use this to validate the system works before considering live trading.
