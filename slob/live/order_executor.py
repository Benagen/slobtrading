"""
Order Executor - Interactive Brokers Integration

Executes trades for SLOB setups using IB TWS API.

Key features:
- Bracket orders (entry + SL + TP)
- NQ futures contract management
- Retry logic with exponential backoff
- Order status tracking
- Position size calculation
- Risk management integration

Usage:
    executor = OrderExecutor(ib_config)
    await executor.initialize()

    # Place bracket order for setup
    order_result = await executor.place_bracket_order(setup)
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List

try:
    from ib_insync import IB, Future, Order, Trade, LimitOrder, StopOrder, MarketOrder
except ImportError:
    raise ImportError("ib_insync not installed. Install with: pip install ib_insync")

from slob.live.setup_state import SetupCandidate
from slob.backtest.risk_manager import RiskManager


logger = logging.getLogger(__name__)


# IB API Error Codes
# https://interactivebrokers.github.io/tws-api/message_codes.html
IB_ERROR_CODES = {
    # Critical errors (stop trading)
    321: "Insufficient buying power",
    502: "Session disconnected",
    1100: "Connectivity lost",
    2103: "Order ID exceeded max allowed",

    # Warning errors (log but continue)
    1102: "Connectivity restored",
    2104: "Market data farm connection OK",
    2106: "HMDS data farm connection OK",
    2108: "HMDS data farm connection broken",

    # Order-specific errors
    10147: "Order was cancelled",
    10148: "Order was filled",
    201: "Order rejected - invalid contract",
    202: "Order cancelled",
    399: "Order message error",
}

# Critical errors that should stop trading
IB_CRITICAL_ERRORS = {321, 502, 1100, 2103}


class OrderStatus(Enum):
    """Order status enumeration."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OrderType(Enum):
    """Order type enumeration."""
    ENTRY = "entry"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


@dataclass
class OrderResult:
    """Result of order execution."""
    order_id: int
    status: OrderStatus
    filled_price: Optional[float] = None
    filled_quantity: Optional[int] = None
    error_message: Optional[str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class BracketOrderResult:
    """Result of bracket order (entry + SL + TP)."""
    entry_order: OrderResult
    stop_loss_order: Optional[OrderResult] = None
    take_profit_order: Optional[OrderResult] = None
    success: bool = False
    error_message: Optional[str] = None


class OrderExecutorConfig:
    """Configuration for OrderExecutor."""

    def __init__(
        self,
        host: str = '127.0.0.1',
        port: int = 4002,  # IB Gateway default port (match fetcher)
        client_id: int = 2,  # Different from data fetcher
        account: Optional[str] = None,
        paper_trading: bool = True,
        max_retry_attempts: int = 3,
        retry_delay_seconds: float = 1.0,
        default_position_size: int = 1,  # NQ contracts
        max_position_size: int = 5,
        enable_bracket_orders: bool = True,
        # Timing parameters
        ib_response_delay: float = 0.5,  # Wait for IB to respond after order placement
        order_submission_delay: float = 0.2,  # Wait after submitting each order
        fill_check_interval: float = 0.5,  # Poll interval for checking order fill status
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.account = account
        self.paper_trading = paper_trading
        self.max_retry_attempts = max_retry_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.default_position_size = default_position_size
        self.max_position_size = max_position_size
        self.enable_bracket_orders = enable_bracket_orders
        self.ib_response_delay = ib_response_delay
        self.order_submission_delay = order_submission_delay
        self.fill_check_interval = fill_check_interval


class OrderExecutor:
    """
    Execute trading orders via Interactive Brokers.

    Handles:
    - Bracket orders (entry + SL + TP)
    - Order retry logic
    - Position tracking
    - Error handling

    Architecture:
    - Uses ib_insync for IB TWS API
    - Async interface matching LiveTradingEngine
    - Separate client_id from data fetcher (avoid conflicts)
    """

    def __init__(self, config: OrderExecutorConfig):
        self.config = config
        self.ib: Optional[IB] = None
        self.nq_contract: Optional[Future] = None

        # Order tracking
        self.active_orders: Dict[int, Trade] = {}
        self.order_history: List[OrderResult] = []
        self.pending_orders: Dict[int, Dict] = {}  # Track pending orders for error handling

        # Statistics
        self.orders_submitted = 0
        self.orders_filled = 0
        self.orders_rejected = 0

        # Error tracking
        self.trading_enabled = True  # Can be disabled by critical errors
        self.last_error: Optional[Dict] = None

        # Risk Management
        self.risk_manager = RiskManager(
            initial_capital=50000.0,  # Will be updated from IB
            max_risk_per_trade=0.01,  # 1% risk per trade (conservative)
            max_drawdown_stop=0.25,   # Stop trading at 25% DD
            reduce_size_at_dd=0.15,   # Reduce size at 15% DD
            use_kelly=False,          # Enable after 50+ trades
            kelly_fraction=0.5        # Half-Kelly when enabled
        )
        self._cached_balance = 50000.0  # Fallback if IB sync fails

        # Validate trading mode early (prevents accidental live trading)
        self.validate_paper_trading_mode()

    async def initialize(self):
        """
        Initialize IB connection and resolve NQ contract with retry logic.

        Steps:
        1. Connect to IB TWS/Gateway (with retry)
        2. Resolve NQ front month contract
        3. Verify account and permissions
        """
        logger.info("Initializing OrderExecutor...")

        # Connect to IB with retry logic
        success = await self.connect_with_retry()

        if not success:
            raise ConnectionError("Failed to connect to IB after multiple attempts")

        # Resolve NQ contract
        self.nq_contract = await self._resolve_nq_contract()
        logger.info(f"✅ NQ contract resolved: {self.nq_contract.localSymbol}")

        # Get account info
        if self.config.account:
            account_values = self.ib.accountValues(account=self.config.account)
            logger.info(f"Account: {self.config.account} ({len(account_values)} values)")

        # Register IB error handler
        self.ib.errorEvent += self._handle_ib_error
        logger.info("IB error handler registered")

        logger.info("✅ OrderExecutor initialized")

    async def _handle_ib_error(self, reqId: int, errorCode: int, errorString: str, contract=None):
        """
        Handle IB API error codes.

        Registered with IB errorEvent to catch all errors from the IB API.
        Critical errors disable trading, connectivity errors trigger reconnect.

        Args:
            reqId: Request ID that caused the error (-1 if system-wide)
            errorCode: IB error code (see IB_ERROR_CODES)
            errorString: Human-readable error description
            contract: Contract associated with error (optional)
        """
        error_desc = IB_ERROR_CODES.get(errorCode, f"Unknown error {errorCode}")

        # Log the error with appropriate severity
        if errorCode in IB_CRITICAL_ERRORS:
            logger.critical(
                f"🔴 IB CRITICAL ERROR {errorCode} (reqId: {reqId}): {error_desc}\n"
                f"   Details: {errorString}"
            )
        else:
            logger.warning(
                f"⚠️ IB Error {errorCode} (reqId: {reqId}): {error_desc} - {errorString}"
            )

        # Store last error
        self.last_error = {
            'code': errorCode,
            'message': errorString,
            'description': error_desc,
            'reqId': reqId,
            'timestamp': datetime.now()
        }

        # Handle critical errors
        if errorCode in IB_CRITICAL_ERRORS:
            if errorCode == 321:  # Insufficient buying power
                logger.critical("❌ INSUFFICIENT BUYING POWER - Disabling all new trades")
                self.trading_enabled = False
                # TODO: Send alert via Telegram/Email
                # await self._send_alert(f"Trading disabled: {error_desc}")

            elif errorCode in (502, 1100):  # Connectivity lost
                logger.critical("❌ IB CONNECTION LOST - Attempting reconnect")
                # Trigger immediate reconnection
                asyncio.create_task(self.reconnect())

            elif errorCode == 2103:  # Order ID exceeded
                logger.critical("❌ ORDER ID EXCEEDED - Reconnection required to reset counter")
                # IB requires reconnection to reset order IDs
                asyncio.create_task(self.reconnect())

        # Track error for specific order
        if reqId > 0 and reqId in self.pending_orders:
            self.pending_orders[reqId]['error'] = {
                'code': errorCode,
                'message': errorString,
                'description': error_desc
            }
            logger.debug(f"Error stored for order {reqId}")

    def validate_paper_trading_mode(self) -> None:
        """
        Validate paper trading mode with multiple checks.

        Validates consistency between:
        - Config paper_trading flag
        - Account format (DU* = paper, U* = live)
        - Port (4002 = paper, 4001 = live)

        Raises:
            ValueError: If validation fails or live trading attempted without confirmation
        """
        import os

        # Check 1: Config flag
        if not self.config.paper_trading:
            logger.warning("⚠️  PAPER_TRADING=False - LIVE TRADING MODE")

        # Check 2: Account format (paper accounts start with DU)
        account = self.config.account
        is_paper_account = account and account.startswith('DU') if account else False

        # Check 3: Port (4002 = paper direct, 4004 = paper SOCAT, 4001 = live)
        port = self.config.port
        is_paper_port = (port in [4002, 4004])

        # Validate consistency
        if self.config.paper_trading:
            # Config says PAPER - verify account and port match
            if account and not is_paper_account:
                raise ValueError(
                    f"❌ Config says PAPER but account {account} is LIVE (should start with DU)\n"
                    f"   Fix: Use a DU-prefixed paper trading account"
                )

            if not is_paper_port:
                raise ValueError(
                    f"❌ Config says PAPER but port {port} is LIVE (should be 4002 or 4004)\n"
                    f"   Fix: Set port=4002 (direct) or 4004 (SOCAT relay) for paper trading"
                )

            logger.info(
                f"✓ Paper trading mode validated: "
                f"account={account or 'default'}, port={port}"
            )

        else:
            # Config says LIVE - require explicit confirmation
            logger.critical(
                f"\n"
                f"{'='*70}\n"
                f"⚠️⚠️⚠️  LIVE TRADING MODE DETECTED  ⚠️⚠️⚠️\n"
                f"{'='*70}\n"
                f"Account: {account or 'NOT SET'}\n"
                f"Port: {port}\n"
                f"\n"
                f"Set REQUIRE_LIVE_CONFIRMATION=true in .env to proceed with live trading\n"
                f"{'='*70}"
            )

            require_confirmation = os.getenv('REQUIRE_LIVE_CONFIRMATION', 'false').lower()
            if require_confirmation != 'true':
                raise ValueError(
                    "❌ LIVE TRADING requires REQUIRE_LIVE_CONFIRMATION=true in .env\n"
                    "   This is a safety check to prevent accidental live trading.\n"
                    "   If you understand the risks, add to .env:\n"
                    "   REQUIRE_LIVE_CONFIRMATION=true"
                )

            logger.info(
                f"✓ Live trading mode validated: "
                f"account={account}, port={port}, confirmation=required"
            )

    async def connect_with_retry(self, max_attempts: int = 10) -> bool:
        """
        Connect to IB with exponential backoff retry.

        Args:
            max_attempts: Maximum number of connection attempts

        Returns:
            True if connected successfully, False otherwise
        """
        self.ib = IB()
        attempt = 0

        while attempt < max_attempts:
            try:
                logger.info(
                    f"Connecting OrderExecutor to IB at {self.config.host}:{self.config.port} "
                    f"(attempt {attempt + 1}/{max_attempts})"
                )

                # Increase timeout to 20 seconds (default is 4s, too short for IB Gateway)
                await self.ib.connectAsync(
                    host=self.config.host,
                    port=self.config.port,
                    clientId=self.config.client_id,
                    readonly=False,  # Need write access for orders
                    timeout=20
                )

                logger.info(f"✅ OrderExecutor connected to IB: {self.config.host}:{self.config.port}")
                return True

            except Exception as e:
                attempt += 1

                if attempt >= max_attempts:
                    logger.critical(
                        f"❌ OrderExecutor failed to connect after {max_attempts} attempts: {e}"
                    )
                    return False

                # Exponential backoff: 2^attempt seconds, max 60s
                delay = min(2 ** attempt, 60)
                logger.warning(
                    f"OrderExecutor connection failed (attempt {attempt}/{max_attempts}): {e}. "
                    f"Retrying in {delay}s..."
                )
                await asyncio.sleep(delay)

        return False

    async def reconnect(self) -> bool:
        """
        Reconnect to IB after connection loss.

        Attempts to restore connection and re-resolve NQ contract.

        Returns:
            True if reconnected successfully
        """
        logger.info("Attempting to reconnect OrderExecutor...")

        # Disconnect cleanly first
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()

        # Reconnect
        success = await self.connect_with_retry(max_attempts=5)

        if success:
            # Re-resolve NQ contract
            try:
                self.nq_contract = await self._resolve_nq_contract()
                logger.info(f"✅ OrderExecutor reconnected and NQ contract re-resolved")
                return True
            except Exception as e:
                logger.error(f"Failed to re-resolve NQ contract: {e}")
                return False

        return False

    def is_connected(self) -> bool:
        """Check if IB connection is active."""
        return self.ib is not None and self.ib.isConnected()

    async def _resolve_nq_contract(self) -> Future:
        """
        Resolve NQ futures contract (front month).

        Returns most liquid contract (closest expiry).

        Returns:
            Future contract for NQ
        """
        # Create generic NQ futures contract
        nq = Future(symbol='NQ', exchange='CME', currency='USD')

        # Request contract details
        details = await self.ib.reqContractDetailsAsync(nq)

        if not details:
            raise ValueError("No NQ contracts found")

        # Sort by expiry (closest first = front month = most liquid)
        details = sorted(
            details,
            key=lambda d: d.contract.lastTradeDateOrContractMonth
        )

        front_month = details[0].contract

        logger.info(
            f"Resolved NQ front month: {front_month.localSymbol} "
            f"(expiry: {front_month.lastTradeDateOrContractMonth})"
        )

        # Qualify contract to get full details
        qualified = await self.ib.qualifyContractsAsync(front_month)

        return qualified[0] if qualified else front_month

    # ─────────────────────────────────────────────────────────────────
    # ORDER PLACEMENT
    # ─────────────────────────────────────────────────────────────────

    async def place_bracket_order(
        self,
        setup: SetupCandidate,
        position_size: Optional[int] = None
    ) -> BracketOrderResult:
        """
        Place bracket order for a setup (entry + SL + TP).

        For 5/1 SLOB setup:
        - Entry: Limit order at entry_price (close below no-wick low)
        - Stop Loss: Stop order at sl_price (above no-wick high)
        - Take Profit: Limit order at tp_price (risk-reward target)

        Args:
            setup: SetupCandidate with entry/SL/TP prices
            position_size: Number of NQ contracts (default: config default)

        Returns:
            BracketOrderResult with all order details
        """
        # CRITICAL: Paper trading mode check - prevent live orders
        if self.config.paper_trading:
            logger.critical(
                f"🛑 PAPER TRADING MODE: Orders NOT sent to IB\n"
                f"Setup: {setup.id}\n"
                f"Entry: ${setup.entry_price:.2f}\n"
                f"SL: ${setup.sl_price:.2f}\n"
                f"TP: ${setup.tp_price:.2f}\n"
                f"Quantity: {position_size or self.config.default_position_size}"
            )

            # Return simulated failure (orders not actually placed)
            return BracketOrderResult(
                entry_order=OrderResult(
                    order_id=0,
                    status=OrderStatus.REJECTED,
                    error_message="Paper trading mode - orders not sent to IB"
                ),
                success=False,
                error_message="Paper trading mode - orders not sent to IB"
            )

        # CRITICAL: Check if trading is enabled (could be disabled by error 321)
        if not self.trading_enabled:
            error_msg = "Trading disabled due to critical error"
            if self.last_error:
                error_msg = f"Trading disabled: {self.last_error['description']}"

            logger.critical(f"❌ {error_msg}")
            return BracketOrderResult(
                entry_order=OrderResult(
                    order_id=0,
                    status=OrderStatus.REJECTED,
                    error_message=error_msg
                ),
                success=False,
                error_message=error_msg
            )

        # Check connection health - reconnect if needed
        if not self.is_connected():
            logger.warning("IB connection lost, attempting reconnection...")
            reconnected = await self.reconnect()
            if not reconnected:
                return BracketOrderResult(
                    entry_order=OrderResult(
                        order_id=0,
                        status=OrderStatus.REJECTED,
                        error_message="IB connection lost and reconnection failed"
                    ),
                    success=False,
                    error_message="IB connection lost and reconnection failed"
                )

        if not setup.entry_price or not setup.sl_price or not setup.tp_price:
            return BracketOrderResult(
                entry_order=OrderResult(
                    order_id=0,
                    status=OrderStatus.REJECTED,
                    error_message="Setup missing entry/SL/TP prices"
                ),
                success=False,
                error_message="Setup missing entry/SL/TP prices"
            )

        # Check for duplicate order (idempotency protection)
        if self._check_duplicate_order(setup.id):
            logger.warning(f"Skipping duplicate order for setup {setup.id[:8]}")
            return BracketOrderResult(
                entry_order=OrderResult(
                    order_id=0,
                    status=OrderStatus.REJECTED,
                    error_message=f"Duplicate order detected - order already placed for setup {setup.id[:8]}"
                ),
                success=False,
                error_message=f"Duplicate order detected - order already placed for setup {setup.id[:8]}"
            )

        # Determine position size
        qty = position_size or self.config.default_position_size

        if qty > self.config.max_position_size:
            logger.warning(
                f"Position size {qty} exceeds max {self.config.max_position_size}. "
                f"Using max."
            )
            qty = self.config.max_position_size

        # Validate sufficient capital before placing order
        # Calculate required capital (assume 20% margin for NQ futures)
        required_capital = abs(qty) * setup.entry_price * 0.2

        if not await self.validate_sufficient_capital(required_capital):
            return BracketOrderResult(
                entry_order=OrderResult(
                    order_id=0,
                    status=OrderStatus.REJECTED,
                    error_message="Insufficient account balance"
                ),
                success=False,
                error_message="Insufficient account balance"
            )

        logger.info(
            f"Placing bracket order for setup {setup.id[:8]}:\n"
            f"  Entry: {setup.entry_price} (SHORT {qty} contracts)\n"
            f"  SL:    {setup.sl_price}\n"
            f"  TP:    {setup.tp_price}"
        )

        try:
            if self.config.enable_bracket_orders:
                # Use IB bracket order (atomic)
                result = await self._place_bracket_order_atomic(setup, qty)
            else:
                # Place orders individually
                result = await self._place_bracket_order_manual(setup, qty)

            if result.success:
                logger.info(f"✅ Bracket order placed: {setup.id[:8]}")
                self.orders_submitted += 1
            else:
                logger.error(f"❌ Bracket order failed: {result.error_message}")
                self.orders_rejected += 1

            return result

        except Exception as e:
            logger.error(f"Exception placing bracket order: {e}")
            return BracketOrderResult(
                entry_order=OrderResult(
                    order_id=0,
                    status=OrderStatus.REJECTED,
                    error_message=str(e)
                ),
                success=False,
                error_message=str(e)
            )

    async def _place_bracket_order_atomic(
        self,
        setup: SetupCandidate,
        qty: int
    ) -> BracketOrderResult:
        """
        Place bracket order using IB's atomic bracket order.

        IB supports bracket orders natively - all 3 orders are linked
        and automatically manage each other (SL/TP cancel when entry fills, etc.)
        """
        # Generate orderRef for idempotency protection
        # Format: SLOB_{setup_id[:8]}_{timestamp}_{order_type}
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        order_ref_base = f"SLOB_{setup.id[:8]}_{timestamp}"

        # Determine order actions based on direction
        from .setup_state import TradeDirection
        if setup.direction == TradeDirection.SHORT:
            entry_action = 'SELL'  # SHORT: Sell to enter
            exit_action = 'BUY'    # SHORT: Buy to close
        else:  # LONG
            entry_action = 'BUY'   # LONG: Buy to enter
            exit_action = 'SELL'   # LONG: Sell to close

        # Create parent order (entry)
        parent_order = LimitOrder(
            action=entry_action,
            totalQuantity=qty,
            lmtPrice=setup.entry_price,
            orderId=self.ib.client.getReqId(),
            transmit=False  # Don't transmit yet (wait for children)
        )
        parent_order.orderRef = f"{order_ref_base}_ENTRY"

        # Create OCA group for one-cancels-all behavior
        oca_group = f"OCA_{setup.id[:8]}"

        # Create stop loss
        stop_loss = StopOrder(
            action=exit_action,
            totalQuantity=qty,
            stopPrice=setup.sl_price,
            orderId=self.ib.client.getReqId(),
            parentId=parent_order.orderId,
            transmit=False,
            ocaGroup=oca_group,  # One-cancels-all group
            ocaType=1  # 1 = Cancel all remaining on fill
        )
        stop_loss.orderRef = f"{order_ref_base}_SL"

        # Create take profit
        take_profit = LimitOrder(
            action=exit_action,
            totalQuantity=qty,
            lmtPrice=setup.tp_price,
            orderId=self.ib.client.getReqId(),
            parentId=parent_order.orderId,
            transmit=True,  # Transmit all orders together
            ocaGroup=oca_group,  # One-cancels-all group
            ocaType=1  # 1 = Cancel all remaining on fill
        )
        take_profit.orderRef = f"{order_ref_base}_TP"

        logger.info(f"Generated orderRef: {order_ref_base}_[ENTRY|SL|TP]")

        # Place bracket (all 3 orders)
        try:
            # Track as pending for error handling
            self.pending_orders[parent_order.orderId] = {
                'setup_id': setup.id,
                'type': 'ENTRY',
                'timestamp': datetime.now()
            }

            # Place parent
            parent_trade = self.ib.placeOrder(self.nq_contract, parent_order)

            # Place children
            sl_trade = self.ib.placeOrder(self.nq_contract, stop_loss)
            tp_trade = self.ib.placeOrder(self.nq_contract, take_profit)

            # Wait for submission confirmation and check for errors
            await asyncio.sleep(self.config.ib_response_delay)  # Give IB time to respond

            # Check if error occurred during placement
            if parent_order.orderId in self.pending_orders and 'error' in self.pending_orders[parent_order.orderId]:
                error = self.pending_orders[parent_order.orderId]['error']
                logger.error(f"Parent order placement failed: {error['message']}")

                # Clean up pending order
                del self.pending_orders[parent_order.orderId]

                return BracketOrderResult(
                    entry_order=OrderResult(
                        order_id=0,
                        status=OrderStatus.REJECTED,
                        error_message=f"IB Error {error['code']}: {error['message']}"
                    ),
                    success=False,
                    error_message=f"IB Error {error['code']}: {error['message']}"
                )

            # Track orders
            self.active_orders[parent_order.orderId] = parent_trade
            self.active_orders[stop_loss.orderId] = sl_trade
            self.active_orders[take_profit.orderId] = tp_trade

            # Clean up from pending (order successfully placed)
            if parent_order.orderId in self.pending_orders:
                del self.pending_orders[parent_order.orderId]

            return BracketOrderResult(
                entry_order=OrderResult(
                    order_id=parent_order.orderId,
                    status=OrderStatus.SUBMITTED
                ),
                stop_loss_order=OrderResult(
                    order_id=stop_loss.orderId,
                    status=OrderStatus.SUBMITTED
                ),
                take_profit_order=OrderResult(
                    order_id=take_profit.orderId,
                    status=OrderStatus.SUBMITTED
                ),
                success=True
            )

        except Exception as e:
            logger.error(f"Failed to place bracket order: {e}")
            return BracketOrderResult(
                entry_order=OrderResult(
                    order_id=0,
                    status=OrderStatus.REJECTED,
                    error_message=str(e)
                ),
                success=False,
                error_message=str(e)
            )

    async def _place_bracket_order_manual(
        self,
        setup: SetupCandidate,
        qty: int
    ) -> BracketOrderResult:
        """
        Place orders individually (fallback if atomic bracket not supported).

        1. Place entry order
        2. Wait for fill
        3. Place SL and TP
        """
        # Entry order
        entry_result = await self._place_order(
            action='SELL',
            quantity=qty,
            order_type='LIMIT',
            limit_price=setup.entry_price
        )

        if entry_result.status != OrderStatus.SUBMITTED:
            return BracketOrderResult(
                entry_order=entry_result,
                success=False,
                error_message="Entry order failed"
            )

        # Wait for entry fill (with timeout)
        filled = await self._wait_for_fill(entry_result.order_id, timeout=300)

        if not filled:
            # Cancel entry if not filled
            await self.cancel_order(entry_result.order_id)
            return BracketOrderResult(
                entry_order=entry_result,
                success=False,
                error_message="Entry order timeout"
            )

        # Place SL
        sl_result = await self._place_order(
            action='BUY',
            quantity=qty,
            order_type='STOP',
            stop_price=setup.sl_price
        )

        # Place TP
        tp_result = await self._place_order(
            action='BUY',
            quantity=qty,
            order_type='LIMIT',
            limit_price=setup.tp_price
        )

        return BracketOrderResult(
            entry_order=entry_result,
            stop_loss_order=sl_result,
            take_profit_order=tp_result,
            success=True
        )

    async def _place_order(
        self,
        action: str,
        quantity: int,
        order_type: str,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        retry: bool = True
    ) -> OrderResult:
        """
        Place individual order with retry logic.

        Args:
            action: 'BUY' or 'SELL'
            quantity: Number of contracts
            order_type: 'MARKET', 'LIMIT', 'STOP'
            limit_price: For LIMIT orders
            stop_price: For STOP orders
            retry: Enable retry on failure

        Returns:
            OrderResult
        """
        attempt = 0
        last_error = None

        while attempt < self.config.max_retry_attempts:
            try:
                # Create order
                if order_type == 'MARKET':
                    order = MarketOrder(action=action, totalQuantity=quantity)
                elif order_type == 'LIMIT':
                    order = LimitOrder(action=action, totalQuantity=quantity, lmtPrice=limit_price)
                elif order_type == 'STOP':
                    order = StopOrder(action=action, totalQuantity=quantity, stopPrice=stop_price)
                else:
                    raise ValueError(f"Unknown order type: {order_type}")

                # Place order
                trade = self.ib.placeOrder(self.nq_contract, order)

                # Wait for submission
                await asyncio.sleep(self.config.order_submission_delay)

                # Track order
                self.active_orders[order.orderId] = trade

                logger.info(f"Order submitted: {order.orderId} ({action} {quantity} @ {order_type})")

                return OrderResult(
                    order_id=order.orderId,
                    status=OrderStatus.SUBMITTED
                )

            except Exception as e:
                last_error = str(e)
                attempt += 1

                if attempt < self.config.max_retry_attempts and retry:
                    delay = self.config.retry_delay_seconds * (2 ** (attempt - 1))  # Exponential backoff
                    logger.warning(f"Order placement failed (attempt {attempt}): {e}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Order placement failed after {attempt} attempts: {e}")
                    break

        return OrderResult(
            order_id=0,
            status=OrderStatus.REJECTED,
            error_message=last_error
        )

    async def _wait_for_fill(self, order_id: int, timeout: float = 300) -> bool:
        """
        Wait for order to fill (with timeout).

        Args:
            order_id: Order ID to monitor
            timeout: Timeout in seconds

        Returns:
            True if filled, False if timeout
        """
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            if order_id in self.active_orders:
                trade = self.active_orders[order_id]

                if trade.orderStatus.status == 'Filled':
                    logger.info(f"Order {order_id} filled at {trade.orderStatus.avgFillPrice}")
                    self.orders_filled += 1
                    return True

                elif trade.orderStatus.status in ['Cancelled', 'ApiCancelled', 'Rejected']:
                    logger.warning(f"Order {order_id} {trade.orderStatus.status}")
                    return False

            await asyncio.sleep(self.config.fill_check_interval)

        logger.warning(f"Order {order_id} fill timeout ({timeout}s)")
        return False

    # ─────────────────────────────────────────────────────────────────
    # ORDER MANAGEMENT
    # ─────────────────────────────────────────────────────────────────

    async def cancel_order(self, order_id: int):
        """Cancel an order."""
        if order_id in self.active_orders:
            trade = self.active_orders[order_id]
            self.ib.cancelOrder(trade.order)
            logger.info(f"Order cancelled: {order_id}")
        else:
            logger.warning(f"Order {order_id} not found in active orders")

    async def get_order_status(self, order_id: int) -> Optional[OrderStatus]:
        """Get current status of an order."""
        if order_id in self.active_orders:
            trade = self.active_orders[order_id]
            status_map = {
                'Submitted': OrderStatus.SUBMITTED,
                'Filled': OrderStatus.FILLED,
                'Cancelled': OrderStatus.CANCELLED,
                'ApiCancelled': OrderStatus.CANCELLED,
                'Rejected': OrderStatus.REJECTED,
                'Inactive': OrderStatus.EXPIRED
            }
            return status_map.get(trade.orderStatus.status, OrderStatus.PENDING)
        return None

    async def get_open_orders(self) -> List[Trade]:
        """Get all open orders."""
        return self.ib.openTrades()

    async def get_positions(self) -> List:
        """Get current positions."""
        return self.ib.positions()

    # ─────────────────────────────────────────────────────────────────
    # IDEMPOTENCY PROTECTION
    # ─────────────────────────────────────────────────────────────────

    def _check_duplicate_order(self, setup_id: str) -> bool:
        """
        Check if order already exists for this setup.

        Uses orderRef field to detect duplicate orders across reconnections.
        Checks both open trades and recent filled trades.

        Args:
            setup_id: Setup candidate ID (full UUID)

        Returns:
            True if duplicate detected, False otherwise
        """
        if not self.ib or not self.ib.isConnected():
            logger.debug("IB not connected - cannot check duplicates (fail-open)")
            return False

        # Create search pattern: first 8 chars of setup ID
        setup_prefix = f"SLOB_{setup_id[:8]}"

        # Check all open orders
        for trade in self.ib.openTrades():
            order_ref = getattr(trade.order, 'orderRef', None)
            if order_ref and setup_prefix in order_ref:
                logger.warning(
                    f"Duplicate order detected for setup {setup_id[:8]}: "
                    f"found in openTrades with orderRef={order_ref}"
                )
                return True

        # Check recent filled orders (last 24h)
        for trade in self.ib.trades():
            if trade.orderStatus.status in ['Filled', 'Submitted', 'PreSubmitted']:
                order_ref = getattr(trade.order, 'orderRef', None)
                if order_ref and setup_prefix in order_ref:
                    logger.warning(
                        f"Order already exists for setup {setup_id[:8]}: "
                        f"found in trades with orderRef={order_ref}, status={trade.orderStatus.status}"
                    )
                    return True

        logger.debug(f"No duplicate found for setup {setup_id[:8]}")
        return False

    # ─────────────────────────────────────────────────────────────────
    # POSITION SIZING
    # ─────────────────────────────────────────────────────────────────

    async def get_account_balance(self) -> float:
        """
        Retrieve live account balance from IBKR.

        CRITICAL: This method raises errors instead of falling back to cached values
        to prevent trading with incorrect or stale balance information.

        Returns:
            float: Current account balance (USD)

        Raises:
            RuntimeError: If IB not connected or account not configured
            ValueError: If NetLiquidation not found in account values
        """
        # Check IB connection
        if not self.ib or not self.ib.isConnected():
            raise RuntimeError("IB not connected - cannot fetch account balance")

        # Verify account is configured
        if not self.config.account:
            raise RuntimeError("Account not configured - cannot fetch balance")

        try:
            # Request account values from IB
            account_values = await self.ib.accountValuesAsync(account=self.config.account)

            # Find NetLiquidation (total account value)
            for av in account_values:
                if av.tag == 'NetLiquidation' and av.currency == 'USD':
                    balance = float(av.value)
                    self._cached_balance = balance
                    self.risk_manager.current_capital = balance
                    logger.info(f"Account balance: ${balance:,.2f}")
                    return balance

            # If NetLiquidation not found, throw error
            raise ValueError("NetLiquidation not found in account values")

        except Exception as e:
            logger.error(f"Failed to get account balance: {e}")
            raise

    async def validate_sufficient_capital(self, required_capital: float) -> bool:
        """
        Validate account has sufficient capital for trade.

        Checks current balance against required capital with 5% safety buffer.

        Args:
            required_capital: Required capital for the trade (USD)

        Returns:
            True if sufficient capital available, False otherwise
        """
        try:
            current_balance = await self.get_account_balance()
            available_cash = current_balance * 0.95  # Reserve 5% buffer

            if required_capital > available_cash:
                logger.error(
                    f"Insufficient capital: need ${required_capital:,.2f}, "
                    f"have ${available_cash:,.2f} (after 5% buffer)"
                )
                return False

            logger.debug(
                f"Capital check passed: ${required_capital:,.2f} / ${available_cash:,.2f} available"
            )
            return True

        except Exception as e:
            logger.error(f"Capital validation failed: {e}")
            return False  # Fail-safe: reject trade if can't validate

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss_price: float,
        atr: Optional[float] = None
    ) -> int:
        """
        Calculate position size using RiskManager.

        Delegates to RiskManager for sophisticated position sizing with:
        - Fixed % risk (1% default)
        - ATR-based volatility adjustment (optional)
        - Kelly Criterion (when enabled after 50+ trades)
        - Drawdown protection (reduces size at 15% DD, stops at 25%)

        Args:
            entry_price: Entry price
            stop_loss_price: SL price
            atr: Optional ATR for volatility adjustment

        Returns:
            int: Number of NQ contracts to trade
        """
        # Sync account balance from IB
        account_balance = self.get_account_balance()

        # Delegate to RiskManager
        result = self.risk_manager.calculate_position_size(
            entry_price=entry_price,
            sl_price=stop_loss_price,
            atr=atr,
            current_equity=account_balance
        )

        contracts = result.get('contracts', 0)

        # Apply max position size limit
        if contracts > self.config.max_position_size:
            logger.warning(
                f"RiskManager suggested {contracts} contracts, "
                f"limiting to max {self.config.max_position_size}"
            )
            contracts = self.config.max_position_size

        # Ensure minimum 1 contract if trading is enabled
        if contracts == 0 and result.get('method') != 'trading_disabled':
            contracts = 1
            logger.warning("Position size was 0, setting to minimum 1 contract")

        logger.info(
            f"Position size calculated: {contracts} contracts\n"
            f"  Method: {result.get('method')}\n"
            f"  Account: ${account_balance:,.2f}\n"
            f"  Risk: ${result.get('risk_amount', 0):.2f} "
            f"({result.get('risk_pct', 0)*100:.1f}%)\n"
            f"  SL Distance: {abs(entry_price - stop_loss_price):.2f} points"
        )

        return contracts

    # ─────────────────────────────────────────────────────────────────
    # STATISTICS
    # ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        """Get executor statistics."""
        return {
            'orders_submitted': self.orders_submitted,
            'orders_filled': self.orders_filled,
            'orders_rejected': self.orders_rejected,
            'active_orders': len(self.active_orders),
            'fill_rate': self.orders_filled / self.orders_submitted if self.orders_submitted > 0 else 0
        }

    # ─────────────────────────────────────────────────────────────────
    # CLEANUP
    # ─────────────────────────────────────────────────────────────────

    async def close(self):
        """Close IB connection."""
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()
            logger.info("OrderExecutor disconnected from IB")
