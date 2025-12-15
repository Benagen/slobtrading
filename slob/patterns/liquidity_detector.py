"""
Enhanced Liquidity Detection with Multi-Factor Confirmation.

Detects liquidity grabs (LIQ #1 and LIQ #2) using multiple confirmation signals:
1. Level break
2. Volume spike
3. Price rejection
4. Wick reversal

Uses composite scoring instead of single-factor detection.
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, List, Tuple
import logging

logger = logging.getLogger(__name__)


class LiquidityDetector:
    """Detect liquidity grabs using multi-factor confirmation"""

    @staticmethod
    def detect_liquidity_grab(
        df: pd.DataFrame,
        idx: int,
        level: float,
        direction: str = 'up',
        lookback: int = 50,
        volume_threshold: float = 1.5,
        min_score: float = 0.6
    ) -> Optional[Dict]:
        """
        Detect liquidity grab at specific candle using multi-factor confirmation.

        Args:
            df: OHLCV DataFrame
            idx: Index to check for liquidity grab
            level: Price level that should be broken (e.g., LSE High for upward break)
            direction: 'up' for break above level, 'down' for break below
            lookback: Candles to look back for volume comparison
            volume_threshold: Volume spike multiplier (1.5 = 150% of average)
            min_score: Minimum composite score to confirm (0-1)

        Returns:
            Dict with liquidity grab details or None:
                - detected: bool
                - score: Composite score (0-1)
                - volume_spike: bool
                - has_rejection: bool
                - wick_reversal: bool
                - break_distance: How far past level
                - signals: Dict of individual signal values
        """
        if idx < lookback:
            logger.debug(f"Not enough data for lookback: idx={idx}, need={lookback}")
            return None

        if idx >= len(df):
            return None

        current = df.iloc[idx]
        start = max(0, idx - lookback)
        window = df.iloc[start:idx]

        # Signal 1: Level break
        if direction == 'up':
            level_broken = current['High'] > level
            break_distance = current['High'] - level if level_broken else 0
        else:
            level_broken = current['Low'] < level
            break_distance = level - current['Low'] if level_broken else 0

        if not level_broken:
            logger.debug(f"Level not broken: {current['High']:.2f} vs {level:.2f}")
            return None

        # Signal 2: Volume spike
        avg_volume = window['Volume'].mean()
        volume_spike = current['Volume'] > avg_volume * volume_threshold

        # Signal 3: Price rejection (break level then close back)
        if direction == 'up':
            has_rejection = current['High'] > level and current['Close'] < level
        else:
            has_rejection = current['Low'] < level and current['Close'] > level

        # Signal 4: Wick reversal (large wick in break direction)
        candle_range = current['High'] - current['Low']
        
        if candle_range > 0:
            if direction == 'up':
                upper_wick = current['High'] - max(current['Open'], current['Close'])
                wick_ratio = upper_wick / candle_range
            else:
                lower_wick = min(current['Open'], current['Close']) - current['Low']
                wick_ratio = lower_wick / candle_range
            
            has_wick_reversal = wick_ratio > 0.5
        else:
            wick_ratio = 0
            has_wick_reversal = False

        # Calculate composite score
        score = 0.0
        
        # Volume spike (40% weight)
        if volume_spike:
            score += 0.4

        # Price rejection (30% weight)
        if has_rejection:
            score += 0.3

        # Wick reversal (30% weight)
        if has_wick_reversal:
            score += 0.3

        detected = score >= min_score

        result = {
            'detected': detected,
            'score': score,
            'volume_spike': volume_spike,
            'has_rejection': has_rejection,
            'wick_reversal': has_wick_reversal,
            'break_distance': break_distance,
            'signals': {
                'level_broken': level_broken,
                'volume_ratio': current['Volume'] / avg_volume if avg_volume > 0 else 0,
                'wick_ratio': wick_ratio,
                'rejection': has_rejection
            }
        }

        if detected:
            logger.info(f"Liquidity grab detected: score={score:.2f}, "
                       f"volume_spike={volume_spike}, rejection={has_rejection}, "
                       f"wick_reversal={has_wick_reversal}")

        return result

    @staticmethod
    def find_liquidity_grabs(
        df: pd.DataFrame,
        start_idx: int,
        end_idx: int,
        level: float,
        direction: str = 'up',
        min_score: float = 0.6
    ) -> List[Dict]:
        """
        Find all liquidity grabs in a window.

        Args:
            df: OHLCV DataFrame
            start_idx: Start of search window
            end_idx: End of search window
            level: Price level to break
            direction: 'up' or 'down'
            min_score: Minimum score to include

        Returns:
            List of liquidity grab dicts with idx, time, score
        """
        liquidity_grabs = []

        for idx in range(start_idx, min(end_idx, len(df))):
            result = LiquidityDetector.detect_liquidity_grab(
                df, idx, level, direction, min_score=min_score
            )

            if result and result['detected']:
                liquidity_grabs.append({
                    'idx': idx,
                    'time': df.index[idx],
                    'score': result['score'],
                    'volume_spike': result['volume_spike'],
                    'has_rejection': result['has_rejection'],
                    'wick_reversal': result['wick_reversal'],
                    'break_distance': result['break_distance']
                })

        return liquidity_grabs

    @staticmethod
    def get_best_liquidity_grab(
        df: pd.DataFrame,
        start_idx: int,
        end_idx: int,
        level: float,
        direction: str = 'up'
    ) -> Optional[Dict]:
        """
        Get the best (highest score) liquidity grab in a window.

        Args:
            df: OHLCV DataFrame
            start_idx: Start of search window
            end_idx: End of search window
            level: Price level to break
            direction: 'up' or 'down'

        Returns:
            Dict with best liquidity grab info, or None
        """
        candidates = LiquidityDetector.find_liquidity_grabs(
            df, start_idx, end_idx, level, direction
        )

        if not candidates:
            return None

        # Return grab with highest score
        best = max(candidates, key=lambda x: x['score'])
        return best

    @staticmethod
    def validate_liquidity_grab(
        df: pd.DataFrame,
        liq_dict: Dict,
        level: float,
        direction: str = 'up',
        strict: bool = False
    ) -> Tuple[bool, List[str]]:
        """
        Validate a detected liquidity grab.

        Args:
            df: OHLCV DataFrame
            liq_dict: Liquidity grab dict from detect_liquidity_grab
            level: Price level that was broken
            direction: 'up' or 'down'
            strict: Apply stricter validation

        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []

        # Check score threshold
        min_score = 0.7 if strict else 0.5
        if liq_dict['score'] < min_score:
            issues.append(f"Score too low: {liq_dict['score']:.2f} < {min_score}")

        # Check volume spike in strict mode
        if strict and not liq_dict['volume_spike']:
            issues.append("No volume spike detected")

        # Check rejection or wick reversal present
        if not liq_dict['has_rejection'] and not liq_dict['wick_reversal']:
            issues.append("No rejection or wick reversal (weak signal)")

        # Check break distance is reasonable
        if liq_dict['break_distance'] < 0.1:
            issues.append(f"Break distance too small: {liq_dict['break_distance']:.2f}")

        is_valid = len(issues) == 0

        return is_valid, issues

    @staticmethod
    def calculate_liquidity_strength(
        df: pd.DataFrame,
        idx: int,
        level: float,
        direction: str = 'up',
        lookback: int = 100
    ) -> Dict:
        """
        Calculate additional liquidity strength metrics.

        Args:
            df: OHLCV DataFrame
            idx: Liquidity grab index
            level: Price level
            direction: 'up' or 'down'
            lookback: Lookback period for context

        Returns:
            Dict with strength metrics:
                - attempts: Number of attempts to break level before success
                - time_at_level: Minutes spent near level
                - momentum: Price momentum at break
        """
        if idx < lookback:
            lookback = idx

        start = max(0, idx - lookback)
        window = df.iloc[start:idx + 1]

        # Count attempts (how many times price touched level)
        tolerance = (window['High'] - window['Low']).mean() * 0.1
        
        if direction == 'up':
            attempts = ((window['High'] >= level - tolerance) & 
                       (window['High'] <= level + tolerance)).sum()
        else:
            attempts = ((window['Low'] <= level + tolerance) & 
                       (window['Low'] >= level - tolerance)).sum()

        # Time at level (consecutive candles near level before break)
        time_at_level = 0
        for i in range(idx - 1, max(0, idx - 20), -1):
            candle = df.iloc[i]
            if direction == 'up':
                near_level = abs(candle['High'] - level) < tolerance
            else:
                near_level = abs(candle['Low'] - level) < tolerance
            
            if near_level:
                time_at_level += 1
            else:
                break

        # Momentum (price change in last 5 candles)
        if idx >= 5:
            momentum_window = df.iloc[idx - 5:idx + 1]
            momentum = (momentum_window['Close'].iloc[-1] - 
                       momentum_window['Close'].iloc[0])
        else:
            momentum = 0

        return {
            'attempts': attempts,
            'time_at_level': time_at_level,
            'momentum': momentum,
            'strength_score': min(attempts / 3.0, 1.0) * 0.5 + 
                            min(time_at_level / 5.0, 1.0) * 0.5
        }


    @staticmethod
    def detect_sequential_liquidity(
        df: pd.DataFrame,
        liq1_level: float,
        liq2_level: float,
        liq1_idx: int,
        direction: str = 'up',
        min_gap: int = 5,
        max_gap: int = 30
    ) -> Optional[Dict]:
        """
        Detect LIQ #2 following LIQ #1 with proper spacing.

        Args:
            df: OHLCV DataFrame
            liq1_level: LIQ #1 price level
            liq2_level: LIQ #2 price level (higher than LIQ #1 for 'up')
            liq1_idx: Index where LIQ #1 occurred
            direction: 'up' or 'down'
            min_gap: Minimum candles between LIQ #1 and LIQ #2
            max_gap: Maximum candles between LIQ #1 and LIQ #2

        Returns:
            Dict with LIQ #2 info if found, else None
        """
        search_start = liq1_idx + min_gap
        search_end = min(liq1_idx + max_gap, len(df))

        # Find best LIQ #2 in window
        liq2 = LiquidityDetector.get_best_liquidity_grab(
            df,
            start_idx=search_start,
            end_idx=search_end,
            level=liq2_level,
            direction=direction
        )

        if liq2:
            liq2['gap_from_liq1'] = liq2['idx'] - liq1_idx
            logger.info(f"Sequential liquidity detected: LIQ#2 at idx {liq2['idx']}, "
                       f"gap={liq2['gap_from_liq1']} candles")

        return liq2
