"""
Alpaca WebSocket Data Fetcher

Real-time market data streaming from Alpaca Markets.
Handles authentication, subscription, reconnection, and tick parsing.
"""

import asyncio
import websockets
import json
import logging
from typing import Callable, List, Optional, Set
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """WebSocket connection states."""
    DISCONNECTED = 0
    CONNECTING = 1
    AUTHENTICATING = 2
    CONNECTED = 3
    RECONNECTING = 4
    FAILED = 5


@dataclass
class Tick:
    """Market tick data."""
    symbol: str
    price: float
    size: int
    timestamp: datetime
    exchange: str

    def to_dict(self):
        """Convert to dictionary."""
        return {
            'symbol': self.symbol,
            'price': self.price,
            'size': self.size,
            'timestamp': self.timestamp,
            'exchange': self.exchange
        }


class AlpacaWSFetcher:
    """
    Alpaca WebSocket data fetcher for real-time market data.

    Features:
    - Async WebSocket connection
    - Automatic reconnection with exponential backoff
    - Multiple subscription support
    - Message validation
    - Health monitoring

    Usage:
        fetcher = AlpacaWSFetcher(
            api_key="YOUR_KEY",
            api_secret="YOUR_SECRET",
            paper_trading=True,
            on_tick=handle_tick
        )

        await fetcher.connect()
        await fetcher.subscribe(["NQ"])
        await fetcher.listen()
    """

    # WebSocket URLs
    WS_URL_PAPER = "wss://stream.data.alpaca.markets/v2/iex"
    WS_URL_LIVE = "wss://stream.data.alpaca.markets/v2/sip"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        paper_trading: bool = True,
        on_tick: Optional[Callable[[Tick], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None
    ):
        """
        Initialize WebSocket fetcher.

        Args:
            api_key: Alpaca API key
            api_secret: Alpaca API secret
            paper_trading: Use paper trading endpoint (default: True)
            on_tick: Callback for tick data
            on_error: Callback for errors
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper_trading = paper_trading
        self.on_tick = on_tick
        self.on_error = on_error

        # Connection state
        self.ws = None
        self.state = ConnectionState.DISCONNECTED
        self.subscribed_symbols: Set[str] = set()

        # Reconnection state
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 1  # seconds
        self.backoff_factor = 2

        # Health monitoring
        self.last_message_time = None
        self.message_count = 0
        self.tick_count = 0

        # Control flags
        self.should_stop = False

    async def connect(self):
        """Establish WebSocket connection and authenticate."""
        if self.state in [ConnectionState.CONNECTED, ConnectionState.CONNECTING]:
            logger.warning("Already connected or connecting")
            return

        self.state = ConnectionState.CONNECTING
        url = self.WS_URL_PAPER if self.paper_trading else self.WS_URL_LIVE

        try:
            logger.info(f"Connecting to Alpaca WebSocket ({'paper' if self.paper_trading else 'live'})")

            # 1. Connect to WebSocket
            self.ws = await websockets.connect(url)

            # 2. Wait for initial "connected" welcome message
            # Alpaca sends [{"T": "success", "msg": "connected"}] immediately upon connection.
            # We must consume this message before sending auth.
            welcome_raw = await asyncio.wait_for(self.ws.recv(), timeout=10.0)
            logger.debug(f"Received welcome message: {welcome_raw}")

            # 3. Authenticate
            self.state = ConnectionState.AUTHENTICATING
            auth_msg = {
                "action": "auth",
                "key": self.api_key,
                "secret": self.api_secret
            }

            await self.ws.send(json.dumps(auth_msg))
            logger.debug("Authentication message sent")

            # 4. Wait for auth confirmation
            response = await asyncio.wait_for(self.ws.recv(), timeout=10.0)
            auth_data = json.loads(response)

            # Check if authentication succeeded
            if isinstance(auth_data, list) and len(auth_data) > 0:
                msg = auth_data[0]

                if msg.get('T') == 'success' and msg.get('msg') == 'authenticated':
                    self.state = ConnectionState.CONNECTED
                    self.reconnect_attempts = 0
                    self.last_message_time = datetime.now()
                    logger.info("✅ Successfully connected and authenticated to Alpaca WebSocket")
                else:
                    raise ConnectionError(f"Authentication failed: {msg}")
            else:
                raise ConnectionError(f"Unexpected auth response: {auth_data}")

        except asyncio.TimeoutError:
            logger.error("Authentication timeout")
            self.state = ConnectionState.FAILED
            await self._handle_connection_failure()

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self.state = ConnectionState.FAILED
            await self._handle_connection_failure()

    async def subscribe(self, symbols: List[str]):
        """
        Subscribe to trades for given symbols.

        Args:
            symbols: List of symbols to subscribe to (e.g., ["NQ", "AAPL"])
        """
        if self.state != ConnectionState.CONNECTED:
            logger.error("Cannot subscribe - not connected")
            return

        if not symbols:
            logger.warning("No symbols provided for subscription")
            return

        try:
            # Alpaca format: {"action": "subscribe", "trades": ["AAPL", "TSLA"]}
            sub_msg = {
                "action": "subscribe",
                "trades": symbols
            }

            await self.ws.send(json.dumps(sub_msg))
            self.subscribed_symbols.update(symbols)

            logger.info(f"✅ Subscribed to: {', '.join(symbols)}")

        except Exception as e:
            logger.error(f"Subscription failed: {e}")
            if self.on_error:
                await self.on_error(e)

    async def listen(self):
        """
        Main message processing loop.

        Runs continuously until stopped, processing incoming messages.
        """
        if self.state != ConnectionState.CONNECTED:
            logger.error("Cannot listen - not connected")
            return

        logger.info("Started listening for messages")

        try:
            async for message in self.ws:
                if self.should_stop:
                    logger.info("Stop requested, exiting listen loop")
                    break

                self.message_count += 1
                self.last_message_time = datetime.now()

                await self._process_message(message)

        except websockets.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            self.state = ConnectionState.DISCONNECTED

            if not self.should_stop:
                await self.reconnect()

        except Exception as e:
            logger.error(f"Error in listen loop: {e}")
            self.state = ConnectionState.FAILED

            if self.on_error:
                await self.on_error(e)

            if not self.should_stop:
                await self.reconnect()

    async def _process_message(self, message: str):
        """
        Process incoming WebSocket message.

        Args:
            message: Raw JSON message from WebSocket
        """
        try:
            data = json.loads(message)

            # Alpaca sends array of messages
            if not isinstance(data, list):
                data = [data]

            for msg in data:
                msg_type = msg.get('T')

                if msg_type == 't':
                    # Trade message
                    await self._handle_trade(msg)

                elif msg_type == 'subscription':
                    logger.debug(f"Subscription confirmed: {msg}")

                elif msg_type == 'error':
                    logger.error(f"Error message from Alpaca: {msg}")

                elif msg_type == 'success':
                    logger.debug(f"Success message: {msg}")

                else:
                    logger.debug(f"Unknown message type '{msg_type}': {msg}")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON: {e}")

        except Exception as e:
            logger.error(f"Message processing error: {e}")
            if self.on_error:
                await self.on_error(e)

    async def _handle_trade(self, msg: dict):
        """
        Handle trade (tick) message.

        Args:
            msg: Trade message dict
        """
        try:
            tick = Tick(
                symbol=msg['S'],
                price=float(msg['p']),
                size=int(msg['s']),
                timestamp=self._parse_timestamp(msg['t']),
                exchange=msg.get('x', 'IEX')
            )

            self.tick_count += 1

            # Call tick handler
            if self.on_tick:
                # Run handler in background to not block message processing
                asyncio.create_task(self._safe_call_handler(tick))

        except KeyError as e:
            logger.error(f"Missing field in trade message: {e}, msg: {msg}")

        except Exception as e:
            logger.error(f"Error handling trade: {e}")

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

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """
        Parse Alpaca timestamp.

        Args:
            timestamp_str: ISO format timestamp (e.g., "2024-01-15T14:30:00.123Z")

        Returns:
            Datetime object
        """
        # Remove 'Z' and parse
        if timestamp_str.endswith('Z'):
            timestamp_str = timestamp_str[:-1] + '+00:00'

        # Alpaca sends nanosecond precision (9 decimals), but Python only supports
        # microsecond precision (6 decimals). Truncate to 6 decimal places.
        # Example: '2025-12-17T16:16:34.756327828+00:00' -> '2025-12-17T16:16:34.756327+00:00'
        import re
        timestamp_str = re.sub(r'(\.\d{6})\d+([+-]\d{2}:\d{2})$', r'\1\2', timestamp_str)

        return datetime.fromisoformat(timestamp_str)

    async def reconnect(self):
        """Reconnect with exponential backoff."""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.critical(f"❌ Max reconnection attempts ({self.max_reconnect_attempts}) reached")
            self.state = ConnectionState.FAILED

            # Enter safe mode
            await self._enter_safe_mode()
            return

        self.state = ConnectionState.RECONNECTING
        self.reconnect_attempts += 1

        # Calculate delay with exponential backoff
        delay = min(
            self.reconnect_delay * (self.backoff_factor ** (self.reconnect_attempts - 1)),
            60  # Max 60 seconds
        )

        logger.info(
            f"Reconnecting in {delay:.1f}s "
            f"(attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})"
        )

        await asyncio.sleep(delay)

        try:
            # Reconnect
            await self.connect()

            # Resubscribe to previous symbols
            if self.state == ConnectionState.CONNECTED and self.subscribed_symbols:
                logger.info("Resubscribing to symbols after reconnection")
                await self.subscribe(list(self.subscribed_symbols))

                # Resume listening
                asyncio.create_task(self.listen())

        except Exception as e:
            logger.error(f"Reconnection attempt failed: {e}")

            if not self.should_stop:
                await self.reconnect()

    async def _handle_connection_failure(self):
        """Handle connection failure."""
        if not self.should_stop:
            await self.reconnect()

    async def _enter_safe_mode(self):
        """
        Enter safe mode after max reconnection attempts.

        In safe mode:
        - Stop trading
        - Close all positions (would need position manager)
        - Alert operator
        """
        logger.critical("🚨 ENTERING SAFE MODE - Max reconnection attempts exceeded")

        # TODO: Close all positions via position manager
        # TODO: Send critical alert via Telegram

        self.should_stop = True

    async def disconnect(self):
        """Gracefully close connection."""
        logger.info("Disconnecting from Alpaca WebSocket")

        self.should_stop = True
        self.state = ConnectionState.DISCONNECTED

        if self.ws:
            await self.ws.close()

        logger.info("✅ Disconnected")

    def get_stats(self) -> dict:
        """
        Get connection statistics.

        Returns:
            Dict with stats
        """
        return {
            'state': self.state.name,
            'reconnect_attempts': self.reconnect_attempts,
            'message_count': self.message_count,
            'tick_count': self.tick_count,
            'subscribed_symbols': list(self.subscribed_symbols),
            'last_message_time': self.last_message_time.isoformat() if self.last_message_time else None
        }
