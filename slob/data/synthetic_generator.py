"""
Synthetic M1 data generation from M5 data.

Uses Brownian Bridge method to create realistic intra-M5 price movements
while preserving OHLC constraints.

Methods:
- Brownian Bridge (recommended): Realistic volatility simulation
- Linear Interpolation (fast, simple): Linear path from Open to Close
- Volume-Weighted (advanced): Realistic volume distribution
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import Literal

logger = logging.getLogger(__name__)


class SyntheticGenerator:
    """Generate synthetic M1 data from M5 candles"""

    @staticmethod
    def generate_m1_from_m5(
        df_m5: pd.DataFrame,
        method: Literal["brownian", "linear", "volume_weighted"] = "brownian"
    ) -> pd.DataFrame:
        """
        Generate M1 data from M5 candles.

        Args:
            df_m5: M5 DataFrame with OHLCV data
            method: Generation method ('brownian', 'linear', 'volume_weighted')

        Returns:
            M1 DataFrame with synthetic data flagged

        Raises:
            ValueError: If df_m5 is empty or method is invalid
        """
        if df_m5.empty:
            raise ValueError("Input M5 dataframe is empty")

        methods = {
            "brownian": SyntheticGenerator._brownian_bridge,
            "linear": SyntheticGenerator._linear_interpolation,
            "volume_weighted": SyntheticGenerator._volume_weighted
        }

        if method not in methods:
            raise ValueError(
                f"Invalid method '{method}'. Choose from: {list(methods.keys())}"
            )

        logger.info(f"Generating M1 data from {len(df_m5)} M5 candles using {method} method")

        # Generate M1 data
        df_m1 = methods[method](df_m5)

        # Flag as synthetic
        df_m1['Synthetic'] = True

        logger.info(f"Generated {len(df_m1)} M1 candles ({len(df_m1) / len(df_m5):.1f}x expansion)")

        return df_m1

    @staticmethod
    def _brownian_bridge(df_m5: pd.DataFrame) -> pd.DataFrame:
        """
        Generate M1 using Brownian Bridge method.

        This creates realistic price movements that:
        - Start at M5.Open and end at M5.Close
        - Respect M5.High and M5.Low constraints
        - Have realistic volatility

        Args:
            df_m5: M5 DataFrame

        Returns:
            M1 DataFrame
        """
        m1_candles = []

        for idx, m5_row in df_m5.iterrows():
            # Generate 5 M1 candles for each M5 candle
            m1_times = pd.date_range(
                start=idx,
                periods=5,
                freq='1min',
                inclusive='left'  # Don't include the end (next M5 candle's start)
            )

            # Extract M5 OHLC
            m5_open = m5_row['Open']
            m5_high = m5_row['High']
            m5_low = m5_row['Low']
            m5_close = m5_row['Close']
            m5_volume = m5_row['Volume']

            # Generate price path using Brownian Bridge
            prices = SyntheticGenerator._generate_brownian_bridge(
                start=m5_open,
                end=m5_close,
                n_steps=5,
                volatility=abs(m5_high - m5_low),
                high_constraint=m5_high,
                low_constraint=m5_low
            )

            # Create M1 candles from price path
            # Generate volume weights once for all 5 M1 candles (ensures they sum correctly)
            volume_weights = np.random.dirichlet([1, 1, 1, 1, 1])

            # Determine which M1 candles should reach M5 high/low
            # Pick random candles to contain the extremes
            high_candle_idx = np.random.randint(0, 5)
            low_candle_idx = np.random.randint(0, 5)

            for i in range(5):
                # Each M1 candle goes from prices[i] to prices[i+1]
                m1_open = prices[i]
                m1_close = prices[i + 1] if i < 4 else m5_close

                max_oc = max(m1_open, m1_close)
                min_oc = min(m1_open, m1_close)

                # If this is the designated high candle, set high to M5 high
                if i == high_candle_idx:
                    m1_high = m5_high
                else:
                    # Random high within reasonable range
                    available_high_range = m5_high - max_oc
                    m1_high = max_oc + np.random.rand() * available_high_range * 0.5

                # If this is the designated low candle, set low to M5 low
                if i == low_candle_idx:
                    m1_low = m5_low
                else:
                    # Random low within reasonable range
                    available_low_range = min_oc - m5_low
                    m1_low = min_oc - np.random.rand() * available_low_range * 0.5

                # Ensure OHLC constraints
                m1_high = max(m1_high, max_oc)
                m1_low = min(m1_low, min_oc)

                # Distribute volume using pre-calculated weights
                m1_volume = int(m5_volume * volume_weights[i])

                m1_candles.append({
                    'Open': m1_open,
                    'High': m1_high,
                    'Low': m1_low,
                    'Close': m1_close,
                    'Volume': m1_volume
                })

        # Create M1 DataFrame
        # Generate complete M1 index
        if len(df_m5) > 0:
            start = df_m5.index[0]
            end = df_m5.index[-1] + timedelta(minutes=5)
            m1_index = pd.date_range(start=start, end=end, freq='1min', inclusive='left')

            df_m1 = pd.DataFrame(m1_candles, index=m1_index[:len(m1_candles)])
            return df_m1
        else:
            return pd.DataFrame()

    @staticmethod
    def _generate_brownian_bridge(
        start: float,
        end: float,
        n_steps: int,
        volatility: float,
        high_constraint: float,
        low_constraint: float,
        max_iterations: int = 100
    ) -> np.ndarray:
        """
        Generate price path using Brownian Bridge.

        The path starts at 'start', ends at 'end', and respects high/low constraints.

        Args:
            start: Starting price
            end: Ending price
            n_steps: Number of steps (5 for M1 from M5)
            volatility: M5 volatility (high - low)
            high_constraint: Maximum allowed price
            low_constraint: Minimum allowed price
            max_iterations: Max attempts to generate valid path

        Returns:
            Array of prices [start, p1, p2, p3, p4, end]
        """
        for attempt in range(max_iterations):
            # Initialize path
            path = np.zeros(n_steps + 1)
            path[0] = start
            path[n_steps] = end

            # Generate intermediate points using Brownian Bridge
            for i in range(1, n_steps):
                # Brownian Bridge formula
                # E[B(t) | B(0) = a, B(T) = b] = a + (b-a) * t/T
                # Var[B(t) | B(0) = a, B(T) = b] = t(T-t)/T * sigma^2

                t = i / n_steps
                mean = start + (end - start) * t
                variance = t * (1 - t) * (volatility ** 2) / n_steps

                # Generate random step
                path[i] = np.random.normal(mean, np.sqrt(variance))

            # Check constraints
            if path.max() <= high_constraint and path.min() >= low_constraint:
                return path

        # If we couldn't generate valid path, use linear interpolation
        logger.warning(
            f"Could not generate valid Brownian Bridge after {max_iterations} attempts. "
            "Using linear interpolation."
        )
        return np.linspace(start, end, n_steps + 1)

    @staticmethod
    def _linear_interpolation(df_m5: pd.DataFrame) -> pd.DataFrame:
        """
        Generate M1 using simple linear interpolation.

        Fast but unrealistic - price moves linearly from Open to Close.

        Args:
            df_m5: M5 DataFrame

        Returns:
            M1 DataFrame
        """
        m1_candles = []

        for idx, m5_row in df_m5.iterrows():
            m1_times = pd.date_range(
                start=idx,
                periods=5,
                freq='1min',
                inclusive='left'
            )

            # Linear price path from open to close
            prices = np.linspace(m5_row['Open'], m5_row['Close'], 6)

            for i in range(5):
                m1_open = prices[i]
                m1_close = prices[i + 1]

                # Simple high/low (just add/subtract small amount)
                m1_high = max(m1_open, m1_close) * 1.0005
                m1_low = min(m1_open, m1_close) * 0.9995

                # Equal volume distribution
                m1_volume = int(m5_row['Volume'] / 5)

                m1_candles.append({
                    'Open': m1_open,
                    'High': m1_high,
                    'Low': m1_low,
                    'Close': m1_close,
                    'Volume': m1_volume
                })

        # Create M1 DataFrame
        if len(df_m5) > 0:
            start = df_m5.index[0]
            end = df_m5.index[-1] + timedelta(minutes=5)
            m1_index = pd.date_range(start=start, end=end, freq='1min', inclusive='left')

            df_m1 = pd.DataFrame(m1_candles, index=m1_index[:len(m1_candles)])
            return df_m1
        else:
            return pd.DataFrame()

    @staticmethod
    def _volume_weighted(df_m5: pd.DataFrame) -> pd.DataFrame:
        """
        Generate M1 with volume-weighted price distribution.

        More volume at beginning and end of M5 candle (realistic for institutional flow).

        Args:
            df_m5: M5 DataFrame

        Returns:
            M1 DataFrame
        """
        m1_candles = []

        # Volume distribution pattern (U-shaped: more at start/end)
        volume_pattern = np.array([0.25, 0.15, 0.20, 0.15, 0.25])

        for idx, m5_row in df_m5.iterrows():
            m1_times = pd.date_range(
                start=idx,
                periods=5,
                freq='1min',
                inclusive='left'
            )

            # Use Brownian Bridge for prices
            prices = SyntheticGenerator._generate_brownian_bridge(
                start=m5_row['Open'],
                end=m5_row['Close'],
                n_steps=5,
                volatility=abs(m5_row['High'] - m5_row['Low']),
                high_constraint=m5_row['High'],
                low_constraint=m5_row['Low']
            )

            # Determine which M1 candles should reach M5 high/low
            high_candle_idx = np.random.randint(0, 5)
            low_candle_idx = np.random.randint(0, 5)

            for i in range(5):
                m1_open = prices[i]
                m1_close = prices[i + 1] if i < 4 else m5_row['Close']

                max_oc = max(m1_open, m1_close)
                min_oc = min(m1_open, m1_close)

                # If this is the designated high candle, set high to M5 high
                if i == high_candle_idx:
                    m1_high = m5_row['High']
                else:
                    m1_high = max_oc + np.random.rand() * (m5_row['High'] - max_oc) * 0.5

                # If this is the designated low candle, set low to M5 low
                if i == low_candle_idx:
                    m1_low = m5_row['Low']
                else:
                    m1_low = min_oc - np.random.rand() * (min_oc - m5_row['Low']) * 0.5

                # Ensure constraints
                m1_high = max(m1_high, max_oc)
                m1_low = min(m1_low, min_oc)

                # Volume-weighted distribution
                m1_volume = int(m5_row['Volume'] * volume_pattern[i])

                m1_candles.append({
                    'Open': m1_open,
                    'High': m1_high,
                    'Low': m1_low,
                    'Close': m1_close,
                    'Volume': m1_volume
                })

        # Create M1 DataFrame
        if len(df_m5) > 0:
            start = df_m5.index[0]
            end = df_m5.index[-1] + timedelta(minutes=5)
            m1_index = pd.date_range(start=start, end=end, freq='1min', inclusive='left')

            df_m1 = pd.DataFrame(m1_candles, index=m1_index[:len(m1_candles)])
            return df_m1
        else:
            return pd.DataFrame()

    @staticmethod
    def validate_synthetic_data(df_m1: pd.DataFrame, df_m5: pd.DataFrame) -> dict:
        """
        Validate that synthetic M1 data is consistent with source M5 data.

        Args:
            df_m1: Synthetic M1 DataFrame
            df_m5: Source M5 DataFrame

        Returns:
            Dict with validation metrics
        """
        issues = []
        metrics = {}

        # Check length (should be 5x)
        expected_len = len(df_m5) * 5
        actual_len = len(df_m1)

        if actual_len != expected_len:
            issues.append(f"Length mismatch: expected {expected_len}, got {actual_len}")

        metrics['length_ratio'] = actual_len / len(df_m5) if len(df_m5) > 0 else 0

        # Resample M1 back to M5 and compare
        if not df_m1.empty:
            m1_resampled = df_m1.resample('5min').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()

            # Compare OHLC
            if len(m1_resampled) == len(df_m5):
                # Check Open and Close (should match exactly)
                open_diff = abs(m1_resampled['Open'] - df_m5['Open']).max()
                close_diff = abs(m1_resampled['Close'] - df_m5['Close']).max()

                metrics['max_open_diff'] = open_diff
                metrics['max_close_diff'] = close_diff

                if open_diff > 0.01:  # Allow tiny floating point errors
                    issues.append(f"Open values differ by {open_diff:.4f}")

                if close_diff > 0.01:
                    issues.append(f"Close values differ by {close_diff:.4f}")

                # High and Low can differ due to random variations in M1 generation
                # Just check that resampled M1 high >= M5 high and low <= M5 low
                high_violations = (m1_resampled['High'] < df_m5['High'] - 0.01).sum()
                low_violations = (m1_resampled['Low'] > df_m5['Low'] + 0.01).sum()

                if high_violations > 0:
                    issues.append(f"{high_violations} M5 candles have M1 high < M5 high")

                if low_violations > 0:
                    issues.append(f"{low_violations} M5 candles have M1 low > M5 low")

                # Check volume (allow rounding errors from int conversion)
                volume_diff = abs(m1_resampled['Volume'] - df_m5['Volume']).max()
                metrics['max_volume_diff'] = volume_diff

                if volume_diff > 5:  # Up to 4 lost per M5 from int rounding
                    issues.append(f"Volume differs by {volume_diff}")

        metrics['issues'] = issues
        metrics['valid'] = len(issues) == 0

        return metrics
