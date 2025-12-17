# Interactive Brokers Setup Guide

**Quick guide for setting up IB paper trading with NQ futures**

---

## 1. Create IB Account

1. Go to [Interactive Brokers](https://www.interactivebrokers.com/)
2. Sign up for account
3. You'll receive TWO accounts:
   - **Live Trading**: U-number (real money)
   - **Paper Trading**: DU-number (virtual money) ✅ Use this!

---

## 2. Install TWS or IB Gateway

**Option A: Trader Workstation (TWS)** - Full GUI
- Download: https://www.interactivebrokers.com/en/trading/tws.php
- Heavier, more features
- **Port**: 7497 (paper), 7496 (live)

**Option B: IB Gateway** - Lightweight (recommended)
- Download: https://www.interactivebrokers.com/en/trading/ibgateway-stable.php
- Lighter, runs in background
- **Port**: 4002 (paper), 4001 (live)

---

## 3. Configure API Access

### In TWS/Gateway:
1. Login with **DU account** (paper trading)
2. Go to: **File → Global Configuration → API → Settings**
3. Enable:
   - ☑️ **Enable ActiveX and Socket Clients**
   - ☑️ **Allow connections from localhost only** (recommended)
   - ☑️ **Read-Only API** (uncheck for trading)
4. **Socket port**: 7497 (TWS) or 4002 (Gateway)
5. Click **OK** and restart TWS/Gateway

### Trusted IPs:
- Add `127.0.0.1` to trusted IPs if prompted

---

## 4. Subscribe to Market Data

**NQ futures requires CME data subscription:**

1. Go to: **Account Management** → **Market Data Subscriptions**
2. Subscribe to: **US Equity and Options Add-On Streaming Bundle**
   - Or specifically: **CME (Chicago Mercantile Exchange)**
3. **Cost**: ~$10-15/month
4. **Free alternatives**:
   - 15-minute delayed data (free, set `data_type='delayed'` in config)
   - Free trial period (usually 1 month)

---

## 5. Install Python Dependencies

```bash
pip install ib_insync
```

Or update all requirements:
```bash
pip install -r requirements.txt
```

---

## 6. Test Connection

### Quick Connection Test:

```python
from ib_insync import IB

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)  # TWS paper

print(f"Connected: {ib.isConnected()}")
print(f"Account: {ib.managedAccounts()}")

ib.disconnect()
```

Expected output:
```
Connected: True
Account: ['DU123456']
```

---

## 7. Run IB Checkpoint Test

**With our system:**

```bash
# Start TWS/Gateway first!
python scripts/ib_checkpoint_test.py 60 DU123456
```

This will:
- ✅ Connect to IB at localhost:7497
- ✅ Subscribe to NQ futures
- ✅ Stream real-time ticks for 60 minutes
- ✅ Validate all components working

---

## 8. Usage in Code

### With IB (NQ futures):
```python
from slob.live import LiveTradingEngine

engine = LiveTradingEngine(
    data_source='ib',           # Use Interactive Brokers
    ib_host='127.0.0.1',
    ib_port=7497,               # TWS paper trading
    ib_client_id=1,
    ib_account='DU123456',      # Your DU account
    symbols=['NQ'],
    paper_trading=True
)

await engine.start()
await engine.run()
```

### With Alpaca (stocks):
```python
engine = LiveTradingEngine(
    data_source='alpaca',       # Use Alpaca
    api_key='YOUR_KEY',
    api_secret='YOUR_SECRET',
    symbols=['AAPL', 'MSFT'],
    paper_trading=True
)

await engine.start()
await engine.run()
```

---

## Common Issues

### 1. "Connection refused"
**Problem**: TWS/Gateway not running
**Solution**: Start TWS/IB Gateway first, login with DU account

### 2. "API not enabled"
**Problem**: API access not configured
**Solution**: Follow Step 3 above, enable API in settings

### 3. "No market data permissions"
**Problem**: CME subscription not active
**Solution**: Subscribe to CME data (Step 4) or use delayed data

### 4. "Contract not found"
**Problem**: Invalid futures symbol or month
**Solution**: System auto-resolves to front month, check logs

### 5. "Port already in use"
**Problem**: Another client using same port/client_id
**Solution**: Change `client_id` to unique value (1-999)

---

## Ports Quick Reference

| Application | Paper Port | Live Port |
|-------------|-----------|-----------|
| **TWS** | 7497 | 7496 |
| **IB Gateway** | 4002 | 4001 |

**Always use Paper Trading ports for testing!**

---

## Security Notes

1. **Never expose IB ports to public internet**
2. **Use localhost only** for connections
3. **Paper trading account only** until validated
4. **30 days paper trading** before going live
5. **Keep TWS/Gateway updated**

---

## Next Steps

1. ✅ Complete IB account setup
2. ✅ Install TWS/Gateway
3. ✅ Enable API access
4. ✅ Subscribe to CME data
5. ✅ Run connection test
6. ✅ Run IB checkpoint test (60 min)
7. ⏭️ 30-day paper trading validation
8. ⏭️ Go-live decision

---

**Ready when you are!** 🚀

Once your IB account is set up, run:
```bash
python scripts/ib_checkpoint_test.py 60 DU123456
```

This will validate the entire Week 1 Data Layer with real NQ futures data.
