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


logger = logging.getLogger(__name__)


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
        port: int = 7497,
        client_id: int = 2,  # Different from data fetcher
        account: Optional[str] = None,
        paper_trading: bool = True,
        max_retry_attempts: int = 3,
        retry_delay_seconds: float = 1.0,
        default_position_size: int = 1,  # NQ contracts
        max_position_size: int = 5,
        enable_bracket_orders: bool = True,
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

        # Statistics
        self.orders_submitted = 0
        self.orders_filled = 0
        self.orders_rejected = 0

    async def initialize(self):
        """
        Initialize IB connection and resolve NQ contract.

        Steps:
        1. Connect to IB TWS/Gateway
        2. Resolve NQ front month contract
        3. Verify account and permissions
        """
        logger.info("Initializing OrderExecutor...")

        # Connect to IB
        self.ib = IB()

        try:
            await self.ib.connectAsync(
                host=self.config.host,
                port=self.config.port,
                clientId=self.config.client_id,
                readonly=False  # Need write access for orders
            )
            logger.info(f"✅ Connected to IB: {self.config.host}:{self.config.port}")
        except Exception as e:
            logger.error(f"Failed to connect to IB: {e}")
            raise

        # Resolve NQ contract
        self.nq_contract = await self._resolve_nq_contract()
        logger.info(f"✅ NQ contract resolved: {self.nq_contract.localSymbol}")

        # Get account info
        if self.config.account:
            account_values = self.ib.accountValues(account=self.config.account)
            logger.info(f"Account: {self.config.account} ({len(account_values)} values)")

        logger.info("✅ OrderExecutor initialized")

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

        # Determine position size
        qty = position_size or self.config.default_position_size

        if qty > self.config.max_position_size:
            logger.warning(
                f"Position size {qty} exceeds max {self.config.max_position_size}. "
                f"Using max."
            )
            qty = self.config.max_position_size

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
        # Create parent order (entry)
        # For SHORT setup: SELL to enter
        parent_order = LimitOrder(
            action='SELL',
            totalQuantity=qty,
            lmtPrice=setup.entry_price,
            orderId=self.ib.client.getReqId(),
            transmit=False  # Don't transmit yet (wait for children)
        )

        # Create stop loss (BUY to close SHORT)
        stop_loss = StopOrder(
            action='BUY',
            totalQuantity=qty,
            stopPrice=setup.sl_price,
            orderId=self.ib.client.getReqId(),
            parentId=parent_order.orderId,
            transmit=False
        )

        # Create take profit (BUY to close SHORT)
        take_profit = LimitOrder(
            action='BUY',
            totalQuantity=qty,
            lmtPrice=setup.tp_price,
            orderId=self.ib.client.getReqId(),
            parentId=parent_order.orderId,
            transmit=True  # Transmit all orders together
        )

        # Place bracket (all 3 orders)
        try:
            # Place parent
            parent_trade = self.ib.placeOrder(self.nq_contract, parent_order)

            # Place children
            sl_trade = self.ib.placeOrder(self.nq_contract, stop_loss)
            tp_trade = self.ib.placeOrder(self.nq_contract, take_profit)

            # Wait for submission confirmation
            await asyncio.sleep(0.5)  # Give IB time to process

            # Track orders
            self.active_orders[parent_order.orderId] = parent_trade
            self.active_orders[stop_loss.orderId] = sl_trade
            self.active_orders[take_profit.orderId] = tp_trade

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
                await asyncio.sleep(0.2)

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

            await asyncio.sleep(0.5)

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
    # POSITION SIZING
    # ─────────────────────────────────────────────────────────────────

    def calculate_position_size(
        self,
        account_balance: float,
        risk_per_trade: float,
        entry_price: float,
        stop_loss_price: float
    ) -> int:
        """
        Calculate position size based on risk management.

        Args:
            account_balance: Current account balance
            risk_per_trade: Risk per trade (e.g., 0.01 = 1%)
            entry_price: Entry price
            stop_loss_price: Stop loss price

        Returns:
            Number of NQ contracts
        """
        # Risk amount in dollars
        risk_amount = account_balance * risk_per_trade

        # Points at risk per contract
        points_risk = abs(stop_loss_price - entry_price)

        # NQ multiplier = $20 per point
        nq_multiplier = 20

        # Dollar risk per contract
        dollar_risk_per_contract = points_risk * nq_multiplier

        # Calculate contracts
        contracts = int(risk_amount / dollar_risk_per_contract)

        # Clamp to max position size
        contracts = min(contracts, self.config.max_position_size)
        contracts = max(contracts, 1)  # At least 1 contract

        logger.info(
            f"Position sizing: ${account_balance:,.0f} × {risk_per_trade*100}% / "
            f"{points_risk} pts = {contracts} contracts"
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
