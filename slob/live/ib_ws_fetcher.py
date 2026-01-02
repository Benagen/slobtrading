
import asyncio
import logging
import math # För att kolla efter NaN
from typing import List, Callable, Optional, Any
from datetime import datetime

# Importera biblioteket direkt
from ib_insync import IB, Stock, Future, Forex, Contract, Ticker

class Tick:
    """
    Enkel Tick-klass.
    Fixar buggen genom att ha både .volume och .size som synonymer.
    """
    def __init__(self, symbol: str, price: float, timestamp: datetime, volume: int = 0):
        self.symbol = symbol
        self.price = price
        self.timestamp = timestamp
        self.volume = volume
        self.size = volume # <-- FIX: CandleAggregator vill ha .size

class IBWSFetcher:
    """
    Hämtar data från Interactive Brokers med reconnection support.

    Features:
    - Exponential backoff reconnection (max 10 attempts)
    - Heartbeat monitoring (every 30s)
    - Auto-reconnection on connection loss
    - Safe mode on persistent failures
    """
    def __init__(self, host='127.0.0.1', port=4002, client_id=1, account='',
                 max_reconnect_attempts=10, heartbeat_interval=30):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.account = account
        self.ib = None
        self.connected = False
        self.subscriptions = []
        self.on_tick: Optional[Callable[[Tick], Any]] = None
        self.logger = logging.getLogger(__name__)

        # Reconnection configuration
        self.max_reconnect_attempts = max_reconnect_attempts
        self.heartbeat_interval = heartbeat_interval
        self.reconnect_count = 0
        self.safe_mode = False
        self.running = False

        # Background tasks
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._pending_tasks: set = set()  # Track fire-and-forget tasks

    async def connect(self):
        """
        Connect to IB Gateway/TWS with retry logic.

        Wrapper for connect_with_retry() for backward compatibility.
        """
        return await self.connect_with_retry()

    async def connect_with_retry(self, max_attempts: Optional[int] = None) -> bool:
        """
        Connect to IB with exponential backoff retry.

        Args:
            max_attempts: Override default max_reconnect_attempts

        Returns:
            True if connected successfully, False otherwise
        """
        if max_attempts is None:
            max_attempts = self.max_reconnect_attempts

        self.ib = IB()
        attempt = 0

        while attempt < max_attempts:
            try:
                self.logger.info(f"Connecting to IB at {self.host}:{self.port} (attempt {attempt + 1}/{max_attempts})")
                await self.ib.connectAsync(self.host, self.port, self.client_id)
                self.connected = True
                self.reconnect_count = 0  # Reset on successful connection

                # Request Delayed Market Data (Type 3)
                # Market Data Types:
                # 1 = Live (real-time, free for paper accounts, requires subscription for live)
                # 2 = Frozen (last available, free)
                # 3 = Delayed (15-20 min delay, free)
                # 4 = Delayed frozen (frozen delayed, free)
                market_data_type = 3  # Delayed (no subscription needed)

                try:
                    self.ib.reqMarketDataType(market_data_type)
                    data_type_name = "Delayed" if market_data_type == 3 else "Real-time"
                    self.logger.info(f"✅ Requested Market Data Type {market_data_type} ({data_type_name})")
                except Exception as mdt_error:
                    self.logger.error(f"Failed to set market data type to real-time: {mdt_error}")
                    # Fall back to delayed if real-time not available
                    try:
                        self.ib.reqMarketDataType(3)
                        self.logger.warning("⚠️ Using delayed market data (Type 3) - real-time not available")
                    except Exception as fallback_error:
                        self.logger.error(f"Failed to set any market data type: {fallback_error}")

                self.logger.info(f"✅ Successfully connected to IB (clientId={self.client_id})")

                # Start heartbeat monitoring
                if not self._heartbeat_task or self._heartbeat_task.done():
                    self.running = True
                    self._heartbeat_task = asyncio.create_task(self._heartbeat_monitor())
                    self.logger.info("Started heartbeat monitoring")

                return True

            except Exception as e:
                attempt += 1
                self.connected = False

                if attempt >= max_attempts:
                    self.logger.critical(
                        f"❌ IB connection failed after {max_attempts} attempts: {e}"
                    )
                    await self._enter_safe_mode()
                    return False

                # Exponential backoff: 2^attempt seconds, max 60s
                delay = min(2 ** attempt, 60)
                self.logger.warning(
                    f"IB connection failed (attempt {attempt}/{max_attempts}): {e}. "
                    f"Retrying in {delay}s..."
                )
                await asyncio.sleep(delay)

        return False

    async def subscribe(self, symbols: List[str]):
        if not self.connected:
            return

        for symbol in symbols:
            try:
                contract = None
                if symbol == "NQ":
                    nq = Future(symbol='NQ', exchange='CME', currency='USD')
                    details = await self.ib.reqContractDetailsAsync(nq)
                    if not details: continue
                    details = sorted(details, key=lambda d: d.contract.lastTradeDateOrContractMonth)
                    contract = details[0].contract
                    await self.ib.qualifyContractsAsync(contract)
                    self.logger.info(f"Resolved NQ to {contract.localSymbol}")
                else:
                    contract = Stock(symbol, 'SMART', 'USD')
                    await self.ib.qualifyContractsAsync(contract)

                if contract:
                    self.ib.reqMktData(contract, '', False, False)
                    self.subscriptions.append(contract)
                    self.logger.info(f"✅ Subscribed to: {symbol}")

            except Exception as e:
                self.logger.error(f"Subscription failed for {symbol}: {e}")

        self.ib.pendingTickersEvent += self._on_ib_tick

    def _on_ib_tick(self, tickers: List[Ticker]) -> None:
        """Process incoming ticks from IB."""
        for ticker in tickers:
            try:
                # Hämta pris
                price = ticker.last if ticker.last and ticker.last > 0 else ticker.close
                
                if (price is None or price != price) and hasattr(ticker, 'delayedLast'):
                     price = ticker.delayedLast
                
                if (price is None or price != price): 
                     if ticker.bid and ticker.ask:
                         price = (ticker.bid + ticker.ask) / 2
                
                # FIX: Hantera volym som kan vara NaN
                vol = 0
                if ticker.volume and not math.isnan(ticker.volume):
                    vol = int(ticker.volume)
                
                if price and price == price: 
                    t = Tick(
                        symbol="NQ", 
                        price=float(price),
                        timestamp=ticker.time if ticker.time else datetime.now(),
                        volume=vol
                    )
                    if self.on_tick:
                        # Create task and track it
                        task = asyncio.create_task(self.on_tick(t))
                        self._pending_tasks.add(task)
                        task.add_done_callback(self._pending_tasks.discard)

                        # Log exceptions
                        def _handle_task_exception(t):
                            try:
                                t.result()
                            except Exception as e:
                                self.logger.error(f"Tick handler failed: {e}", exc_info=True)

                        task.add_done_callback(_handle_task_exception)
            except Exception as e:
                # Logga felet men krascha inte hela loopen
                self.logger.error(f"Error processing tick: {e}")

    async def disconnect(self):
        """Disconnect from IB and stop monitoring."""
        self.running = False

        # Wait for pending tick handler tasks
        if self._pending_tasks:
            self.logger.info(f"Waiting for {len(self._pending_tasks)} pending tick handlers...")
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
            self.logger.info("All pending tick handlers completed")

        # Stop heartbeat monitoring
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self.logger.info("Stopped heartbeat monitoring")

        # Disconnect from IB
        if self.ib:
            self.ib.disconnect()
            self.connected = False
            self.logger.info("Disconnected from IB")

    async def _heartbeat_monitor(self):
        """
        Monitor connection health with periodic heartbeat.

        Checks every heartbeat_interval seconds if connection is alive.
        Auto-reconnects on connection loss.
        """
        self.logger.info(f"Heartbeat monitoring started (interval: {self.heartbeat_interval}s)")

        while self.running:
            await asyncio.sleep(self.heartbeat_interval)

            if not self.running:
                break

            # Check if connection is alive
            if self.ib and not self.ib.isConnected():
                self.connected = False
                self.reconnect_count += 1

                self.logger.error(
                    f"❌ IB connection lost (reconnect #{self.reconnect_count}), attempting reconnection..."
                )

                # Try to reconnect
                success = await self.connect_with_retry(max_attempts=5)

                if success:
                    self.logger.info("✅ IB reconnected successfully")

                    # Re-subscribe to symbols
                    if self.subscriptions:
                        self.logger.info("Re-subscribing to market data...")
                        symbols = [s.symbol if hasattr(s, 'symbol') else 'NQ' for s in self.subscriptions]
                        self.subscriptions = []  # Clear old subscriptions
                        await self.subscribe(symbols)
                else:
                    self.logger.critical("Failed to reconnect to IB - entering safe mode")
                    await self._enter_safe_mode()
                    break
            elif self.ib and self.ib.isConnected():
                # Connection healthy
                self.logger.debug("Heartbeat: IB connection healthy")

        self.logger.info("Heartbeat monitoring stopped")

    async def _enter_safe_mode(self):
        """
        Enter safe mode on persistent connection failures.

        Safe mode:
        - Stops new data processing
        - Logs critical alert
        - Requires manual intervention
        """
        self.safe_mode = True
        self.connected = False
        self.running = False

        self.logger.critical(
            "🚨 ENTERING SAFE MODE 🚨\n"
            f"Reason: IB connection failed after {self.reconnect_count} reconnection attempts\n"
            "Action Required: Manual intervention needed\n"
            "- Check IB Gateway/TWS is running\n"
            "- Verify network connectivity\n"
            "- Check credentials and account status\n"
            "- Review IB logs for errors\n"
            "System will NOT auto-restart until safe mode is cleared"
        )

        # TODO: Send alert via Telegram/Email
        # TODO: Update dashboard status to SAFE_MODE

    def is_healthy(self) -> bool:
        """
        Check if connection is healthy.

        Returns:
            True if connected and not in safe mode
        """
        return self.connected and not self.safe_mode and self.ib and self.ib.isConnected()

    def clear_safe_mode(self) -> None:
        """
        Clear safe mode (manual recovery).

        Should only be called after resolving underlying connection issues.
        """
        self.logger.info("Clearing safe mode - manual recovery")
        self.safe_mode = False
        self.reconnect_count = 0
