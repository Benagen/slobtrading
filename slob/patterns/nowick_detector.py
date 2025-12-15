"""
Percentile-Based No-Wick Candle Detection.

Detects "no-wick" candles (bullish for SHORT setups) using percentile-based
thresholds that adapt to current market volatility instead of fixed pip values.

A no-wick candle indicates "false strength" before the final liquidity sweep.
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class NoWickDetector:
    """Detect no-wick candles using adaptive percentile thresholds"""

    @staticmethod
    def is_no_wick_candle(
        candle: pd.Series,
        df: pd.DataFrame,
        idx: int,
        direction: str = 'bullish',
        percentile: int = 90,
        lookback: int = 100,
        body_percentile_min: int = 30,
        body_percentile_max: int = 70
    ) -> bool:
        """
        Check if candle is a no-wick candle using percentile thresholds.

        Args:
            candle: Single candle (row from DataFrame)
            df: Full OHLCV DataFrame with wick columns
            idx: Index of candle in df
            direction: 'bullish' for SHORT setup, 'bearish' for LONG setup
            percentile: Wick must be smaller than this percentile (90 = smaller than 90% of candles)
            lookback: How many candles to look back for percentile calculation
            body_percentile_min: Minimum body size percentile (30 = larger than 30% of candles)
            body_percentile_max: Maximum body size percentile (70 = smaller than 30% of candles)

        Returns:
            True if candle qualifies as no-wick candle
        """
        # Calculate wick sizes if not already in dataframe
        if 'Upper_Wick_Pips' not in df.columns:
            df = NoWickDetector._add_wick_columns(df)

        # Get historical context
        start = max(0, idx - lookback)
        historical = df.iloc[start:idx]

        if len(historical) < 10:
            logger.debug(f"Not enough historical data: {len(historical)} candles")
            return False

        # 1. Check candle direction
        is_bullish = candle['Close'] > candle['Open']
        is_bearish = candle['Close'] < candle['Open']

        if direction == 'bullish' and not is_bullish:
            return False
        elif direction == 'bearish' and not is_bearish:
            return False

        # 2. Check wick size (percentile-based)
        wick_col = 'Upper_Wick_Pips' if direction == 'bullish' else 'Lower_Wick_Pips'
        
        if wick_col not in historical.columns:
            logger.warning(f"Column {wick_col} not found in DataFrame")
            return False

        # Calculate percentile threshold
        wick_threshold = historical[wick_col].quantile(1 - percentile/100)

        current_wick = candle[wick_col]

        if current_wick > wick_threshold:
            logger.debug(f"Wick too large: {current_wick:.2f} > threshold {wick_threshold:.2f}")
            return False

        # 3. Check body size (should be moderate, not tiny or huge)
        body_col = 'Body_Pips'
        
        if body_col not in historical.columns:
            logger.warning(f"Column {body_col} not found in DataFrame")
            return False

        body_min = historical[body_col].quantile(body_percentile_min / 100)
        body_max = historical[body_col].quantile(body_percentile_max / 100)

        current_body = candle[body_col]

        if current_body < body_min:
            logger.debug(f"Body too small: {current_body:.2f} < min {body_min:.2f}")
            return False

        if current_body > body_max:
            logger.debug(f"Body too large: {current_body:.2f} > max {body_max:.2f}")
            return False

        logger.info(f"No-wick candle detected: wick={current_wick:.2f} (threshold={wick_threshold:.2f}), "
                   f"body={current_body:.2f} (range=[{body_min:.2f}, {body_max:.2f}])")

        return True

    @staticmethod
    def find_no_wick_candles(
        df: pd.DataFrame,
        start_idx: int,
        end_idx: int,
        direction: str = 'bullish',
        percentile: int = 90,
        lookback: int = 100
    ) -> list:
        """
        Find all no-wick candles in a window.

        Args:
            df: OHLCV DataFrame
            start_idx: Start of search window
            end_idx: End of search window
            direction: 'bullish' or 'bearish'
            percentile: Wick percentile threshold
            lookback: Lookback period for percentile

        Returns:
            List of dicts with no-wick candle info:
                - idx: Index in DataFrame
                - time: Timestamp
                - wick_size: Wick size in pips
                - body_size: Body size in pips
                - score: Quality score (0-1)
        """
        if 'Upper_Wick_Pips' not in df.columns:
            df = NoWickDetector._add_wick_columns(df)

        no_wick_candles = []

        for idx in range(start_idx, end_idx):
            if idx >= len(df):
                break

            candle = df.iloc[idx]

            if NoWickDetector.is_no_wick_candle(
                candle, df, idx, direction, percentile, lookback
            ):
                # Calculate quality score
                score = NoWickDetector._calculate_no_wick_score(candle, df, idx, direction, lookback)

                no_wick_candles.append({
                    'idx': idx,
                    'time': df.index[idx],
                    'wick_size': candle['Upper_Wick_Pips'] if direction == 'bullish' else candle['Lower_Wick_Pips'],
                    'body_size': candle['Body_Pips'],
                    'score': score
                })

        return no_wick_candles

    @staticmethod
    def get_best_no_wick(
        df: pd.DataFrame,
        start_idx: int,
        end_idx: int,
        direction: str = 'bullish'
    ) -> Optional[Dict]:
        """
        Get the best (highest quality) no-wick candle in a window.

        Args:
            df: OHLCV DataFrame
            start_idx: Start of search window
            end_idx: End of search window
            direction: 'bullish' or 'bearish'

        Returns:
            Dict with best no-wick candle info, or None if none found
        """
        candidates = NoWickDetector.find_no_wick_candles(
            df, start_idx, end_idx, direction
        )

        if not candidates:
            return None

        # Return candle with highest score
        best = max(candidates, key=lambda x: x['score'])
        return best

    @staticmethod
    def _add_wick_columns(df: pd.DataFrame) -> pd.DataFrame:
        """
        Add wick and body size columns to DataFrame.

        Args:
            df: OHLCV DataFrame

        Returns:
            DataFrame with added columns:
                - Upper_Wick_Pips: Upper wick size
                - Lower_Wick_Pips: Lower wick size
                - Body_Pips: Body size
                - Range_Pips: Total candle range
        """
        df = df.copy()

        # Body size
        df['Body_Pips'] = abs(df['Close'] - df['Open'])

        # Wick sizes
        df['Upper_Wick_Pips'] = df['High'] - df[['Open', 'Close']].max(axis=1)
        df['Lower_Wick_Pips'] = df[['Open', 'Close']].min(axis=1) - df['Low']

        # Total range
        df['Range_Pips'] = df['High'] - df['Low']

        return df

    @staticmethod
    def _calculate_no_wick_score(
        candle: pd.Series,
        df: pd.DataFrame,
        idx: int,
        direction: str,
        lookback: int
    ) -> float:
        """
        Calculate quality score for no-wick candle.

        Factors:
        1. How small is the wick (smaller = better)
        2. Body size (moderate is better than tiny or huge)
        3. Volume (higher = more conviction)

        Args:
            candle: Candle to score
            df: Full DataFrame
            idx: Candle index
            direction: 'bullish' or 'bearish'
            lookback: Lookback period

        Returns:
            Score between 0 and 1
        """
        start = max(0, idx - lookback)
        historical = df.iloc[start:idx]

        if len(historical) < 10:
            return 0.5  # Neutral score

        score = 0.0

        # 1. Wick size score (smaller = better)
        wick_col = 'Upper_Wick_Pips' if direction == 'bullish' else 'Lower_Wick_Pips'
        wick_percentile = (historical[wick_col] < candle[wick_col]).sum() / len(historical)
        
        # Invert: small wick (low percentile) = high score
        wick_score = 1.0 - wick_percentile
        score += wick_score * 0.4

        # 2. Body size score (moderate = better)
        body_percentile = (historical['Body_Pips'] < candle['Body_Pips']).sum() / len(historical)
        
        # Penalize if too small (<20th) or too large (>80th)
        if body_percentile < 0.2:
            body_score = body_percentile / 0.2  # Linear 0-1
        elif body_percentile > 0.8:
            body_score = (1.0 - body_percentile) / 0.2  # Linear 1-0
        else:
            body_score = 1.0  # Perfect range

        score += body_score * 0.3

        # 3. Volume score (higher = more conviction)
        if 'Volume' in df.columns and len(historical) > 0:
            vol_percentile = (historical['Volume'] < candle['Volume']).sum() / len(historical)
            volume_score = vol_percentile  # High volume = high score
            score += volume_score * 0.3
        else:
            score += 0.15  # Neutral if no volume

        return score

    @staticmethod
    def validate_no_wick(
        candle: pd.Series,
        df: pd.DataFrame,
        idx: int,
        direction: str = 'bullish',
        strict: bool = False
    ) -> Tuple[bool, list]:
        """
        Validate a detected no-wick candle.

        Args:
            candle: Candle to validate
            df: Full DataFrame
            idx: Candle index
            direction: 'bullish' or 'bearish'
            strict: Apply stricter validation

        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []

        if 'Upper_Wick_Pips' not in df.columns:
            df = NoWickDetector._add_wick_columns(df)

        # Check direction
        is_bullish = candle['Close'] > candle['Open']
        is_bearish = candle['Close'] < candle['Open']

        if direction == 'bullish' and not is_bullish:
            issues.append("Candle is not bullish")
        elif direction == 'bearish' and not is_bearish:
            issues.append("Candle is not bearish")

        # Check wick is actually small
        wick_col = 'Upper_Wick_Pips' if direction == 'bullish' else 'Lower_Wick_Pips'
        body_col = 'Body_Pips'

        wick_to_body_ratio = candle[wick_col] / candle[body_col] if candle[body_col] > 0 else float('inf')

        max_ratio = 0.2 if strict else 0.4  # Wick should be <20% (strict) or <40% of body

        if wick_to_body_ratio > max_ratio:
            issues.append(f"Wick to body ratio too high: {wick_to_body_ratio:.2f} > {max_ratio}")

        # Check body is not tiny
        if candle[body_col] < 0.5:  # Less than 0.5 pips is too small
            issues.append(f"Body too small: {candle[body_col]:.2f} pips")

        is_valid = len(issues) == 0

        return is_valid, issues
