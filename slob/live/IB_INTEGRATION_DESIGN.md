# Interactive Brokers Integration Design

**Date**: 2025-12-17
**Status**: 🟡 In Progress
**Purpose**: NQ Futures real-time data & trading via IB TWS API

---

## Overview

Replace Alpaca (stocks only) with Interactive Brokers (NQ futures support) while maintaining same architecture and interface.

---

## IB TWS API vs Alpaca WebSocket

| Feature | Alpaca WebSocket | IB TWS API |
|---------|-----------------|------------|
| **Protocol** | WebSocket (async) | Socket-based (sync) |
| **Library** | `websockets` | `ib_insync` (async wrapper) |
| **Authentication** | API key/secret | Account + host/port |
| **Symbols** | Stocks only | Stocks + Futures + Options |
| **NQ Support** | ❌ No | ✅ Yes (NQZ4, NQH5, etc.) |
| **Paper Trading** | ✅ Yes | ✅ Yes (DU account) |
| **Market Data** | Included | Subscription required ($10-15/mo) |

---

## Architecture Decision

Use **`ib_insync`** library instead of raw `ibapi`:

**Why ib_insync:**
- ✅ Native async/await support (matches our architecture)
- ✅ High-level API (easier to use)
- ✅ Active maintenance
- ✅ Wraps official `ibapi`
- ✅ Good documentation

**Installation:**
```bash
pip install ib_insync
```

---

## Interface Compatibility

`IBWSFetcher` will implement **same interface** as `AlpacaWSFetcher`:

```python
class IBWSFetcher:
    """Interactive Brokers WebSocket-like fetcher for NQ futures."""

    def __init__(self, host: str, port: int, client_id: int, account: str):
        """
        Initialize IB fetcher.

        Args:
            host: IB Gateway/TWS host (default: '127.0.0.1')
            port: Paper trading port 7497 (TWS) or 4002 (Gateway)
            client_id: Unique client ID (1-999)
            account: Paper trading account (e.g., 'DU123456')
        """

    async def connect(self):
        """Connect to IB TWS/Gateway."""

    async def subscribe(self, symbols: List[str]):
        """
        Subscribe to symbols.

        Args:
            symbols: List of futures symbols (e.g., ['NQ'])
        """

    async def listen(self):
        """Start listening for ticks."""

    async def disconnect(self):
        """Disconnect from IB."""

    def get_stats(self) -> dict:
        """Return connection statistics."""

    # Callbacks (same as AlpacaWSFetcher)
    on_tick: Optional[Callable] = None
    on_error: Optional[Callable] = None
```

---

## NQ Futures Contract Specification

**Symbol Format:**
- **Generic**: `NQ` (auto-roll to front month)
- **Specific**: `NQZ4` (Dec 2024), `NQH5` (Mar 2025)

**Contract Details:**
```python
from ib_insync import Future

nq = Future(
    symbol='NQ',
    lastTradeDateOrContractMonth='202412',  # YYYYMM
    exchange='CME',
    currency='USD',
    multiplier=20  # $20 per point
)
```

**Trading Hours (CME):**
- Sunday: 18:00 ET - Friday: 17:00 ET
- LSE session: 09:00-15:30 London = 04:00-10:30 ET
- NYSE session: 15:30+ London = 10:30+ ET

---

## Implementation Plan

### File Structure

```
slob/live/
├── ib_ws_fetcher.py          # IB WebSocket-like fetcher (NEW)
├── ib_contract_manager.py    # NQ contract rolling logic (NEW)
├── alpaca_ws_fetcher.py      # Existing (keep for stocks)
└── live_trading_engine.py    # Update to support both
```

### Configuration

```python
# slob/config/ib_config.py
@dataclass
class IBConfig:
    """Interactive Brokers configuration."""

    # Connection
    host: str = '127.0.0.1'
    port: int = 7497  # TWS paper trading (4002 for IB Gateway)
    client_id: int = 1

    # Account
    account: str = 'DU123456'  # Paper trading account
    paper_trading: bool = True

    # Reconnection
    max_reconnect_attempts: int = 10
    reconnect_delay_seconds: int = 5

    # Market data
    data_type: str = 'realtime'  # or 'delayed' (15min delay, free)
```

---

## Key Differences from Alpaca

### 1. Contract Management

IB requires explicit futures contract specification:

```python
async def _resolve_nq_contract(self):
    """
    Resolve NQ to front month contract.

    Automatically rolls to next contract on expiration.
    """
    contract = Future('NQ', exchange='CME')
    details = await self.ib.reqContractDetailsAsync(contract)

    # Get front month (most liquid)
    front_month = details[0].contract
    return front_month
```

### 2. Tick Types

IB has multiple tick types:

```python
# Subscribe to real-time ticks
self.ib.reqMktData(
    contract=nq_contract,
    genericTickList='',  # Empty = trade ticks only
    snapshot=False,      # Streaming (not snapshot)
    regulatorySnapshot=False
)
```

### 3. Event Handling

`ib_insync` uses event-driven model:

```python
# Register tick handler
self.ib.pendingTickersEvent += self._on_pending_tickers

def _on_pending_tickers(self, tickers):
    """Called when ticks arrive."""
    for ticker in tickers:
        if ticker.hasTick():
            tick = self._convert_ib_tick(ticker)
            asyncio.create_task(self.on_tick(tick))
```

---

## Connection Flow

```
┌─────────────────────────────────────────────────┐
│  1. Start IB Gateway/TWS (paper trading mode)   │
│     - Port 7497 (TWS) or 4002 (Gateway)        │
│     - Enable API connections in settings        │
└─────────────────────────────────────────────────┘
                      │
                      v
┌─────────────────────────────────────────────────┐
│  2. IBWSFetcher.connect()                       │
│     - Connect to localhost:7497                 │
│     - Authenticate with client_id               │
└─────────────────────────────────────────────────┘
                      │
                      v
┌─────────────────────────────────────────────────┐
│  3. Resolve NQ contract                         │
│     - Query CME for front month                 │
│     - Cache contract details                    │
└─────────────────────────────────────────────────┘
                      │
                      v
┌─────────────────────────────────────────────────┐
│  4. Subscribe to market data                    │
│     - reqMktData(nq_contract)                   │
│     - Start receiving ticks                     │
└─────────────────────────────────────────────────┘
                      │
                      v
┌─────────────────────────────────────────────────┐
│  5. Stream ticks to LiveTradingEngine           │
│     - Convert IB tick → Tick dataclass          │
│     - Call on_tick(tick) callback               │
└─────────────────────────────────────────────────┘
```

---

## Error Handling

### Common Errors

1. **"TWS/Gateway not running"**
   - Solution: Start TWS/IB Gateway first

2. **"Market data subscription required"**
   - Solution: Subscribe to CME market data in IB account portal

3. **"Contract not found"**
   - Solution: Check futures contract month/year format

4. **"Already connected from another client_id"**
   - Solution: Use unique client_id for each connection

---

## Testing Strategy

### 1. Unit Tests

```python
# tests/live/test_ib_ws_fetcher.py

@pytest.mark.asyncio
async def test_ib_connection():
    """Test IB connection."""
    fetcher = IBWSFetcher(
        host='127.0.0.1',
        port=7497,
        client_id=1,
        account='DU123456'
    )

    await fetcher.connect()
    assert fetcher.is_connected()
    await fetcher.disconnect()

@pytest.mark.asyncio
async def test_nq_subscription():
    """Test NQ subscription."""
    fetcher = IBWSFetcher(...)
    await fetcher.connect()

    ticks = []
    fetcher.on_tick = lambda tick: ticks.append(tick)

    await fetcher.subscribe(['NQ'])
    await asyncio.sleep(10)  # Collect ticks for 10s

    assert len(ticks) > 0
    assert all(tick.symbol == 'NQ' for tick in ticks)
```

### 2. Integration Test

Run 1-hour test similar to Week 1 checkpoint:

```bash
python scripts/ib_checkpoint_test.py 60
```

---

## Migration Path

### Phase 1: Alpaca (Current)
- ✅ Validate Week 1 Data Layer with stocks
- ✅ Checkpoint test passing

### Phase 2: IB Implementation (This Week)
- 🟡 Implement `ib_ws_fetcher.py`
- 🟡 Test with IB paper trading account
- 🟡 1-hour checkpoint test with NQ

### Phase 3: Dual Support
```python
# slob/live/live_trading_engine.py

class LiveTradingEngine:
    def __init__(self, data_source: str = 'ib', **kwargs):
        """
        Initialize engine.

        Args:
            data_source: 'ib' for Interactive Brokers, 'alpaca' for stocks
        """
        if data_source == 'ib':
            self.ws_fetcher = IBWSFetcher(...)
        elif data_source == 'alpaca':
            self.ws_fetcher = AlpacaWSFetcher(...)
```

### Phase 4: Production
- 🟡 30 days paper trading with NQ
- 🟡 Validation report
- 🟡 Go-live decision

---

## Code Example

```python
# Example usage
from slob.live import IBWSFetcher, LiveTradingEngine

# Create IB fetcher
ib_fetcher = IBWSFetcher(
    host='127.0.0.1',
    port=7497,  # TWS paper trading
    client_id=1,
    account='DU123456'
)

# Create engine with IB
engine = LiveTradingEngine(
    data_source='ib',
    ib_fetcher=ib_fetcher,
    symbols=['NQ'],
    paper_trading=True
)

# Start trading
await engine.start()
await engine.run()
```

---

## Next Steps

1. ✅ **Design complete** - This document
2. 🟡 **Implementation** - `ib_ws_fetcher.py` (2-3 hours)
3. ⏭️ **IB account setup** - User creates paper trading account
4. ⏭️ **Connection test** - Verify IB Gateway connection
5. ⏭️ **Checkpoint test** - 1 hour with NQ futures
6. ⏭️ **Integration** - Connect to SetupTracker

---

**Status**: 🟡 Design Complete, Ready for Implementation
**Blockers**: None (can implement now, test when IB account ready)
**ETA**: 2-3 hours implementation + testing when account ready

---

**Requirements for Testing:**
- ✅ IB paper trading account (DU number)
- ✅ TWS or IB Gateway installed locally
- ✅ API enabled in TWS settings
- ✅ CME market data subscription (for NQ)
- ✅ Port 7497 (TWS) or 4002 (Gateway) accessible
