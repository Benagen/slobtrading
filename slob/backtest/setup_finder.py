"""
5/1 SLOB Setup Finder - Orchestration Layer

Implements the EXACT 5/1 SLOB strategy flow:
1. LSE Session (09:00-15:30) → Establish LSE High/Low
2. LIQ #1 (NYSE session, >15:30) → Break LSE High with volume
3. Consolidation (15-30 min) → SIDEWAYS oscillation (NOT diagonal trend)
4. No-Wick Candle → Bullish (for SHORT) with minimal upper wick
5. LIQ #2 → Break consolidation high
6. Entry Trigger → Candle closes below no-wick low
7. Entry Execution → Next candle's OPEN price
8. SL/TP → LIQ #2 high / LSE Low

Critical considerations:
- No look-ahead bias (incremental discovery)
- NYSE session timing (AFTER 15:30 for LIQ #1)
- Proper indexing (global vs relative)
- Edge case handling (missing data, spikes, invalidations)
"""

import pandas as pd
import numpy as np
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple
import logging

from slob.patterns import ConsolidationDetector, NoWickDetector, LiquidityDetector

logger = logging.getLogger(__name__)


class SetupFinder:
    """Finds 5/1 SLOB setups in OHLCV data following exact strategy rules"""

    def __init__(
        self,
        atr_period: int = 14,
        consol_min_duration: int = 15,
        consol_max_duration: int = 30,
        atr_multiplier_min: float = 0.5,
        atr_multiplier_max: float = 3.0,
        nowick_percentile: int = 90,
        max_retracement_pips: float = 100.0,
        max_entry_wait_candles: int = 20
    ):
        """
        Initialize Setup Finder.

        Args:
            atr_period: Period for ATR calculation
            consol_min_duration: Min consolidation duration (minutes)
            consol_max_duration: Max consolidation duration (minutes)
            atr_multiplier_min: Min ATR multiplier for consolidation range
            atr_multiplier_max: Max ATR multiplier for consolidation range
            nowick_percentile: Percentile threshold for no-wick detection
            max_retracement_pips: Max pips above no-wick high before invalidation
            max_entry_wait_candles: Max candles to wait for entry trigger
        """
        self.atr_period = atr_period
        self.consol_min_duration = consol_min_duration
        self.consol_max_duration = consol_max_duration
        self.atr_multiplier_min = atr_multiplier_min
        self.atr_multiplier_max = atr_multiplier_max
        self.nowick_percentile = nowick_percentile
        self.max_retracement_pips = max_retracement_pips
        self.max_entry_wait_candles = max_entry_wait_candles

        # Session times (UTC)
        self.lse_open = time(9, 0)
        self.lse_close = time(15, 30)
        self.nyse_open = time(15, 30)

    def find_setups(
        self,
        df: pd.DataFrame,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        verbose: bool = False
    ) -> List[Dict]:
        """
        Find all valid 5/1 SLOB setups in data.

        Args:
            df: OHLCV DataFrame with datetime index
            start_date: Start date for search
            end_date: End date for search
            verbose: Print progress

        Returns:
            List of setup dicts with all details
        """
        if start_date:
            df = df.loc[start_date:]
        if end_date:
            df = df.loc[:end_date]

        if verbose:
            print(f"\n{'='*80}")
            print(f"5/1 SLOB Setup Finder")
            print(f"{'='*80}")
            print(f"Data period: {df.index[0]} to {df.index[-1]}")
            print(f"Total candles: {len(df)}")
            print(f"{'='*80}\n")

        setups = []

        # Group by date
        df['date'] = df.index.date
        dates = df['date'].unique()

        for date in dates:
            if verbose:
                print(f"\nProcessing {date}...")

            day_df = df[df['date'] == date].copy()

            # Find setups for this day
            day_setups = self._find_setups_for_day(day_df, verbose=verbose)

            setups.extend(day_setups)

            if verbose and len(day_setups) > 0:
                print(f"  ✓ Found {len(day_setups)} setup(s)")

        if verbose:
            print(f"\n{'='*80}")
            print(f"Total setups found: {len(setups)}")
            print(f"{'='*80}\n")

        return setups

    def _find_setups_for_day(self, df: pd.DataFrame, verbose: bool = False) -> List[Dict]:
        """
        Find setups for a single day.

        Returns:
            List of setups found on this day
        """
        setups = []

        # STEP 1: Establish LSE High/Low (09:00-15:30)
        lse_high, lse_low, lse_end_idx = self._get_lse_levels(df)

        if lse_high is None:
            if verbose:
                print(f"  ✗ No LSE session data")
            return []

        if verbose:
            print(f"  LSE High: {lse_high:.2f}, LSE Low: {lse_low:.2f}")

        # STEP 2: Find LIQ #1 (NYSE breaks LSE High)
        liq1_results = self._find_liq1_candidates(df, lse_high, lse_end_idx)

        if len(liq1_results) == 0:
            if verbose:
                print(f"  ✗ No LIQ #1 found")
            return []

        # For each LIQ #1, try to find complete setup
        for liq1 in liq1_results:
            setup = self._build_setup_from_liq1(
                df, liq1, lse_high, lse_low, verbose=verbose
            )

            if setup is not None:
                setups.append(setup)

        return setups

    def _get_lse_levels(self, df: pd.DataFrame) -> Tuple[Optional[float], Optional[float], Optional[int]]:
        """
        Get LSE High/Low from 09:00-15:30 session.

        Returns:
            (lse_high, lse_low, lse_end_idx)
        """
        # Filter LSE session (09:00-15:30)
        lse_mask = (df.index.time >= self.lse_open) & (df.index.time < self.lse_close)
        lse_data = df[lse_mask]

        if len(lse_data) == 0:
            return None, None, None

        lse_high = lse_data['High'].max()
        lse_low = lse_data['Low'].min()

        # Get global index of LSE session end
        lse_end_idx = df.index.get_loc(lse_data.index[-1])

        return lse_high, lse_low, lse_end_idx

    def _find_liq1_candidates(
        self,
        df: pd.DataFrame,
        lse_high: float,
        lse_end_idx: int
    ) -> List[Dict]:
        """
        Find LIQ #1 candidates (NYSE breaks LSE High).

        Critical rules:
        - MUST be in NYSE session (>= 15:30)
        - Price breaks ABOVE LSE High
        - Volume confirmation

        Returns:
            List of LIQ #1 dicts with {idx, price, level, confidence}
        """
        candidates = []

        # Search ONLY in NYSE session (after LSE close)
        nyse_start_idx = lse_end_idx + 1

        if nyse_start_idx >= len(df):
            return []

        # Search for breaks above LSE High
        for i in range(nyse_start_idx, len(df)):
            candle = df.iloc[i]

            # Check if in NYSE session (>= 15:30)
            if candle.name.time() < self.nyse_open:
                continue

            # Check if breaks LSE High
            if candle['High'] > lse_high:
                # Detect liquidity grab using liquidity detector
                liq_result = LiquidityDetector.detect_liquidity_grab(
                    df, i, lse_high, direction='up'
                )

                if liq_result['detected']:
                    candidates.append({
                        'idx': i,  # GLOBAL index
                        'price': candle['High'],
                        'level': lse_high,
                        'confidence': liq_result['score'],
                        'time': candle.name
                    })

                    # Take first valid LIQ #1
                    # (Could also take highest confidence, but first is simpler)
                    break

        return candidates

    def _build_setup_from_liq1(
        self,
        df: pd.DataFrame,
        liq1: Dict,
        lse_high: float,
        lse_low: float,
        verbose: bool = False
    ) -> Optional[Dict]:
        """
        Try to build complete setup from LIQ #1.

        Flow:
        1. Find consolidation after LIQ #1
        2. Find no-wick candle in consolidation
        3. Find LIQ #2 (break consolidation high)
        4. Find entry trigger (close below no-wick low)
        5. Calculate entry, SL, TP

        Returns:
            Complete setup dict or None if setup invalid
        """
        liq1_idx = liq1['idx']

        # STEP 3: Find consolidation after LIQ #1
        consol = self._find_consolidation_after_liq1(df, liq1_idx)

        if consol is None:
            if verbose:
                print(f"    ✗ No valid consolidation after LIQ #1 @ {liq1['time']}")
            return None

        if verbose:
            print(f"    ✓ Consolidation found: {consol['start_idx']} to {consol['end_idx']}")

        # STEP 4: Find no-wick candle in consolidation
        nowick = self._find_nowick_in_consolidation(df, consol)

        if nowick is None:
            if verbose:
                print(f"      ✗ No valid no-wick candle")
            return None

        if verbose:
            print(f"      ✓ No-wick @ {nowick['idx']}: High={nowick['high']:.2f}, Low={nowick['low']:.2f}")

        # STEP 5: Find LIQ #2 (break consolidation high)
        liq2 = self._find_liq2_after_nowick(df, consol, nowick)

        if liq2 is None:
            if verbose:
                print(f"        ✗ No LIQ #2 found")
            return None

        if verbose:
            print(f"        ✓ LIQ #2 @ {liq2['idx']}: {liq2['price']:.2f}")

        # STEP 6: Find entry trigger (close below no-wick low)
        entry_trigger = self._find_entry_trigger(df, liq2, nowick)

        if entry_trigger is None:
            if verbose:
                print(f"          ✗ No entry trigger")
            return None

        if verbose:
            print(f"          ✓ Entry trigger @ {entry_trigger['trigger_idx']}")

        # STEP 7: Calculate entry, SL, TP
        entry_price = entry_trigger['entry_price']
        sl_price = self._calculate_sl(df, liq2)
        tp_price = lse_low

        # Build complete setup
        setup = {
            # LSE levels
            'lse_high': lse_high,
            'lse_low': lse_low,

            # LIQ #1
            'liq1_idx': liq1['idx'],
            'liq1_price': liq1['price'],
            'liq1_time': liq1['time'],

            # Consolidation
            'consol_start_idx': consol['start_idx'],
            'consol_end_idx': consol['end_idx'],
            'consol_high': consol['high'],
            'consol_low': consol['low'],
            'consol_range': consol['range'],
            'consol_quality_score': consol.get('quality_score', 0),

            # No-wick
            'nowick_idx': nowick['idx'],
            'nowick_high': nowick['high'],
            'nowick_low': nowick['low'],
            'nowick_time': nowick['time'],

            # LIQ #2
            'liq2_idx': liq2['idx'],
            'liq2_price': liq2['price'],
            'liq2_time': liq2['time'],

            # Entry
            'entry_trigger_idx': entry_trigger['trigger_idx'],
            'entry_idx': entry_trigger['entry_idx'],
            'entry_price': entry_price,
            'entry_time': entry_trigger['entry_time'],

            # SL/TP
            'sl_price': sl_price,
            'tp_price': tp_price,

            # Metrics
            'risk_pips': abs(entry_price - sl_price),
            'reward_pips': abs(entry_price - tp_price),
            'risk_reward_ratio': abs(entry_price - tp_price) / abs(entry_price - sl_price) if abs(entry_price - sl_price) > 0 else 0,

            # Direction
            'direction': 'SHORT'
        }

        return setup

    def _find_consolidation_after_liq1(
        self,
        df: pd.DataFrame,
        liq1_idx: int
    ) -> Optional[Dict]:
        """
        Find consolidation after LIQ #1.

        Must be SIDEWAYS oscillation (not diagonal trend).
        """
        # Start searching 1 candle after LIQ #1
        search_start = liq1_idx + 1

        if search_start >= len(df):
            return None

        # Use ConsolidationDetector
        consol = ConsolidationDetector.detect_consolidation(
            df,
            start_idx=search_start,
            atr_period=self.atr_period,
            atr_multiplier_min=self.atr_multiplier_min,
            atr_multiplier_max=self.atr_multiplier_max,
            min_duration=self.consol_min_duration,
            max_duration=self.consol_max_duration
            # Note: ConsolidationDetector already does trend rejection via slope/R² checks
        )

        return consol

    def _find_nowick_in_consolidation(
        self,
        df: pd.DataFrame,
        consol: Dict
    ) -> Optional[Dict]:
        """
        Find no-wick candle in consolidation.

        Rules:
        - Must be BULLISH (Close > Open) for SHORT setup
        - Upper wick < threshold (percentile-based)
        - Timing: Prefer LAST valid candidate (closest to LIQ #2)

        Returns:
            Dict with {idx, high, low, time} or None
        """
        consol_start = consol['start_idx']
        consol_end = consol['end_idx']

        candidates = []

        for i in range(consol_start, consol_end + 1):
            candle = df.iloc[i]

            # Check if bullish (for SHORT setup)
            if candle['Close'] <= candle['Open']:
                continue

            # Use NoWickDetector
            is_nowick = NoWickDetector.is_no_wick_candle(
                candle, df, i,
                direction='bullish',
                percentile=self.nowick_percentile
            )

            if is_nowick:
                candidates.append({
                    'idx': i,
                    'high': candle['High'],
                    'low': candle['Low'],
                    'time': candle.name
                })

        if len(candidates) == 0:
            return None

        # Return LAST candidate (closest to LIQ #2)
        return candidates[-1]

    def _find_liq2_after_nowick(
        self,
        df: pd.DataFrame,
        consol: Dict,
        nowick: Dict
    ) -> Optional[Dict]:
        """
        Find LIQ #2 (break consolidation high) after no-wick.

        Must occur AFTER no-wick candle.
        """
        nowick_idx = nowick['idx']
        consol_high = consol['high']

        # Search from nowick+1 to end of consolidation + some buffer
        search_start = nowick_idx + 1
        search_end = min(consol['end_idx'] + 10, len(df) - 1)

        for i in range(search_start, search_end + 1):
            candle = df.iloc[i]

            if candle['High'] > consol_high:
                # Detect liquidity grab
                liq_result = LiquidityDetector.detect_liquidity_grab(
                    df, i, consol_high, direction='up'
                )

                if liq_result['detected']:
                    return {
                        'idx': i,
                        'price': candle['High'],
                        'level': consol_high,
                        'time': candle.name
                    }

        return None

    def _find_entry_trigger(
        self,
        df: pd.DataFrame,
        liq2: Dict,
        nowick: Dict
    ) -> Optional[Dict]:
        """
        Find entry trigger: candle that CLOSES below no-wick low.

        Critical rules:
        - Search AFTER LIQ #2
        - Trigger = candle that CLOSES below no-wick low
        - Entry = NEXT candle's OPEN
        - Invalidation: If price goes >100 pips above no-wick high
        - Max wait: 20 candles

        Returns:
            Dict with {trigger_idx, entry_idx, entry_price, entry_time}
        """
        liq2_idx = liq2['idx']
        nowick_low = nowick['low']
        nowick_high = nowick['high']

        search_start = liq2_idx
        search_end = min(liq2_idx + self.max_entry_wait_candles, len(df) - 2)

        for i in range(search_start, search_end + 1):
            candle = df.iloc[i]

            # Check invalidation: price > nowick_high + 100 pips
            if candle['High'] > nowick_high + self.max_retracement_pips:
                logger.debug(f"Setup invalidated: price {candle['High']} > nowick_high {nowick_high} + {self.max_retracement_pips}")
                return None

            # Check if closes below no-wick low
            if candle['Close'] < nowick_low:
                # TRIGGER found!
                trigger_idx = i

                # Entry = NEXT candle's OPEN
                entry_idx = i + 1

                if entry_idx >= len(df):
                    return None

                entry_candle = df.iloc[entry_idx]
                entry_price = entry_candle['Open']

                return {
                    'trigger_idx': trigger_idx,
                    'entry_idx': entry_idx,
                    'entry_price': entry_price,
                    'entry_time': entry_candle.name
                }

        return None

    def _calculate_sl(self, df: pd.DataFrame, liq2: Dict) -> float:
        """
        Calculate stop loss.

        Rules:
        - Base: LIQ #2 high + 1-2 pip buffer
        - If LIQ #2 has spike (wick > 2x body): Use body top instead

        Returns:
            SL price
        """
        liq2_idx = liq2['idx']
        candle = df.iloc[liq2_idx]

        high = candle['High']
        close = candle['Close']
        open_price = candle['Open']

        body = abs(close - open_price)
        upper_wick = high - max(close, open_price)

        # Check for spike
        if upper_wick > 2 * body and body > 0:
            # Spike detected - use body top
            sl_price = max(close, open_price) + 2  # +2 pips buffer
            logger.debug(f"LIQ #2 spike detected (wick {upper_wick:.1f} > 2*body {body:.1f}), using body top SL")
        else:
            # Normal - use actual high
            sl_price = high + 2  # +2 pips buffer

        return sl_price

    def __repr__(self) -> str:
        return (f"SetupFinder(consol_duration={self.consol_min_duration}-{self.consol_max_duration}, "
                f"atr_mult={self.atr_multiplier_min}-{self.atr_multiplier_max})")


if __name__ == "__main__":
    print("5/1 SLOB Setup Finder")
    print("Use: finder = SetupFinder(); setups = finder.find_setups(df)")
