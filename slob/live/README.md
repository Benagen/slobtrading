# Live Trading Module

> ⚠️ **DATA SOURCE NOTICE**: This system uses **Interactive Brokers (IB)**, not Alpaca Markets.

**Status**: Production Ready (v0.9.0)
**Current Phase**: Phase 7 - Live Trading Operations

## Overview

The live trading module provides real-time trading capabilities for the 5/1 SLOB trading system using Interactive Brokers as the data source and broker. It transforms the offline backtest system into a production-ready live trading engine.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│             LIVE TRADING SYSTEM (IB-BASED)                   │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐    ┌───────────────┐   ┌───────────────┐ │
│  │  IB Gateway  │───>│  Tick Buffer  │──>│   Candle      │ │
│  │  (ib_insync) │    │  (asyncio)    │   │  Aggregator   │ │
│  └──────────────┘    └───────────────┘   └───────────────┘ │
│                                                    │          │
│                                                    v          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │          EVENT BUS (async handlers)                  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                    │          │
│       ┌────────────────────┬───────────────────┬──┴───┐     │
│       v                    v                   v      v      │
│  ┌─────────┐         ┌──────────┐       ┌─────────────────┐ │
│  │ Candle  │         │  Setup   │       │  Order          │ │
│  │ Store   │         │  Tracker │       │  Executor       │ │
│  │(SQLite) │         │  (Live)  │       │  (IB Orders)    │ │
│  └─────────┘         └──────────┘       └─────────────────┘ │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Components

### 1. IBWSFetcher (`ib_ws_fetcher.py`)

Real-time data client for Interactive Brokers using `ib_insync` library.

**Features:**
- Async IB Gateway/TWS connection via `ib_insync`
- Market data subscription (live or delayed)
- Tick message parsing (symbol, price, size, timestamp)
- Automatic reconnection with exponential backoff (1s → 2s → 4s → ... → 60s max)
- Circuit breaker (max 10 reconnection attempts)
- Health monitoring with heartbeat (30s interval)
- Safe mode on persistent failures

**Usage:**
```python
from slob.live.ib_ws_fetcher import IBWSFetcher

async def on_tick(tick):
    print(f"Tick: {tick.symbol} @ {tick.price}")

fetcher = IBWSFetcher(
    host='ib-gateway',      # IB Gateway hostname
    port=4002,              # Paper trading port (live: 4001)
    client_id=1,
    account='DU123456',     # Your IB paper account
    on_tick=on_tick
)

await fetcher.connect()
await fetcher.subscribe(["NQ"])  # Subscribe to NQ futures
await fetcher.listen()
```

**Tick Data Structure:**
```python
class Tick:
    symbol: str
    price: float
    size: int          # Also accessible as .volume
    timestamp: datetime
```

**Connection Ports:**
- **Paper Trading**: 4002 (default)
- **Live Trading**: 4001
- **VNC**: 5900 (for GUI access)

### 2. TickBuffer (`tick_buffer.py`)

Async queue for buffering market ticks with backpressure handling.

**Features:**
- `asyncio.Queue` with max 10,000 ticks
- Backpressure handling (drops oldest ticks on overflow)
- TTL-based eviction (60-second default)
- Auto-flush background task
- Statistics tracking
- Stockholm timezone support

**Usage:**
```python
from slob.live.tick_buffer import TickBuffer

buffer = TickBuffer(max_size=10000, ttl_seconds=60)

# Enqueue
await buffer.enqueue(tick)

# Dequeue
tick = await buffer.dequeue(timeout=1.0)

# Auto-flush old ticks
asyncio.create_task(buffer.auto_flush(interval=10))

# Get stats
stats = buffer.get_stats()
print(f"Utilization: {buffer.utilization():.1%}")
```

### 3. CandleAggregator (`candle_aggregator.py`)

Aggregates market ticks into M1 (1-minute) OHLCV candles with timezone support.

**Features:**
- Per-symbol candle tracking
- Minute-aligned timestamps (Stockholm timezone: Europe/Stockholm)
- Gap detection and filling (flat candles for gaps ≤2 minutes)
- Candle-close event emission
- Statistics tracking

**Usage:**
```python
from slob.live.candle_aggregator import CandleAggregator

async def on_candle(candle):
    print(f"Candle: {candle}")

aggregator = CandleAggregator(on_candle_complete=on_candle)

# Process ticks
await aggregator.process_tick(tick)

# Force complete all active candles (on shutdown)
await aggregator.force_complete_all()
```

**Candle Data Structure:**
```python
class Candle:
    symbol: str
    timestamp: datetime  # Stockholm timezone (Europe/Stockholm)
    open: float
    high: float
    low: float
    close: float
    volume: int
    tick_count: int
```

### 4. EventBus (`event_bus.py`)

Typed event dispatcher for the live trading system.

**Features:**
- Typed event registration (14+ event types)
- Multiple handlers per event type
- Async and sync handler support
- Error isolation (failed handlers don't affect others)
- Optional event history (max 1,000 events)

**Event Types:**
```python
class EventType(Enum):
    # Data events
    TICK_RECEIVED = "tick_received"
    CANDLE_COMPLETED = "candle_completed"

    # Setup events
    SETUP_DETECTED = "setup_detected"
    SETUP_INVALIDATED = "setup_invalidated"

    # Trading events
    ORDER_PLACED = "order_placed"
    ORDER_FILLED = "order_filled"
    ORDER_REJECTED = "order_rejected"

    # System events
    WEBSOCKET_CONNECTED = "websocket_connected"
    WEBSOCKET_DISCONNECTED = "websocket_disconnected"
    CIRCUIT_BREAKER_TRIGGERED = "circuit_breaker_triggered"
    SAFE_MODE_ENTERED = "safe_mode_entered"
```

**Usage:**
```python
from slob.live.event_bus import EventBus, EventType

bus = EventBus(enable_history=True)

# Subscribe using decorator
@bus.on(EventType.CANDLE_COMPLETED)
async def handle_candle(event):
    print(f"Candle completed: {event.data}")

# Or subscribe directly
bus.subscribe(EventType.TICK_RECEIVED, handle_tick)

# Emit event
await bus.emit(EventType.CANDLE_COMPLETED, candle)

# Emit and wait for all handlers to complete (critical events)
await bus.emit_and_wait(EventType.CIRCUIT_BREAKER_TRIGGERED, error)
```

### 5. CandleStore (`candle_store.py`)

SQLite persistence layer for historical M1 candles.

**Features:**
- Efficient bulk inserts (`executemany`)
- Time-range queries
- Symbol-based filtering
- Automatic schema creation
- WAL mode for concurrent access

**Schema:**
```sql
CREATE TABLE candles (
    symbol TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    tick_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timestamp)
);

CREATE INDEX idx_candles_symbol_time ON candles (symbol, timestamp DESC);
```

**Usage:**
```python
from slob.live.candle_store import CandleStore

store = CandleStore(db_path='data/candles.db')

# Save single candle
store.save_candle(candle)

# Bulk save
store.save_candles(candles)

# Query candles
df = store.get_candles('NQ', start_time, end_time)

# Get latest candle
latest = store.get_latest_candle('NQ')

# Get stats
stats = store.get_stats()
print(f"Total candles: {stats['total_candles']}")
print(f"DB size: {stats['db_size_mb']} MB")
```

### 6. SetupTracker (`setup_tracker.py`)

Real-time setup detection and state tracking.

**Features:**
- Event-driven state machine (no look-ahead bias)
- States: WATCHING_LIQ1, WATCHING_CONSOL, WATCHING_LIQ2, WAITING_ENTRY, SETUP_COMPLETE, INVALIDATED
- Incremental consolidation tracking
- Multi-setup support (track multiple concurrent setups)
- Redis + SQLite persistence

### 7. OrderExecutor (`order_executor.py`)

IB order execution with bracket orders.

**Features:**
- IB bracket orders (entry + stop loss + take profit)
- Retry logic with exponential backoff
- Order fill tracking
- Position management
- Risk validation

### 8. LiveTradingEngine (`live_trading_engine.py`)

Main orchestrator that integrates all components.

**Features:**
- Component lifecycle management
- Background task coordination
- Health monitoring (8-second heartbeat)
- Graceful shutdown
- Signal handlers (SIGINT, SIGTERM)

**Usage:**
```python
from slob.live.live_trading_engine import LiveTradingEngine

engine = LiveTradingEngine(
    ib_host="ib-gateway",
    ib_port=4002,
    ib_client_id=1,
    ib_account="DU123456",
    symbols=["NQ"],
    db_path="data/candles.db"
)

# Setup signal handlers for graceful shutdown
engine.setup_signal_handlers()

# Start and run
await engine.start()
await engine.run()
```

## Setup

### 1. Install Interactive Brokers

**Option A: IB Gateway (Recommended for servers)**
```bash
# Download from:
# https://www.interactivebrokers.com/en/trading/ibgateway-stable.php

# Or use Docker (recommended):
docker pull ghcr.io/gnzsnz/ib-gateway:stable
```

**Option B: TWS (Trader Workstation)**
- For desktop/GUI usage
- Download from IB website

**See**: [IB_SETUP_GUIDE.md](../IB_SETUP_GUIDE.md) for detailed setup

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

**Key IB dependencies:**
- `ib_insync>=0.9.86` - IB API wrapper (asyncio-based)
- `websockets>=12.0` - WebSocket support
- `aiohttp>=3.9.0` - Async HTTP client
- `redis>=5.0.0` - State storage

### 3. Configure Environment

```bash
# Copy template
cp .env.template .env

# Edit with your IB credentials
nano .env
```

**Required IB variables:**
```bash
# Interactive Brokers Configuration
IB_GATEWAY_HOST=ib-gateway    # Or localhost for local
IB_GATEWAY_PORT=4002           # Paper: 4002, Live: 4001
IB_CLIENT_ID=1
IB_ACCOUNT=DU123456            # Your IB paper account

# Optional
SYMBOLS=NQ                     # Comma-separated
DB_PATH=data/candles.db
LOG_LEVEL=INFO
```

**NOT USED** (legacy Alpaca variables - ignore):
- ~~ALPACA_API_KEY~~
- ~~ALPACA_API_SECRET~~

### 4. Setup Secrets (Production)

For production deployment with Docker secrets:

```bash
# See detailed guide:
cat docs/SECRETS_SETUP.md

# Quick setup:
./scripts/generate_secrets.sh
```

### 5. Test IB Connection

```bash
# Quick connection test
python scripts/test_ib_connection.py

# Or use checkpoint test
python scripts/ib_checkpoint_test.py 60 DU123456
```

**Expected output:**
```
✅ Connected to IB Gateway
✅ Market data subscription active
✅ Receiving ticks for NQ
```

### 6. Run Paper Trading

```bash
# Run 24-hour paper trading validation
python scripts/run_paper_trading.py \
    --account DU123456 \
    --gateway \
    --duration 24

# Or run in monitor-only mode (no orders)
python scripts/run_paper_trading.py \
    --account DU123456 \
    --monitor-only
```

**See**: [PAPER_TRADING_GUIDE.md](../PAPER_TRADING_GUIDE.md) for validation criteria

## Current Implementation Status

| Component | Status | File | Tests |
|-----------|--------|------|-------|
| IB Connection | ✅ Complete | `ib_ws_fetcher.py` | ✅ |
| Tick Buffer | ✅ Complete | `tick_buffer.py` | ✅ |
| Candle Aggregator | ✅ Complete | `candle_aggregator.py` | ✅ |
| Event Bus | ✅ Complete | `event_bus.py` | ✅ |
| Candle Store | ✅ Complete | `candle_store.py` | ✅ |
| Setup Tracker | ✅ Complete | `setup_tracker.py` | ✅ |
| State Manager | ✅ Complete | `state_manager.py` | ✅ |
| Order Executor | ✅ Complete | `order_executor.py` | ✅ |
| Live Engine | ✅ Complete | `live_trading_engine.py` | ✅ |
| Risk Manager | ✅ Complete | `risk_manager.py` | ✅ |
| Dashboard | ✅ Complete | `../monitoring/dashboard.py` | ⏸️ |

**Total code**: ~5,000+ lines (components + tests)

## Deployment

### Local Development

```bash
# Run locally with IB Gateway/TWS
python -m slob.live.live_trading_engine
```

### Docker Deployment

```bash
# Build and start all services
docker-compose up -d

# Services:
# - redis: State storage (port 6379)
# - ib-gateway: IB Gateway (ports 4002, 5900)
# - slob-bot: Trading bot
# - slob-dashboard: Web dashboard (port 5000)
```

**See**: [DEPLOYMENT.md](../DEPLOYMENT.md) for full deployment guide

### VPS Deployment (Production)

```bash
# Deploy to production VPS
./scripts/deploy.sh production

# Monitor
./scripts/monitor.sh
```

## Troubleshooting

### IB Connection Issues

**Problem**: `ConnectionError: connection refused`

**Solutions:**
1. Verify IB Gateway/TWS is running
2. Check port (Paper: 4002, Live: 4001)
3. Enable API connections in IB Gateway settings
4. Accept API connection dialog in VNC

### No Ticks Received

**Problem**: Connected but tick_count = 0

**Solutions:**
1. Check market hours (NQ futures: Sunday 18:00 ET - Friday 17:00 ET)
2. Verify market data subscription (delayed vs real-time)
3. Check if paper account has market data permissions
4. Accept "market data" dialog in IB Gateway

### API Read-Only Mode

**Problem**: `Error 321: The API interface is currently in Read-Only mode`

**Solutions:**
1. Access IB Gateway via VNC (port 5900)
2. Click "OK" on "API client needs write access" dialog
3. Or: Pre-configure in IB Gateway settings

### Database Locked

**Problem**: `sqlite3.OperationalError: database is locked`

**Solutions:**
1. WAL mode already enabled in CandleStore
2. Reduce concurrent writes (use bulk inserts)
3. Check for long-running transactions

## Performance Metrics

### Expected Throughput

**Single symbol (NQ):**
- Ticks/second: 1-10 (normal), up to 100 (high volatility)
- Candles/hour: 60 (M1 candles)
- DB writes/hour: 60 (one per candle)

**Buffer utilization:**
- Normal: <5%
- High volatility: 10-20%
- Critical: >80% (increase buffer size)

### Memory Usage

- Base engine: ~100 MB
- Per 10,000 ticks in buffer: ~5 MB
- Per 1,000 candles in DB: ~0.5 MB
- Total (24h runtime): ~200-500 MB

## Testing

### Unit Tests

```bash
# Run all live module tests
pytest tests/live/

# Run specific test
pytest tests/live/test_ib_ws_fetcher.py

# Run with coverage
pytest tests/live/ --cov=slob.live --cov-report=html
```

### Integration Tests

```bash
# Full end-to-end test
pytest tests/integration/test_live_engine_flow.py

# IB connection test
pytest tests/integration/test_ib_connection.py
```

### Paper Trading Validation

```bash
# 48-hour validation run
python scripts/run_paper_trading.py \
    --account DU123456 \
    --gateway \
    --duration 48 \
    --strict
```

**Success criteria:**
- ✅ Uptime: 100% (no crashes)
- ✅ IB Connection: Stable for entire duration
- ✅ Candles received: >0
- ✅ Candles persisted: Matches generated
- ✅ No look-ahead bias detected

## Migration from Alpaca (Historical)

> **Note**: This system previously used Alpaca Markets. It was migrated to Interactive Brokers for:
> - Better futures trading support (NQ contracts)
> - More reliable real-time data
> - Direct broker integration (no separate data provider)
> - Lower latency

Old Alpaca components have been removed. If you find references to `AlpacaWSFetcher` or `ALPACA_*` variables, they are obsolete.

## Support & Resources

**Documentation:**
- [Main README](../README.md) - System overview
- [IB Setup Guide](../IB_SETUP_GUIDE.md) - IB Gateway configuration
- [Deployment Guide](../DEPLOYMENT.md) - Production deployment
- [Paper Trading Guide](../PAPER_TRADING_GUIDE.md) - Validation process
- [Operational Runbook](../OPERATIONAL_RUNBOOK.md) - Daily operations

**For issues:**
1. Check logs: `logs/trading.log`
2. Review statistics: Call `.get_stats()` on any component
3. Enable DEBUG logging: `LOG_LEVEL=DEBUG` in `.env`
4. Check IB Gateway logs via VNC or `docker logs ib-gateway`

**IB Resources:**
- [IB API Documentation](https://interactivebrokers.github.io/tws-api/)
- [ib_insync Documentation](https://ib-insync.readthedocs.io/)
- [IB Market Data Guide](https://www.interactivebrokers.com/en/index.php?f=14193)

---

**Status**: ✅ Production Ready (v0.9.0) - IB-based architecture
