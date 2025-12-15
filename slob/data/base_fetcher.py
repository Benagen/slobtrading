"""
Abstract base class for data fetchers.

All data source implementations (yfinance, polygon, etc.) must inherit from this class.
"""

from abc import ABC, abstractmethod
import pandas as pd
from datetime import datetime
from typing import Tuple, Optional


class BaseDataFetcher(ABC):
    """Abstract base class for all data fetchers"""

    def __init__(self, name: str):
        """
        Initialize data fetcher.

        Args:
            name: Name of the data source (e.g., 'yfinance', 'polygon')
        """
        self.name = name

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1m"
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data for a symbol.

        Args:
            symbol: Trading symbol (e.g., 'NQ=F')
            start: Start datetime
            end: End datetime
            interval: Data interval ('1m', '5m', '15m', etc.)

        Returns:
            DataFrame with DatetimeIndex and columns: Open, High, Low, Close, Volume

        Raises:
            ValueError: If data cannot be fetched
            ConnectionError: If API is unreachable
        """
        pass

    @abstractmethod
    def check_availability(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str
    ) -> bool:
        """
        Check if data is available before fetching.

        Args:
            symbol: Trading symbol
            start: Start datetime
            end: End datetime
            interval: Data interval

        Returns:
            True if data is available, False otherwise
        """
        pass

    @abstractmethod
    def get_rate_limit(self) -> Tuple[int, int]:
        """
        Get rate limit information for this data source.

        Returns:
            Tuple of (requests_per_minute, requests_per_day)
        """
        pass

    def validate_data(self, df: pd.DataFrame) -> bool:
        """
        Basic validation of fetched data.

        Args:
            df: DataFrame to validate

        Returns:
            True if data is valid

        Raises:
            ValueError: If data validation fails
        """
        if df.empty:
            raise ValueError(f"{self.name}: Fetched data is empty")

        required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            raise ValueError(
                f"{self.name}: Missing required columns: {missing_columns}"
            )

        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError(f"{self.name}: Index must be DatetimeIndex")

        # Validate OHLC relationships
        # High must be >= Open and Close
        invalid_high = (df['High'] < df[['Open', 'Close']].max(axis=1)).sum()
        if invalid_high > 0:
            raise ValueError(
                f"{self.name}: {invalid_high} candles have High < max(Open, Close)"
            )

        # Low must be <= Open and Close
        invalid_low = (df['Low'] > df[['Open', 'Close']].min(axis=1)).sum()
        if invalid_low > 0:
            raise ValueError(
                f"{self.name}: {invalid_low} candles have Low > min(Open, Close)"
            )

        # Check for negative prices
        if (df[['Open', 'High', 'Low', 'Close']] < 0).any().any():
            raise ValueError(f"{self.name}: Negative prices detected")

        # Check for negative volume
        if (df['Volume'] < 0).any():
            raise ValueError(f"{self.name}: Negative volume detected")

        return True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}')>"
