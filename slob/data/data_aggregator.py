"""
Data Aggregator - Orchestrates multiple data sources with fallback chain.

Fallback strategy:
1. Check cache
2. Try fetching M1 from primary source (yfinance)
3. If M1 fails, fetch M5 and generate synthetic M1
4. Cache the result
5. Return data with metadata
"""

import pandas as pd
import logging
from datetime import datetime
from typing import List, Optional, Dict
from pathlib import Path

from .base_fetcher import BaseDataFetcher
from .cache_manager import CacheManager
from .synthetic_generator import SyntheticGenerator

logger = logging.getLogger(__name__)


class DataAggregator:
    """Orchestrates data fetching from multiple sources with caching and fallbacks"""

    def __init__(
        self,
        fetchers: List[BaseDataFetcher],
        cache_manager: Optional[CacheManager] = None,
        cache_dir: str = "data_cache",
        use_cache: bool = True
    ):
        """
        Initialize Data Aggregator.

        Args:
            fetchers: List of data fetchers (prioritized in order)
            cache_manager: Optional custom cache manager
            cache_dir: Directory for cache storage
            use_cache: Whether to use caching
        """
        self.fetchers = fetchers
        self.use_cache = use_cache

        # Initialize cache manager
        if cache_manager is None and use_cache:
            self.cache = CacheManager(cache_dir=cache_dir)
        else:
            self.cache = cache_manager

        logger.info(
            f"DataAggregator initialized with {len(fetchers)} fetcher(s), "
            f"cache={'enabled' if use_cache else 'disabled'}"
        )

    def fetch_data(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1m",
        force_refresh: bool = False
    ) -> Dict:
        """
        Fetch OHLCV data with intelligent fallback strategy.

        Fallback chain:
        1. Check cache (if enabled and not force_refresh)
        2. Try M1 from each fetcher in priority order
        3. If all M1 attempts fail, try M5 + synthetic generation
        4. Cache and return result

        Args:
            symbol: Trading symbol (e.g., 'NQ=F')
            start: Start datetime
            end: End datetime
            interval: Target interval (default '1m')
            force_refresh: Skip cache and re-fetch

        Returns:
            Dict with keys:
                - 'data': DataFrame with OHLCV data
                - 'source': Data source name
                - 'interval': Actual interval fetched
                - 'synthetic': Whether data is synthetic
                - 'cache_hit': Whether data came from cache
                - 'metadata': Additional metadata

        Raises:
            ValueError: If no data could be fetched from any source
        """
        logger.info(
            f"Fetching {symbol} {interval} data from {start} to {end} "
            f"(force_refresh={force_refresh})"
        )

        metadata = {
            'symbol': symbol,
            'start': start,
            'end': end,
            'requested_interval': interval,
            'attempts': []
        }

        # Step 1: Check cache
        if self.use_cache and not force_refresh:
            cached_df = self.cache.get_cached_data(
                symbol=symbol,
                start=start,
                end=end,
                interval=interval,
                source="any"
            )

            if cached_df is not None:
                is_synthetic = 'Synthetic' in cached_df.columns and cached_df['Synthetic'].any()

                logger.info(f"✓ Cache hit for {symbol} {interval} ({len(cached_df)} rows)")

                return {
                    'data': cached_df,
                    'source': 'cache',
                    'interval': interval,
                    'synthetic': is_synthetic,
                    'cache_hit': True,
                    'metadata': metadata
                }

            logger.debug(f"Cache miss for {symbol} {interval}")
            metadata['attempts'].append({'source': 'cache', 'result': 'miss'})

        # Step 2: Try fetching M1 from each fetcher
        if interval == "1m":
            df_m1 = self._fetch_m1_from_sources(symbol, start, end, metadata)

            if df_m1 is not None:
                # Cache the result
                if self.use_cache:
                    self._cache_data(df_m1, symbol, start, end, interval, metadata['last_successful_source'])

                return {
                    'data': df_m1,
                    'source': metadata['last_successful_source'],
                    'interval': '1m',
                    'synthetic': False,
                    'cache_hit': False,
                    'metadata': metadata
                }

        # Step 3: Fallback to M5 + synthetic M1 generation
        if interval == "1m":
            logger.info("All M1 sources failed. Attempting M5 → synthetic M1 fallback...")

            df_synthetic = self._fetch_and_generate_synthetic(symbol, start, end, metadata)

            if df_synthetic is not None:
                # Cache the synthetic data
                if self.use_cache:
                    self._cache_data(df_synthetic, symbol, start, end, "1m", "synthetic")

                return {
                    'data': df_synthetic,
                    'source': 'synthetic',
                    'interval': '1m',
                    'synthetic': True,
                    'cache_hit': False,
                    'metadata': metadata
                }

        # Step 4: If requesting non-M1 interval, fetch directly
        if interval != "1m":
            for fetcher in self.fetchers:
                try:
                    logger.info(f"Attempting {interval} from {fetcher.name}...")

                    df = fetcher.fetch_ohlcv(symbol, start, end, interval)

                    metadata['attempts'].append({
                        'source': fetcher.name,
                        'interval': interval,
                        'result': 'success',
                        'rows': len(df)
                    })

                    # Cache the result
                    if self.use_cache:
                        self._cache_data(df, symbol, start, end, interval, fetcher.name)

                    logger.info(f"✓ Successfully fetched {interval} from {fetcher.name} ({len(df)} rows)")

                    return {
                        'data': df,
                        'source': fetcher.name,
                        'interval': interval,
                        'synthetic': False,
                        'cache_hit': False,
                        'metadata': metadata
                    }

                except Exception as e:
                    logger.warning(f"✗ {fetcher.name} failed for {interval}: {e}")
                    metadata['attempts'].append({
                        'source': fetcher.name,
                        'interval': interval,
                        'result': 'failed',
                        'error': str(e)
                    })
                    continue

        # All attempts failed
        logger.error(f"All data sources exhausted for {symbol} {interval}")
        raise ValueError(
            f"Could not fetch {symbol} {interval} data from any source. "
            f"Attempts: {len(metadata['attempts'])}"
        )

    def _fetch_m1_from_sources(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        metadata: Dict
    ) -> Optional[pd.DataFrame]:
        """
        Try fetching M1 data from all available sources.

        Args:
            symbol: Trading symbol
            start: Start datetime
            end: End datetime
            metadata: Metadata dict to update

        Returns:
            DataFrame if successful, None otherwise
        """
        for fetcher in self.fetchers:
            try:
                logger.info(f"Attempting M1 from {fetcher.name}...")

                # Check availability first
                if not fetcher.check_availability(symbol, start, end, "1m"):
                    logger.debug(f"{fetcher.name} reports M1 unavailable for this date range")
                    metadata['attempts'].append({
                        'source': fetcher.name,
                        'interval': '1m',
                        'result': 'unavailable'
                    })
                    continue

                df = fetcher.fetch_ohlcv(symbol, start, end, "1m")

                metadata['attempts'].append({
                    'source': fetcher.name,
                    'interval': '1m',
                    'result': 'success',
                    'rows': len(df)
                })
                metadata['last_successful_source'] = fetcher.name

                logger.info(f"✓ Successfully fetched M1 from {fetcher.name} ({len(df)} rows)")

                return df

            except Exception as e:
                logger.warning(f"✗ {fetcher.name} M1 failed: {e}")
                metadata['attempts'].append({
                    'source': fetcher.name,
                    'interval': '1m',
                    'result': 'failed',
                    'error': str(e)
                })
                continue

        return None

    def _fetch_and_generate_synthetic(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        metadata: Dict
    ) -> Optional[pd.DataFrame]:
        """
        Fetch M5 data and generate synthetic M1.

        Args:
            symbol: Trading symbol
            start: Start datetime
            end: End datetime
            metadata: Metadata dict to update

        Returns:
            Synthetic M1 DataFrame if successful, None otherwise
        """
        for fetcher in self.fetchers:
            try:
                logger.info(f"Attempting M5 from {fetcher.name} for synthetic generation...")

                df_m5 = fetcher.fetch_ohlcv(symbol, start, end, "5m")

                metadata['attempts'].append({
                    'source': fetcher.name,
                    'interval': '5m',
                    'result': 'success',
                    'rows': len(df_m5)
                })

                # Generate synthetic M1
                logger.info(f"Generating synthetic M1 from {len(df_m5)} M5 candles...")

                df_m1 = SyntheticGenerator.generate_m1_from_m5(
                    df_m5,
                    method="brownian"
                )

                metadata['attempts'].append({
                    'source': 'synthetic_generator',
                    'interval': '1m',
                    'result': 'success',
                    'rows': len(df_m1),
                    'method': 'brownian',
                    'source_m5_rows': len(df_m5)
                })
                metadata['last_successful_source'] = f"{fetcher.name}_synthetic"

                logger.info(
                    f"✓ Generated {len(df_m1)} synthetic M1 candles "
                    f"from {len(df_m5)} M5 candles"
                )

                return df_m1

            except Exception as e:
                logger.warning(f"✗ {fetcher.name} M5 or synthetic generation failed: {e}")
                metadata['attempts'].append({
                    'source': fetcher.name,
                    'interval': '5m',
                    'result': 'failed',
                    'error': str(e)
                })
                continue

        return None

    def _cache_data(
        self,
        df: pd.DataFrame,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str,
        source: str
    ) -> None:
        """
        Cache data if caching is enabled.

        Args:
            df: DataFrame to cache
            symbol: Trading symbol
            start: Start datetime
            end: End datetime
            interval: Data interval
            source: Data source name
        """
        if not self.use_cache:
            return

        try:
            # Remove Synthetic column before caching
            df_to_cache = df.copy()
            if 'Synthetic' in df_to_cache.columns:
                df_to_cache = df_to_cache.drop('Synthetic', axis=1)

            self.cache.store_data(
                df=df_to_cache,
                symbol=symbol,
                start=start,
                end=end,
                interval=interval,
                source=source
            )

            logger.debug(f"Cached {len(df)} rows for {symbol} {interval} from {source}")

        except Exception as e:
            logger.warning(f"Failed to cache data: {e}")

    def get_cache_stats(self) -> Dict:
        """
        Get cache statistics.

        Returns:
            Dict with cache statistics (if caching enabled)
        """
        if not self.use_cache:
            return {'cache_enabled': False}

        stats = self.cache.get_cache_stats()
        stats['cache_enabled'] = True

        return stats

    def clear_cache(self, expired_only: bool = True) -> int:
        """
        Clear cache entries.

        Args:
            expired_only: If True, only clear expired entries

        Returns:
            Number of entries cleared
        """
        if not self.use_cache:
            logger.warning("Cache is not enabled")
            return 0

        if expired_only:
            return self.cache.clear_expired()
        else:
            self.cache.clear_all()
            return -1  # Indicate all cleared

    def __repr__(self) -> str:
        fetcher_names = [f.name for f in self.fetchers]
        return (
            f"<DataAggregator(fetchers={fetcher_names}, "
            f"cache={'enabled' if self.use_cache else 'disabled'})>"
        )
