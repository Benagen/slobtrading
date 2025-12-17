# Test Suite for SLOB Trading System

**Status**: Week 1+ Tests Complete
**Coverage Target**: 80%+
**Total Test Files**: 6 (5 unit + 1 integration)

---

## Overview

Comprehensive test suite for the Week 1 Data Layer components. Tests cover unit functionality, integration flows, error handling, and edge cases.

### Test Structure

```
tests/
├── __init__.py
├── README.md (this file)
├── live/                          # Unit tests
│   ├── __init__.py
│   ├── test_alpaca_ws_fetcher.py  # WebSocket client tests
│   ├── test_tick_buffer.py         # Async buffer tests
│   ├── test_candle_aggregator.py   # Candle aggregation tests
│   ├── test_event_bus.py           # Event system tests
│   └── test_candle_store.py        # SQLite persistence tests
└── integration/                    # Integration tests
    ├── __init__.py
    └── test_live_engine_flow.py    # End-to-end data flow tests
```

---

## Running Tests

### Quick Start

```bash
# Install test dependencies
pip install -r requirements.txt

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=slob --cov-report=html --cov-report=term-missing -v

# Run specific test file
pytest tests/live/test_event_bus.py -v
```

### Using Test Runner Script

```bash
# Run all tests
./scripts/run_tests.sh all

# Run unit tests only
./scripts/run_tests.sh unit

# Run integration tests only
./scripts/run_tests.sh integration

# Run specific component tests
./scripts/run_tests.sh alpaca
./scripts/run_tests.sh buffer
./scripts/run_tests.sh aggregator
./scripts/run_tests.sh eventbus
./scripts/run_tests.sh store

# Run with coverage
./scripts/run_tests.sh all coverage
```

---

## Test Files

### 1. `test_alpaca_ws_fetcher.py` (Unit Tests)

**Component**: AlpacaWSFetcher
**Test Count**: ~20 tests
**Coverage**: WebSocket connection, authentication, message parsing, reconnection

**Key Test Cases:**
- ✅ Successful connection and authentication
- ✅ Failed authentication handling
- ✅ Authentication timeout
- ✅ Symbol subscription
- ✅ Tick message parsing (trade data)
- ✅ Multiple message processing
- ✅ Exponential backoff reconnection
- ✅ Circuit breaker after max attempts
- ✅ Safe mode entry
- ✅ Graceful disconnection
- ✅ Error handler invocation
- ✅ Timestamp parsing (ISO format)
- ✅ Statistics tracking
- ✅ Resubscribe after reconnect

**Example:**
```python
@pytest.mark.asyncio
async def test_successful_connection(fetcher, mock_websocket):
    """Test successful WebSocket connection and authentication."""
    auth_response = json.dumps([{
        'T': 'success',
        'msg': 'authenticated'
    }])
    mock_websocket.recv.return_value = auth_response

    with patch('websockets.connect', return_value=mock_websocket):
        await fetcher.connect()

        assert fetcher.state == ConnectionState.CONNECTED
        assert fetcher.reconnect_attempts == 0
```

---

### 2. `test_tick_buffer.py` (Unit Tests)

**Component**: TickBuffer
**Test Count**: ~25 tests
**Coverage**: Async queue operations, backpressure, TTL eviction, concurrency

**Key Test Cases:**
- ✅ Enqueue/dequeue single tick
- ✅ Multiple tick processing
- ✅ Buffer overflow handling
- ✅ Overflow callback invocation
- ✅ Dequeue timeout
- ✅ Blocking dequeue until tick available
- ✅ TTL-based eviction
- ✅ Auto-flush background task
- ✅ Utilization calculation
- ✅ Buffer clearing
- ✅ Graceful shutdown
- ✅ Concurrent enqueue/dequeue
- ✅ FIFO ordering guarantee
- ✅ Emergency flush on overflow
- ✅ Edge cases (zero max size, small TTL)
- ✅ Multiple concurrent producers

**Example:**
```python
@pytest.mark.asyncio
async def test_concurrent_enqueue_dequeue(buffer):
    """Test concurrent enqueueing and dequeueing."""
    tick_count = 100
    received_ticks = []

    async def producer():
        for i in range(tick_count):
            tick = Tick(...)
            await buffer.enqueue(tick)

    async def consumer():
        while len(received_ticks) < tick_count:
            tick = await buffer.dequeue(timeout=1.0)
            if tick:
                received_ticks.append(tick)

    await asyncio.gather(producer(), consumer())

    assert len(received_ticks) == tick_count
```

---

### 3. `test_candle_aggregator.py` (Unit Tests)

**Component**: CandleAggregator + Candle
**Test Count**: ~30 tests
**Coverage**: Tick aggregation, candle formation, gap detection, OHLCV calculation

**Key Test Cases:**
- ✅ Candle initialization
- ✅ First tick updates (O=H=L=C)
- ✅ Multiple tick updates (correct OHLCV)
- ✅ Candle completion check
- ✅ Single tick processing
- ✅ Multiple ticks same minute
- ✅ Candle completion on minute change
- ✅ Multiple symbol tracking
- ✅ Gap detection
- ✅ Automatic gap filling
- ✅ Large gap not filled (exceeds threshold)
- ✅ Flat candle properties (gap-filled)
- ✅ Force complete all candles
- ✅ Minute-aligned timestamp calculation
- ✅ Callback error handling
- ✅ Sync/async callback support
- ✅ Rapid tick stream handling

**Example:**
```python
@pytest.mark.asyncio
async def test_candle_completion_on_minute_change(aggregator):
    """Test candle completion when minute changes."""
    completed_candles = []

    async def on_candle(candle):
        completed_candles.append(candle)

    aggregator.on_candle_complete = on_candle

    # First tick at 14:30:xx
    tick1 = Tick('NQ', 15300.0, 10, datetime(2024, 1, 15, 14, 30, 30), 'IEX')
    await aggregator.process_tick(tick1)

    # Second tick at 14:31:xx (minute changed)
    tick2 = Tick('NQ', 15305.0, 10, datetime(2024, 1, 15, 14, 31, 10), 'IEX')
    await aggregator.process_tick(tick2)

    await asyncio.sleep(0.1)

    assert len(completed_candles) == 1
    assert completed_candles[0].timestamp == datetime(2024, 1, 15, 14, 30, 0)
```

---

### 4. `test_event_bus.py` (Unit Tests)

**Component**: EventBus + Event + EventType
**Test Count**: ~35 tests
**Coverage**: Event subscription, emission, handlers, error isolation, history

**Key Test Cases:**
- ✅ Event creation and representation
- ✅ All event types defined (14 types)
- ✅ Handler subscription
- ✅ Multiple handlers per event
- ✅ Handler unsubscription
- ✅ Decorator subscription
- ✅ Async handler execution
- ✅ Sync handler execution
- ✅ Multiple handler emission
- ✅ Emit with no handlers
- ✅ emit_and_wait blocks until complete
- ✅ Handler error isolation
- ✅ Event history recording
- ✅ Event history filtering by type
- ✅ Event history size limit
- ✅ Handler count retrieval
- ✅ Statistics tracking
- ✅ Handler clearing
- ✅ Graceful shutdown
- ✅ Custom timestamp support
- ✅ Concurrent emit
- ✅ High-frequency event stream

**Example:**
```python
@pytest.mark.asyncio
async def test_handler_error_isolation(bus):
    """Test that handler errors don't affect other handlers."""
    received_good = []

    @bus.on(EventType.CANDLE_COMPLETED)
    async def bad_handler(event):
        raise ValueError("Test error")

    @bus.on(EventType.CANDLE_COMPLETED)
    async def good_handler(event):
        received_good.append(event)

    await bus.emit(EventType.CANDLE_COMPLETED, {'test': 'data'})
    await asyncio.sleep(0.1)

    # Good handler should still receive event
    assert len(received_good) == 1
    assert bus.handler_errors == 1
```

---

### 5. `test_candle_store.py` (Unit Tests)

**Component**: CandleStore
**Test Count**: ~30 tests
**Coverage**: SQLite operations, queries, persistence, concurrent access

**Key Test Cases:**
- ✅ Database initialization
- ✅ Schema creation
- ✅ Save single candle
- ✅ Save incomplete candle (should skip)
- ✅ Bulk save candles
- ✅ Filter incomplete candles in bulk
- ✅ Replace duplicate candle
- ✅ Query all candles
- ✅ Query with time range
- ✅ Query with limit
- ✅ Empty query result
- ✅ Get latest candle
- ✅ Get candle count (total and per symbol)
- ✅ Get symbol list
- ✅ Get date range for symbol
- ✅ Delete candles (all or before time)
- ✅ Vacuum database
- ✅ Statistics retrieval
- ✅ Connection management
- ✅ Multiple store instances
- ✅ DataFrame structure validation
- ✅ Concurrent writes (WAL mode)
- ✅ Edge cases (zero volume, special chars, old timestamps)

**Example:**
```python
def test_get_candles_time_range(store):
    """Test querying candles with time range."""
    candles = []
    base_time = datetime(2024, 1, 15, 14, 30, 0)

    for i in range(10):
        candle = Candle(symbol='NQ', timestamp=base_time + timedelta(minutes=i))
        candle.open = 15300.0
        # ... set OHLCV
        candles.append(candle)

    store.save_candles(candles)

    # Query range: 14:32 to 14:37
    start_time = base_time + timedelta(minutes=2)
    end_time = base_time + timedelta(minutes=7)

    df = store.get_candles('NQ', start_time=start_time, end_time=end_time)

    assert len(df) == 6  # Inclusive range
```

---

### 6. `test_live_engine_flow.py` (Integration Tests)

**Component**: LiveTradingEngine (full system)
**Test Count**: ~10 tests
**Coverage**: End-to-end data flow, component integration, lifecycle, error handling

**Key Test Cases:**
- ✅ Tick-to-candle data flow
- ✅ Candle persistence to database
- ✅ Event bus integration across components
- ✅ Multiple symbol handling
- ✅ Buffer backpressure under load
- ✅ Gap detection and filling
- ✅ Statistics tracking across all components
- ✅ Graceful shutdown
- ✅ Force complete candles on shutdown
- ✅ Error handling (candle handler errors, database errors)

**Example:**
```python
@pytest.mark.asyncio
async def test_tick_to_candle_flow(engine):
    """Test tick processing through to candle aggregation."""
    await engine.start()

    completed_candles = []

    @engine.event_bus.on(EventType.CANDLE_COMPLETED)
    async def on_candle(event):
        completed_candles.append(event.data)

    # Simulate ticks for 2 minutes
    base_time = datetime(2024, 1, 15, 14, 30, 0)

    # Minute 1: 14:30
    for i in range(5):
        tick = Tick('NQ', 15300.0 + i, 10, base_time + timedelta(seconds=i * 10), 'IEX')
        await engine._on_tick(tick)

    # Process ticks
    for _ in range(5):
        tick = await engine.tick_buffer.dequeue(timeout=0.1)
        if tick:
            await engine.candle_aggregator.process_tick(tick)

    # Minute 2: 14:31 (triggers completion)
    # ... similar processing ...

    await asyncio.sleep(0.2)

    assert len(completed_candles) >= 1
```

---

## Test Markers

Tests are marked for categorization:

```python
@pytest.mark.unit          # Unit test
@pytest.mark.integration   # Integration test
@pytest.mark.slow          # Long-running test
@pytest.mark.asyncio       # Async test
@pytest.mark.requires_db   # Needs database
@pytest.mark.requires_network  # Needs network
```

**Run by marker:**
```bash
pytest -m unit           # Unit tests only
pytest -m integration    # Integration tests only
pytest -m "not slow"     # Skip slow tests
```

---

## Coverage Report

### Target Coverage: 80%+

**Generate coverage report:**
```bash
pytest tests/ --cov=slob --cov-report=html --cov-report=term-missing -v
```

**View HTML report:**
```bash
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

**Expected coverage by component:**
- AlpacaWSFetcher: ~85%
- TickBuffer: ~90%
- CandleAggregator: ~85%
- EventBus: ~90%
- CandleStore: ~85%
- LiveTradingEngine: ~70% (harder to test due to WebSocket mocking)

---

## Continuous Integration

### CI Pipeline (TODO)

```yaml
# .github/workflows/tests.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests
        run: pytest tests/ --cov=slob --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

---

## Test Development Guidelines

### Writing New Tests

1. **Follow naming conventions**:
   - Test files: `test_<component>.py`
   - Test classes: `Test<Component>`
   - Test functions: `test_<behavior>`

2. **Use fixtures for setup**:
   ```python
   @pytest.fixture
   def component():
       return Component(config)
   ```

3. **Test one behavior per test**:
   ```python
   def test_buffer_enqueues_tick():  # ✅ Good
       ...

   def test_buffer_operations():  # ❌ Too broad
       ...
   ```

4. **Use descriptive assertions**:
   ```python
   assert buffer.size() == 10  # ✅ Good
   assert x  # ❌ Unclear
   ```

5. **Mark async tests**:
   ```python
   @pytest.mark.asyncio
   async def test_async_operation():
       ...
   ```

### Test Structure

```python
# Arrange
buffer = TickBuffer(max_size=10)
tick = Tick(...)

# Act
await buffer.enqueue(tick)

# Assert
assert buffer.size() == 1
```

---

## Troubleshooting

### Common Issues

**1. "ModuleNotFoundError: No module named 'slob'"**
```bash
# Add project root to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:/path/to/slobprototype"

# Or run from project root
cd /path/to/slobprototype
pytest tests/
```

**2. "RuntimeWarning: coroutine was never awaited"**
- Ensure async test functions have `@pytest.mark.asyncio`
- Use `await` for all async calls

**3. "Database is locked"**
- Use temp databases in fixtures
- Ensure proper cleanup with `yield`
- Check that WAL mode is enabled

**4. Tests hanging**
- Add timeouts to async operations
- Check for infinite loops in test code
- Ensure proper shutdown of background tasks

---

## Next Steps (Week 2+)

### Additional Test Coverage Needed:

1. **Week 2 Components** (not yet built):
   - SetupTracker tests
   - IncrementalConsolidationDetector tests
   - StateManager tests (Redis + SQLite)
   - OrderExecutor tests

2. **Replay Tests** (Week 2):
   - No look-ahead bias validation
   - Compare live vs backtest detection timing
   - Feed historical data candle-by-candle

3. **Performance Tests**:
   - Load testing (1000+ ticks/sec)
   - Memory leak detection
   - Latency benchmarking

4. **End-to-End Tests**:
   - Full trading cycle (setup detection → order → fill)
   - Paper trading validation
   - Multi-day continuous operation

---

## Resources

- **Pytest Documentation**: https://docs.pytest.org/
- **pytest-asyncio**: https://pytest-asyncio.readthedocs.io/
- **pytest-cov**: https://pytest-cov.readthedocs.io/
- **Testing Best Practices**: https://realpython.com/pytest-python-testing/

---

**Last Updated**: 2025-12-16
**Status**: Week 1 Tests Complete (100% of planned unit + integration tests)
