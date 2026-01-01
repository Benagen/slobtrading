"""
Candle Aggregator

Aggregates market ticks into M1 (1-minute) candles.
Handles gap detection and emits candle-close events.
"""

import asyncio
import logging
from typing import Optional, Callable, Dict
from datetime import datetime, timedelta
from collections import defaultdict

from .ib_ws_fetcher import Tick

logger = logging.getLogger(__name__)


class Candle:
    """OHLCV Candle data."""

    def __init__(self, symbol: str, timestamp: datetime):
        """
        Initialize candle.

        Args:
            symbol: Symbol name
            timestamp: Candle timestamp (minute-aligned)
        """
        self.symbol = symbol
        self.timestamp = timestamp

        # OHLCV
        self.open: Optional[float] = None
        self.high: Optional[float] = None
        self.low: Optional[float] = None
        self.close: Optional[float] = None
        self.volume: int = 0

        # Tick count
        self.tick_count = 0

    def update(self, tick: Tick):
        """
        Update candle with tick data.

        Args:
            tick: Tick data
        """
        price = tick.price
        size = tick.size

        # First tick - set open
        if self.open is None:
            self.open = price
            self.high = price
            self.low = price
        else:
            # Update high/low
            if price > self.high:
                self.high = price
            if price < self.low:
                self.low = price

        # Always update close
        self.close = price

        # Add volume
        self.volume += size
        self.tick_count += 1

    def is_complete(self) -> bool:
        """Check if candle has all OHLCV data."""
        return all([
            self.open is not None,
            self.high is not None,
            self.low is not None,
            self.close is not None
        ])

    def to_dict(self) -> Dict:
        """
        Convert to dictionary.

        Returns:
            Dict with OHLCV data
        """
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'tick_count': self.tick_count
        }

    def __repr__(self):
        return (
            f"Candle(symbol={self.symbol}, timestamp={self.timestamp}, "
            f"O:{self.open}, H:{self.high}, L:{self.low}, C:{self.close}, V:{self.volume})"
        )


class CandleAggregator:
    """
    Aggregates ticks into M1 candles.

    Features:
    - Per-symbol candle tracking
    - Minute-aligned timestamps
    - Gap detection and filling
    - Candle-close event emission

    Usage:
        aggregator = CandleAggregator(
            on_candle_complete=handle_candle
        )

        # Process ticks
        await aggregator.process_tick(tick)

        # Automatically emits candle when minute closes
    """

    def __init__(
        self,
        on_candle_complete: Optional[Callable[[Candle], None]] = None,
        fill_gaps: bool = True,
        gap_threshold_seconds: int = 120
    ):
        """
        Initialize candle aggregator.

        Args:
            on_candle_complete: Callback when candle completes
            fill_gaps: Fill gaps with flat candles (default: True)
            gap_threshold_seconds: Max gap to fill (default: 120s)
        """
        self.on_candle_complete = on_candle_complete
        self.fill_gaps = fill_gaps
        self.gap_threshold_seconds = gap_threshold_seconds

        # Active candles per symbol
        self.active_candles: Dict[str, Candle] = {}

        # Last candle timestamp per symbol (for gap detection)
        self.last_candle_time: Dict[str, datetime] = {}

        # Statistics
        self.candles_completed = 0
        self.gaps_filled = 0
        self.ticks_processed = 0

    async def process_tick(self, tick: Tick):
        """
        Process incoming tick.

        Args:
            tick: Tick data
        """
        self.ticks_processed += 1

        # Get minute-aligned timestamp
        candle_time = self._get_minute_timestamp(tick.timestamp)

        symbol = tick.symbol

        # Check for gaps
        if symbol in self.last_candle_time:
            await self._check_and_fill_gaps(symbol, candle_time, tick.price)

        # Get or create active candle
        if symbol not in self.active_candles:
            # New candle
            self.active_candles[symbol] = Candle(symbol, candle_time)
            logger.debug(f"Started new candle for {symbol} at {candle_time}")

        elif self.active_candles[symbol].timestamp != candle_time:
            # Minute changed - complete previous candle
            await self._complete_candle(symbol)

            # Start new candle
            self.active_candles[symbol] = Candle(symbol, candle_time)
            logger.debug(f"Started new candle for {symbol} at {candle_time}")

        # Update candle with tick
        self.active_candles[symbol].update(tick)

    def _get_minute_timestamp(self, dt: datetime) -> datetime:
        """
        Get minute-aligned timestamp.

        Args:
            dt: Datetime

        Returns:
            Minute-aligned datetime (seconds/microseconds set to 0)
        """
        return dt.replace(second=0, microsecond=0)

    async def _check_and_fill_gaps(self, symbol: str, current_time: datetime, last_price: float):
        """
        Check for gaps and fill if needed.

        Args:
            symbol: Symbol name
            current_time: Current candle time
            last_price: Last known price (for gap filling)
        """
        last_time = self.last_candle_time[symbol]

        # Calculate gap in minutes
        time_diff = (current_time - last_time).total_seconds()
        gap_minutes = int(time_diff / 60) - 1

        if gap_minutes > 0:
            # Gap detected
            if time_diff <= self.gap_threshold_seconds and self.fill_gaps:
                # Fill gap with flat candles
                logger.warning(
                    f"Gap detected for {symbol}: {gap_minutes} minutes "
                    f"({last_time} -> {current_time}). Filling with flat candles."
                )

                for i in range(1, gap_minutes + 1):
                    gap_time = last_time + timedelta(minutes=i)
                    gap_candle = Candle(symbol, gap_time)

                    # Flat candle (all prices same, zero volume)
                    gap_candle.open = last_price
                    gap_candle.high = last_price
                    gap_candle.low = last_price
                    gap_candle.close = last_price
                    gap_candle.volume = 0

                    await self._emit_candle(gap_candle)
                    self.gaps_filled += 1

            else:
                # Gap too large or gap filling disabled
                logger.warning(
                    f"Large gap detected for {symbol}: {time_diff:.0f}s "
                    f"({last_time} -> {current_time}). Not filling."
                )

    async def _complete_candle(self, symbol: str):
        """
        Complete and emit candle.

        Args:
            symbol: Symbol name
        """
        if symbol not in self.active_candles:
            return

        candle = self.active_candles[symbol]

        if candle.is_complete():
            await self._emit_candle(candle)
            self.candles_completed += 1

            # Update last candle time
            self.last_candle_time[symbol] = candle.timestamp

        else:
            logger.warning(f"Incomplete candle for {symbol} at {candle.timestamp}: {candle}")

    async def _emit_candle(self, candle: Candle):
        """
        Emit completed candle.

        Args:
            candle: Completed candle
        """
        logger.debug(f"Candle completed: {candle}")

        if self.on_candle_complete:
            try:
                if asyncio.iscoroutinefunction(self.on_candle_complete):
                    await self.on_candle_complete(candle)
                else:
                    self.on_candle_complete(candle)
            except Exception as e:
                logger.error(f"Error in candle completion handler: {e}")

    async def force_complete_all(self):
        """Force completion of all active candles."""
        logger.info(f"Force completing {len(self.active_candles)} active candles")

        for symbol in list(self.active_candles.keys()):
            await self._complete_candle(symbol)

        self.active_candles.clear()

    def get_active_candle(self, symbol: str) -> Optional[Candle]:
        """
        Get active candle for symbol.

        Args:
            symbol: Symbol name

        Returns:
            Active candle or None
        """
        return self.active_candles.get(symbol)

    def get_stats(self) -> Dict:
        """
        Get aggregator statistics.

        Returns:
            Dict with stats
        """
        return {
            'ticks_processed': self.ticks_processed,
            'candles_completed': self.candles_completed,
            'gaps_filled': self.gaps_filled,
            'active_candles': len(self.active_candles),
            'symbols': list(self.active_candles.keys())
        }
