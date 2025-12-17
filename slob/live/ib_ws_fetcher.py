"""
Interactive Brokers WebSocket-like Fetcher

Real-time market data fetcher for NQ futures using IB TWS API via ib_insync.
Drop-in replacement for AlpacaWSFetcher with same interface.

Architecture:
- Uses ib_insync async wrapper for IB TWS API
- Connects to IB Gateway or TWS (paper trading: port 7497/4002)
- Subscribes to NQ futures real-time ticks
- Converts IB ticks to standard Tick dataclass
- Handles reconnection and error recovery

Usage:
    fetcher = IBWSFetcher(
        host='127.0.0.1',
        port=7497,
        client_id=1,
        account='DU123456'
    )

    fetcher.on_tick = async_tick_handler
    await fetcher.connect()
    await fetcher.subscribe(['NQ'])
    await fetcher.listen()
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional

# ib_insync import (will be installed)
try:
    from ib_insync import IB, Future, util
except ImportError:
    raise ImportError(
        "ib_insync not installed. Install with: pip install ib_insync"
    )

from slob.data.tick import Tick

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """Connection states."""
    DISCONNECTED = 1
    CONNECTING = 2
    CONNECTED = 3
    FAILED = 4


@dataclass
class IBConfig:
    """Interactive Brokers configuration."""
    host: str = '127.0.0.1'
    port: int = 7497  # TWS paper trading (4002 for IB Gateway paper)
    client_id: int = 1
    account: Optional[str] = None
    paper_trading: bool = True
    timeout: int = 10
    max_reconnect_attempts: int = 10
    reconnect_delay_seconds: int = 5


class IBWSFetcher:
    """
    Interactive Brokers WebSocket-like fetcher.

    Provides same interface as AlpacaWSFetcher for drop-in compatibility.

    Attributes:
        config: IB configuration
        state: Connection state
        ib: IB connection instance
        subscribed_contracts: Active market data subscriptions
        on_tick: Callback for tick events
        on_error: Callback for errors
    """

    def __init__(
        self,
        host: str = '127.0.0.1',
        port: int = 7497,
        client_id: int = 1,
        account: Optional[str] = None,
        paper_trading: bool = True
    ):
        """
        Initialize IB fetcher.

        Args:
            host: IB Gateway/TWS host (default: localhost)
            port: Port - 7497 (TWS paper), 7496 (TWS live),
                  4002 (Gateway paper), 4001 (Gateway live)
            client_id: Unique client ID (1-999)
            account: Paper trading account (e.g., 'DU123456')
            paper_trading: Enable paper trading mode
        """
        self.config = IBConfig(
            host=host,
            port=port,
            client_id=client_id,
            account=account,
            paper_trading=paper_trading
        )

        self.state = ConnectionState.DISCONNECTED
        self.ib: Optional[IB] = None

        # Subscriptions
        self.subscribed_contracts: Dict[str, Future] = {}
        self.contract_to_symbol: Dict[int, str] = {}  # conId -> symbol

        # Statistics
        self.tick_count = 0
        self.message_count = 0
        self.reconnect_attempts = 0
        self.last_message_time: Optional[datetime] = None

        # Callbacks
        self.on_tick: Optional[Callable] = None
        self.on_error: Optional[Callable] = None

        # Reconnection
        self.max_reconnect_attempts = 10
        self.is_running = False

    async def connect(self):
        """
        Connect to IB TWS/Gateway.

        Raises:
            ConnectionError: If connection fails
        """
        try:
            self.state = ConnectionState.CONNECTING
            logger.info(f"Connecting to IB at {self.config.host}:{self.config.port}")

            # Create IB instance
            self.ib = IB()

            # Connect
            await self.ib.connectAsync(
                host=self.config.host,
                port=self.config.port,
                clientId=self.config.client_id,
                timeout=self.config.timeout
            )

            self.state = ConnectionState.CONNECTED
            self.reconnect_attempts = 0
            self.last_message_time = datetime.now()

            logger.info(f"✅ Successfully connected to IB (clientId={self.config.client_id})")

            # Register error handler
            self.ib.errorEvent += self._on_error

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self.state = ConnectionState.FAILED
            raise ConnectionError(f"Failed to connect to IB: {e}")

    async def subscribe(self, symbols: List[str]):
        """
        Subscribe to symbols.

        Args:
            symbols: List of futures symbols (e.g., ['NQ', 'ES'])

        Raises:
            RuntimeError: If not connected
        """
        if self.state != ConnectionState.CONNECTED:
            raise RuntimeError("Not connected to IB")

        for symbol in symbols:
            try:
                # Resolve contract
                contract = await self._resolve_futures_contract(symbol)

                if contract is None:
                    logger.error(f"❌ Failed to resolve contract for {symbol}")
                    continue

                # Subscribe to market data
                ticker = self.ib.reqMktData(
                    contract=contract,
                    genericTickList='',  # Trade ticks only
                    snapshot=False,
                    regulatorySnapshot=False
                )

                # Register tick handler
                ticker.updateEvent += self._on_ticker_update

                # Store subscription
                self.subscribed_contracts[symbol] = contract
                self.contract_to_symbol[contract.conId] = symbol

                logger.info(f"✅ Subscribed to: {symbol} (conId={contract.conId})")

            except Exception as e:
                logger.error(f"Failed to subscribe to {symbol}: {e}")
                if self.on_error:
                    await self.on_error(e)

    async def listen(self):
        """
        Start listening for messages.

        Runs until stopped or disconnected.
        """
        logger.info("Started listening for messages")
        self.is_running = True

        try:
            # Keep connection alive with heartbeat
            while self.is_running and self.ib.isConnected():
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Listen loop error: {e}")
            if self.on_error:
                await self.on_error(e)

    def _on_ticker_update(self, ticker):
        """
        Handle ticker update event from ib_insync.

        Args:
            ticker: Updated ticker object
        """
        try:
            # Check if valid trade tick
            if ticker.time and ticker.last and ticker.last > 0:
                # Get symbol from contract ID
                symbol = self.contract_to_symbol.get(ticker.contract.conId, 'UNKNOWN')

                # Create Tick
                tick = Tick(
                    symbol=symbol,
                    price=float(ticker.last),
                    size=int(ticker.lastSize) if ticker.lastSize else 1,
                    timestamp=ticker.time,
                    exchange=ticker.contract.exchange
                )

                self.tick_count += 1
                self.message_count += 1
                self.last_message_time = datetime.now()

                # Call tick handler
                if self.on_tick:
                    asyncio.create_task(self._safe_call_handler(tick))

        except Exception as e:
            logger.error(f"Error handling ticker update: {e}")

    async def _safe_call_handler(self, tick: Tick):
        """
        Safely call tick handler with error handling.

        Args:
            tick: Tick data
        """
        try:
            if asyncio.iscoroutinefunction(self.on_tick):
                await self.on_tick(tick)
            else:
                self.on_tick(tick)
        except Exception as e:
            logger.error(f"Error in tick handler: {e}")
            if self.on_error:
                await self.on_error(e)

    def _on_error(self, reqId: int, errorCode: int, errorString: str, contract):
        """
        Handle IB error event.

        Args:
            reqId: Request ID
            errorCode: Error code
            errorString: Error message
            contract: Related contract
        """
        # Filter out informational messages (code < 1000)
        if errorCode < 1000:
            logger.debug(f"IB info [{errorCode}]: {errorString}")
            return

        # Warning codes (1000-1999)
        if 1000 <= errorCode < 2000:
            logger.warning(f"IB warning [{errorCode}]: {errorString}")
            return

        # Error codes (2000+)
        logger.error(f"IB error [{errorCode}]: {errorString} (reqId={reqId})")

        # Handle specific errors
        if errorCode == 1100:  # Connectivity lost
            logger.error("❌ Connectivity lost to IB")
            asyncio.create_task(self.reconnect())

    async def _resolve_futures_contract(self, symbol: str) -> Optional[Future]:
        """
        Resolve futures contract for symbol.

        For NQ, resolves to front month contract (most liquid).

        Args:
            symbol: Futures symbol (e.g., 'NQ', 'ES')

        Returns:
            Resolved contract or None if not found
        """
        try:
            # Create generic futures contract
            contract = Future(
                symbol=symbol,
                exchange='CME',  # Chicago Mercantile Exchange
                currency='USD'
            )

            # Query contract details
            details = await self.ib.reqContractDetailsAsync(contract)

            if not details:
                logger.error(f"No contracts found for {symbol}")
                return None

            # Get front month (first in list, most liquid)
            front_month = details[0].contract

            logger.info(
                f"Resolved {symbol} to {front_month.localSymbol} "
                f"(expiry: {front_month.lastTradeDateOrContractMonth})"
            )

            return front_month

        except Exception as e:
            logger.error(f"Failed to resolve contract for {symbol}: {e}")
            return None

    async def disconnect(self):
        """Disconnect from IB."""
        self.is_running = False

        if self.ib and self.ib.isConnected():
            logger.info("Disconnecting from IB...")

            # Cancel all subscriptions
            for symbol, contract in self.subscribed_contracts.items():
                try:
                    self.ib.cancelMktData(contract)
                    logger.debug(f"Cancelled subscription: {symbol}")
                except Exception as e:
                    logger.warning(f"Error cancelling {symbol}: {e}")

            # Disconnect
            self.ib.disconnect()
            logger.info("✅ Disconnected from IB")

        self.state = ConnectionState.DISCONNECTED
        self.subscribed_contracts.clear()
        self.contract_to_symbol.clear()

    async def reconnect(self):
        """Reconnect with exponential backoff."""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.critical(
                f"❌ Max reconnection attempts ({self.max_reconnect_attempts}) reached"
            )
            self.state = ConnectionState.FAILED
            return

        self.reconnect_attempts += 1
        delay = min(2 ** self.reconnect_attempts, 60)  # Exponential backoff, max 60s

        logger.info(
            f"Reconnecting in {delay}s (attempt {self.reconnect_attempts}/"
            f"{self.max_reconnect_attempts})"
        )

        await asyncio.sleep(delay)

        try:
            await self.disconnect()
            await self.connect()

            # Re-subscribe to symbols
            if self.subscribed_contracts:
                symbols = list(self.subscribed_contracts.keys())
                self.subscribed_contracts.clear()
                self.contract_to_symbol.clear()
                await self.subscribe(symbols)

            logger.info("✅ Reconnection successful")

        except Exception as e:
            logger.error(f"Reconnection failed: {e}")
            await self.reconnect()

    def is_connected(self) -> bool:
        """
        Check if connected to IB.

        Returns:
            True if connected
        """
        return self.ib is not None and self.ib.isConnected()

    def get_stats(self) -> dict:
        """
        Get connection statistics.

        Returns:
            Statistics dict
        """
        return {
            'state': self.state.name,
            'reconnect_attempts': self.reconnect_attempts,
            'message_count': self.message_count,
            'tick_count': self.tick_count,
            'subscribed_symbols': list(self.subscribed_contracts.keys()),
            'last_message_time': (
                self.last_message_time.isoformat()
                if self.last_message_time else None
            )
        }


# For backward compatibility with AlpacaWSFetcher interface
__all__ = ['IBWSFetcher', 'IBConfig', 'ConnectionState']
