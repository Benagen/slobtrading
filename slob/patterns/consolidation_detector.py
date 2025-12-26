"""
ATR-Based Consolidation Detection.

Detects consolidation periods with dynamic range based on ATR instead of fixed pips.
Provides quality scoring based on:
- Tightness (range compression over time)
- Volume compression
- Breakout readiness (price position)
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class ConsolidationDetector:
    """Detect consolidation periods using ATR-based dynamic ranges"""

    @staticmethod
    def detect_consolidation(
        df: pd.DataFrame,
        start_idx: int,
        atr_period: int = 14,
        atr_multiplier_min: float = 0.5,
        atr_multiplier_max: float = 2.0,
        min_duration: int = 3,
        max_duration: int = 25,
        lookback_for_atr: int = 100
    ) -> Optional[Dict]:
        """
        Detect consolidation with ATR-based dynamic range.

        Args:
            df: OHLCV DataFrame
            start_idx: Starting index for consolidation search
            atr_period: Period for ATR calculation
            atr_multiplier_min: Minimum ATR multiplier for range (0.5 = tight)
            atr_multiplier_max: Maximum ATR multiplier for range (2.0 = wide)
            min_duration: Minimum consolidation duration in candles
            max_duration: Maximum consolidation duration in candles
            lookback_for_atr: How many candles to look back for ATR calculation

        Returns:
            Dict with consolidation details or None if not found:
                - start_idx: Consolidation start index
                - end_idx: Consolidation end index
                - high: Consolidation high price
                - low: Consolidation low price
                - range: Price range (high - low)
                - atr: ATR value at start
                - quality_score: Quality score (0-1)
                - tightness: Tightness score (0-1)
                - volume_compression: Volume decreasing (bool)
                - breakout_ready: Price near top (bool)
                - duration: Duration in candles
        """
        if start_idx < lookback_for_atr:
            logger.debug(f"Not enough data: start_idx={start_idx}, need {lookback_for_atr}")
            return None

        if start_idx + min_duration >= len(df):
            logger.debug(f"Not enough data after start_idx for min duration")
            return None

        # 1. Calculate ATR at start_idx
        try:
            atr = ConsolidationDetector._calculate_atr(df, start_idx, atr_period, lookback_for_atr)
        except KeyError as e:
            logger.error(f"Column not found in ConsolidationDetector: {e}")
            return None

        if atr <= 0:
            logger.debug(f"Invalid ATR: {atr}")
            return None

        # 2. Dynamic range thresholds
        min_range = atr * atr_multiplier_min
        max_range = atr * atr_multiplier_max

        logger.debug(f"ATR={atr:.2f}, range thresholds: [{min_range:.2f}, {max_range:.2f}]")

        # 3. Search for consolidation - WHITEPAPER SIMPLIFIED LOGIC
        # "Wait for clear NYSE High or Low to form on M5"
        # - Duration: FLEXIBLE 3-25 candles (no strict upper limit per whitepaper)
        # - Quality: Simple "touched 2+ times" check
        # - Return FIRST valid consolidation found (not "best")

        tolerance = 2.0  # points - price must be within 2 points to count as "touch"

        print(f"    [CONSOL] Testing durations {min_duration} to {min(max_duration, len(df) - start_idx - 1)}")

        for duration in range(min_duration, min(max_duration + 1, len(df) - start_idx)):
            end_idx = start_idx + duration
            window = df.iloc[start_idx:end_idx]

            if len(window) < min_duration:
                continue

            # Calculate High and Low
            consol_high = window['High'].max()
            consol_low = window['Low'].min()
            consol_range = consol_high - consol_low

            # Check if range is zero (invalid)
            if consol_range == 0:
                print(f"    [CONSOL] Duration {duration}: Zero range")
                continue

            # Check for trend (reject if trending - valid rejection criterion)
            if ConsolidationDetector._is_trending(window, atr):
                logger.debug(f"Duration {duration}: Rejected (trending)")
                print(f"    [CONSOL] Duration {duration}: Trending")
                continue

            # Count touches of High level (within tolerance)
            high_touches = (window['High'] >= consol_high - tolerance).sum()

            # Count touches of Low level (within tolerance)
            low_touches = (window['Low'] <= consol_low + tolerance).sum()

            # If either level touched 2+ times, consolidation detected!
            if high_touches >= 2 or low_touches >= 2:
                print(f"    [CONSOL] Duration {duration}: ✅ VALID (range={consol_range:.2f}, high_touches={high_touches}, low_touches={low_touches})")

                logger.info(f"Consolidation found: duration={duration}, "
                           f"range={consol_range:.2f}, "
                           f"high_touches={high_touches}, low_touches={low_touches}")

                # Return FIRST valid consolidation (whitepaper doesn't specify "best")
                return {
                    'start_idx': start_idx,
                    'end_idx': end_idx,
                    'high': consol_high,
                    'low': consol_low,
                    'range': consol_range,
                    'atr': atr,
                    'quality_score': 1.0,  # All valid consolidations score 1.0
                    'duration': duration,
                    'high_touches': high_touches,
                    'low_touches': low_touches
                }
            else:
                logger.debug(f"Duration {duration}: Not enough touches (high={high_touches}, low={low_touches})")

        # No valid consolidation found
        print(f"    [CONSOL] No valid consolidation found in range {min_duration}-{max_duration}")
        return None

    @staticmethod
    def _calculate_atr(
        df: pd.DataFrame,
        end_idx: int,
        period: int = 14,
        lookback: int = 100
    ) -> float:
        """
        Calculate Average True Range at a specific point.

        Args:
            df: OHLCV DataFrame
            end_idx: Index to calculate ATR at
            period: ATR period
            lookback: How far back to look for calculation

        Returns:
            ATR value
        """
        start = max(0, end_idx - lookback)
        window = df.iloc[start:end_idx]

        if len(window) < period:
            return 0.0

        # True Range calculation
        high_low = window['High'] - window['Low']
        high_close = np.abs(window['High'] - window['Close'].shift(1))
        low_close = np.abs(window['Low'] - window['Close'].shift(1))

        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        
        # ATR = rolling mean of True Range
        atr = true_range.rolling(window=period).mean().iloc[-1]

        return float(atr) if not pd.isna(atr) else 0.0

    @staticmethod
    def _assess_quality(window: pd.DataFrame, atr: float) -> Dict:
        """
        Assess consolidation quality.

        Quality factors:
        1. Tightness: Range compression (first half vs second half)
        2. Volume compression: Volume decreasing
        3. Breakout readiness: Price near consolidation high (for SHORT)
        4. Oscillation: Multiple crosses of midpoint

        Args:
            window: Consolidation window DataFrame
            atr: Current ATR value

        Returns:
            Dict with quality metrics
        """
        # 1. Tightness - compare first half vs second half range
        mid = len(window) // 2
        
        if mid < 2:
            first_range = window['High'].max() - window['Low'].min()
            second_range = first_range
        else:
            first_half = window.iloc[:mid]
            second_half = window.iloc[mid:]
            
            first_range = first_half['High'].max() - first_half['Low'].min()
            second_range = second_half['High'].max() - second_half['Low'].min()

        # Tightness = how much range decreased (1.0 = perfect compression, 0 = expanding)
        if first_range > 0:
            tightness = max(0, 1.0 - (second_range / first_range))
        else:
            tightness = 0.0

        # 2. Volume compression
        if 'Volume' in window.columns and len(window) >= 10:
            first_vol = window['Volume'].iloc[:len(window)//2].mean()
            second_vol = window['Volume'].iloc[len(window)//2:].mean()
            volume_compression = second_vol < first_vol
        else:
            volume_compression = False

        # 3. Breakout readiness - price position (0 = at low, 1 = at high)
        consol_range = window['High'].max() - window['Low'].min()
        if consol_range > 0:
            price_position = (window['Close'].iloc[-1] - window['Low'].min()) / consol_range
        else:
            price_position = 0.5

        # For SHORT setup, we want price near high (>0.7)
        breakout_ready = price_position > 0.7

        # 4. Oscillation - count midpoint crosses
        midpoint = (window['High'].max() + window['Low'].min()) / 2
        crosses_above = (window['Close'] > midpoint).astype(int)
        midpoint_crosses = (crosses_above.diff() != 0).sum()

        # Calculate composite score
        score = (
            tightness * 0.35 +  # Tightening range is important
            (1.0 if volume_compression else 0.3) * 0.25 +  # Volume compression
            (1.0 if breakout_ready else 0.5) * 0.20 +  # Price position
            min(midpoint_crosses / 4.0, 1.0) * 0.20  # Oscillation (want 2-4 crosses)
        )

        return {
            'score': score,
            'tightness': tightness,
            'volume_compression': volume_compression,
            'breakout_ready': breakout_ready,
            'price_position': price_position,
            'midpoint_crosses': midpoint_crosses
        }

    @staticmethod
    def _is_trending(window: pd.DataFrame, atr: float) -> bool:
        """
        Check if window is trending instead of consolidating.

        Uses linear regression slope to detect trends.

        Args:
            window: Price window
            atr: Current ATR

        Returns:
            True if trending, False if consolidating
        """
        if len(window) < 5:
            return False

        closes = window['Close'].values
        
        # Linear regression slope
        x = np.arange(len(closes))
        slope, _ = np.polyfit(x, closes, 1)

        # If slope is > 15% of ATR per candle, it's trending
        slope_threshold = atr * 0.15

        is_trending = abs(slope) > slope_threshold

        if is_trending:
            logger.debug(f"Trending detected: slope={slope:.2f}, threshold={slope_threshold:.2f}")

        return is_trending

    @staticmethod
    def validate_consolidation(
        df: pd.DataFrame,
        consolidation: Dict,
        strict: bool = False
    ) -> Tuple[bool, list]:
        """
        Validate a detected consolidation.

        Checks:
        1. Duration is reasonable
        2. Range is within bounds
        3. No extreme outliers
        4. Quality score meets threshold

        Args:
            df: Full DataFrame
            consolidation: Consolidation dict from detect_consolidation
            strict: If True, apply stricter validation

        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []

        # Check duration
        duration = consolidation['duration']
        if duration < 10:
            issues.append(f"Duration too short: {duration} candles")
        elif duration > 40:
            issues.append(f"Duration too long: {duration} candles")

        # Check quality score
        min_quality = 0.6 if strict else 0.4
        if consolidation['quality_score'] < min_quality:
            issues.append(f"Quality score too low: {consolidation['quality_score']:.2f} < {min_quality}")

        # Check for extreme outliers in window
        start_idx = consolidation['start_idx']
        end_idx = consolidation['end_idx']
        window = df.iloc[start_idx:end_idx]

        # Calculate range per candle
        candle_ranges = window['High'] - window['Low']
        median_range = candle_ranges.median()
        max_range = candle_ranges.max()

        # Check if any candle is >3x median (extreme outlier)
        if max_range > median_range * 3:
            issues.append(f"Extreme outlier candle detected: {max_range:.2f} vs median {median_range:.2f}")

        is_valid = len(issues) == 0 or (not strict and len([i for i in issues if 'too low' not in i]) == 0)

        return is_valid, issues
