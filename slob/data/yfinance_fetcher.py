"""
Enhanced YFinance data fetcher with retry logic and validation.

Improvements over basic yfinance:
- Exponential backoff retry logic
- Rate limit handling
- Automatic M5 fallback if M1 fails
- Comprehensive data validation
- Detailed error logging
"""

import yfinance as yf
import pandas as pd
import time
import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional

from .base_fetcher import BaseDataFetcher

logger = logging.getLogger(__name__)


class YFinanceFetcher(BaseDataFetcher):
    """Enhanced YFinance data fetcher with robust error handling"""

    MAX_RETRIES = 3
    BACKOFF_FACTOR = 2
    TIMEOUT_SECONDS = 30

    # YFinance free tier limits (conservative estimate)
    REQUESTS_PER_MINUTE = 30
    REQUESTS_PER_DAY = 2000

    def __init__(self):
        """Initialize YFinance fetcher"""
        super().__init__(name="yfinance")
        self.request_count = 0
        self.last_request_time = None

    def fetch_ohlcv(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1m"
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data with retry logic and validation.

        Args:
            symbol: Trading symbol (e.g., 'NQ=F')
            start: Start datetime
            end: End datetime
            interval: Data interval ('1m', '5m', '15m', etc.)

        Returns:
            DataFrame with DatetimeIndex and columns: Open, High, Low, Close, Volume

        Raises:
            ValueError: If data cannot be fetched or validation fails
            ConnectionError: If API is unreachable after retries
        """
        logger.info(f"Fetching {symbol} {interval} data from {start} to {end}")

        for attempt in range(self.MAX_RETRIES):
            try:
                # Rate limit check
                self._check_rate_limit()

                # Fetch data
                df = self._fetch_with_timeout(symbol, start, end, interval)

                # Validate
                if self.validate_data(df):
                    logger.info(
                        f"Successfully fetched {len(df)} rows of {symbol} {interval} data"
                    )
                    return df

            except Exception as e:
                logger.warning(
                    f"Attempt {attempt + 1}/{self.MAX_RETRIES} failed: {e}"
                )

                if attempt == self.MAX_RETRIES - 1:
                    # Last attempt failed
                    logger.error(f"All retry attempts exhausted for {symbol} {interval}")

                    # Try fallback to M5 if fetching M1
                    if interval == "1m":
                        logger.info("Attempting fallback to M5 data...")
                        try:
                            return self.fetch_ohlcv(symbol, start, end, interval="5m")
                        except Exception as fallback_error:
                            logger.error(f"M5 fallback also failed: {fallback_error}")

                    raise ValueError(
                        f"Failed to fetch {symbol} {interval} data after {self.MAX_RETRIES} attempts: {e}"
                    )

                # Exponential backoff
                sleep_time = self.BACKOFF_FACTOR ** attempt
                logger.info(f"Retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)

        raise ConnectionError("Unreachable code - should have raised earlier")

    def _fetch_with_timeout(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str
    ) -> pd.DataFrame:
        """
        Fetch data from yfinance with timeout.

        Args:
            symbol: Trading symbol
            start: Start datetime
            end: End datetime
            interval: Data interval

        Returns:
            Raw DataFrame from yfinance

        Raises:
            ValueError: If fetch fails or returns empty data
        """
        try:
            # Create ticker object
            ticker = yf.Ticker(symbol)

            # Fetch historical data
            df = ticker.history(
                start=start,
                end=end,
                interval=interval,
                actions=False,  # Don't need dividends/splits
                auto_adjust=False,  # Keep raw OHLC
                back_adjust=False,
                timeout=self.TIMEOUT_SECONDS
            )

            # Track request
            self.request_count += 1
            self.last_request_time = datetime.now()

            if df.empty:
                raise ValueError(f"YFinance returned empty data for {symbol}")

            # Clean column names (yfinance sometimes adds ticker prefix)
            df.columns = df.columns.str.replace(f'{symbol}.', '', regex=False)

            # Ensure we have required columns
            required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                raise ValueError(f"Missing columns: {missing_cols}")

            # Keep only OHLCV columns
            df = df[required_cols]

            # Ensure index is timezone-aware and converted to Europe/Stockholm
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC')
            df.index = df.index.tz_convert('Europe/Stockholm')

            return df

        except Exception as e:
            logger.error(f"YFinance fetch error: {e}")
            raise

    def _check_rate_limit(self) -> None:
        """
        Check and enforce rate limits.

        Sleeps if necessary to avoid hitting rate limits.
        """
        if self.last_request_time is None:
            return

        # Simple rate limiting: max 1 request per 2 seconds (conservative)
        time_since_last = (datetime.now() - self.last_request_time).total_seconds()
        min_interval = 2.0

        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)

    def check_availability(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str
    ) -> bool:
        """
        Check if data is available for the given parameters.

        YFinance M1 data limitations:
        - Only last 7-30 days available (varies by symbol)
        - Some symbols don't support M1 at all

        Args:
            symbol: Trading symbol
            start: Start datetime
            end: End datetime
            interval: Data interval

        Returns:
            True if data is likely available, False otherwise
        """
        # Check if date range is too old for M1 data
        if interval == "1m":
            days_ago = (datetime.now() - start).days
            if days_ago > 30:
                logger.warning(
                    f"M1 data requested for {days_ago} days ago - "
                    "YFinance typically only has 7-30 days of M1 data"
                )
                return False

        # Check if date range is in the future
        if start > datetime.now():
            logger.warning("Start date is in the future")
            return False

        return True

    def get_rate_limit(self) -> Tuple[int, int]:
        """
        Get rate limit information.

        Returns:
            Tuple of (requests_per_minute, requests_per_day)
        """
        return (self.REQUESTS_PER_MINUTE, self.REQUESTS_PER_DAY)

    def get_available_intervals(self) -> list:
        """
        Get list of available intervals.

        Returns:
            List of interval strings
        """
        return ['1m', '2m', '5m', '15m', '30m', '60m', '90m', '1h', '1d', '5d', '1wk', '1mo', '3mo']

    def get_max_period(self, interval: str) -> int:
        """
        Get maximum historical period available for an interval.

        Args:
            interval: Data interval

        Returns:
            Maximum days of historical data available
        """
        # YFinance limitations (approximate)
        max_periods = {
            '1m': 7,
            '2m': 60,
            '5m': 60,
            '15m': 60,
            '30m': 60,
            '60m': 730,
            '1h': 730,
            '1d': 36500,  # ~100 years
            '5d': 36500,
            '1wk': 36500,
            '1mo': 36500,
            '3mo': 36500
        }

        return max_periods.get(interval, 60)

    def __repr__(self) -> str:
        return f"<YFinanceFetcher(requests={self.request_count})>"
