"""
5/1 SLOB Setup Finder - Orchestration Layer (WHITEPAPER-COMPLIANT)

Implements the EXACT 5/1 SLOB strategy flow per whitepaper:
1. LSE Session (09:00-15:30) → Establish LSE High/Low
2. LIQ #1 (NYSE session, >15:30) → Break LSE High/Low with volume
3. Consolidation (3-25 min FLEXIBLE) → Clear High/Low formation (2+ touches)
4. Sweep + No-Wick (COMBINED) → Same candle sweeps level AND is no-wick
   - No-wick: Body ≥95% of range, Wick ≤5%, Size 0.03-0.15% of price
   - SHORT: Sweep consol HIGH with bullish no-wick
   - LONG: Sweep consol LOW with bearish no-wick
5. Entry Trigger → Candle closes below/above no-wick OPEN (+ direction check)
6. Entry Execution → Next candle's OPEN price
7. SL/TP → Sweep high/low / LSE Low/High

Critical considerations:
- Bidirectional: SHORT and LONG setups
- No look-ahead bias (incremental discovery)
- NYSE session timing (AFTER 15:30 for LIQ #1)
- Whitepaper-compliant ratios and timing
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
        consol_min_duration: int = 3,
        consol_max_duration: int = 25,
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

        # Group by date using groupby to preserve DatetimeIndex
        # Convert to UTC first to handle DST transitions
        df_work = df.copy()
        if hasattr(df_work.index, 'tz') and df_work.index.tz is not None:
            df_work.index = df_work.index.tz_convert('UTC')

        # Group by date (floor to day)
        for date, day_df in df_work.groupby(df_work.index.floor('D')):
            if verbose:
                print(f"\nProcessing {date.date()}...")

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

        # STEP 2: Find LIQ #1 (NYSE breaks LSE High OR LSE Low - BIDIRECTIONAL)
        liq1_results = self._find_liq1_candidates(df, lse_high, lse_low, lse_end_idx)

        if len(liq1_results) == 0:
            if verbose:
                print(f"  ✗ No LIQ #1 found (checked both up and down)")
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
        # Index should already be DatetimeIndex from data loading
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
        lse_low: float,
        lse_end_idx: int
    ) -> List[Dict]:
        """
        Find LIQ #1 candidates (NYSE breaks LSE High OR LSE Low) - BIDIRECTIONAL.

        Critical rules:
        - MUST be in NYSE session (>= 15:30)
        - Price breaks ABOVE LSE High (SHORT setup) OR BELOW LSE Low (LONG setup)
        - Rejection preferred

        Returns:
            List of LIQ #1 dicts with {idx, price, level, confidence, direction}
        """
        candidates = []

        # Search ONLY in NYSE session (after LSE close)
        nyse_start_idx = lse_end_idx + 1

        if nyse_start_idx >= len(df):
            return []

        # Search for breaks in BOTH directions
        for i in range(nyse_start_idx, len(df)):
            candle = df.iloc[i]

            # Check if in NYSE session (>= 15:30)
            if candle.name.time() < self.nyse_open:
                continue

            # Check UPWARD break (SHORT setup)
            if candle['High'] > lse_high:
                liq_result = LiquidityDetector.detect_liquidity_grab(
                    df, i, lse_high, direction='up'
                )

                if liq_result and liq_result['detected']:
                    candidates.append({
                        'idx': i,
                        'price': candle['High'],
                        'level': lse_high,
                        'confidence': liq_result['score'],
                        'time': candle.name,
                        'direction': 'short'  # Break above = SHORT setup
                    })
                    # Take first valid LIQ #1 (in either direction)
                    break

            # Check DOWNWARD break (LONG setup)
            if candle['Low'] < lse_low:
                liq_result = LiquidityDetector.detect_liquidity_grab(
                    df, i, lse_low, direction='down'
                )

                if liq_result and liq_result['detected']:
                    candidates.append({
                        'idx': i,
                        'price': candle['Low'],
                        'level': lse_low,
                        'confidence': liq_result['score'],
                        'time': candle.name,
                        'direction': 'long'  # Break below = LONG setup
                    })
                    # Take first valid LIQ #1 (in either direction)
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
        Try to build complete setup from LIQ #1 - BIDIRECTIONAL (WHITEPAPER-COMPLIANT).

        Flow (UPDATED per whitepaper):
        1. Find consolidation after LIQ #1
        2. Detect sweep + no-wick (COMBINED - same candle sweeps AND is no-wick)
        3. Find entry trigger (close below/above no-wick OPEN)
        4. Calculate entry, SL, TP (direction-aware)

        Returns:
            Complete setup dict or None if setup invalid
        """
        liq1_idx = liq1['idx']
        direction = liq1['direction']  # 'short' or 'long'

        # STEP 3: Find consolidation after LIQ #1
        consol = self._find_consolidation_after_liq1(df, liq1_idx, direction)

        if consol is None:
            if verbose:
                print(f"    ✗ No valid consolidation after LIQ #1 @ {liq1['time']}")
            return None

        if verbose:
            print(f"    ✓ Consolidation found: {consol['start_idx']} to {consol['end_idx']}")

        # STEP 4: Detect sweep + no-wick (COMBINED - whitepaper spec)
        # The no-wick appears AT the sweep, not before or after
        sweep_nowick = self._detect_liq_sweep_with_nowick(df, consol, direction)

        if sweep_nowick is None:
            if verbose:
                print(f"      ✗ No valid sweep+no-wick for {direction} setup")
            return None

        if verbose:
            print(f"      ✓ Sweep+No-wick @ {sweep_nowick['idx']}: Level={sweep_nowick['sweep_level']:.2f}")

        # Extract data for backward compatibility
        liq2 = {
            'idx': sweep_nowick['sweep_idx'],
            'price': sweep_nowick['sweep_price'],
            'level': sweep_nowick['sweep_level'],
            'time': sweep_nowick['time']
        }

        nowick = {
            'idx': sweep_nowick['nowick_idx'],
            'open': sweep_nowick['nowick_open'],
            'high': sweep_nowick['nowick_high'],
            'low': sweep_nowick['nowick_low'],
            'time': sweep_nowick['time']
        }

        # STEP 5: Find entry trigger (direction-aware: close below/above no-wick OPEN)
        entry_trigger = self._find_entry_trigger(df, liq2, nowick, direction)

        if entry_trigger is None:
            if verbose:
                print(f"          ✗ No entry trigger for {direction} setup")
            return None

        if verbose:
            print(f"          ✓ Entry trigger @ {entry_trigger['trigger_idx']}")

        # STEP 7: Calculate entry, SL, TP (direction-aware)
        entry_price = entry_trigger['entry_price']

        if direction == 'short':
            # SHORT: SL above (at LIQ #2 high + buffer), TP below (at LSE Low)
            sl_price = self._calculate_sl(df, liq2, direction)
            tp_price = lse_low
        else:  # direction == 'long'
            # LONG: SL below (at LIQ #2 low - buffer), TP above (at LSE High)
            sl_price = self._calculate_sl(df, liq2, direction)
            tp_price = lse_high

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
            'direction': direction.upper()  # 'SHORT' or 'LONG'
        }

        return setup

    def _find_consolidation_after_liq1(
        self,
        df: pd.DataFrame,
        liq1_idx: int,
        direction: str
    ) -> Optional[Dict]:
        """
        Find consolidation after LIQ #1.

        Must be SIDEWAYS oscillation (not diagonal trend).
        Consolidation detection logic is same for both SHORT and LONG.
        """
        # Start searching 1 candle after LIQ #1
        search_start = liq1_idx + 1

        if search_start >= len(df):
            return None

        # Use ConsolidationDetector (same logic for both directions)
        consol = ConsolidationDetector.detect_consolidation(
            df,
            start_idx=search_start,
            atr_period=self.atr_period,
            atr_multiplier_min=self.atr_multiplier_min,
            atr_multiplier_max=self.atr_multiplier_max,
            min_duration=self.consol_min_duration,
            max_duration=self.consol_max_duration,
            lookback_for_atr=30  # FIX: Reduce from default 100 to work with day-level data
            # Note: ConsolidationDetector already does trend rejection via slope/R² checks
        )

        return consol

    def _detect_liq_sweep_with_nowick(
        self,
        df: pd.DataFrame,
        consol: Dict,
        direction: str
    ) -> Optional[Dict]:
        """
        Detect liquidity sweep WITH no-wick candle - WHITEPAPER COMBINED STAGE.

        From whitepaper: No-wick appears AT the sweep, not before or after.
        The sweep and no-wick are the SAME EVENT, not sequential.

        SHORT setup:
            - Sweep consolidation HIGH (final push up)
            - The sweeping candle must be a bullish no-wick (close > open, 95%/5% ratios)

        LONG setup:
            - Sweep consolidation LOW (final push down)
            - The sweeping candle must be a bearish no-wick (close < open, 95%/5% ratios)

        Search window: Consolidation end + 40-50 candles (total trade ~60 min)

        Returns:
            Combined dict with sweep and no-wick info, or None
        """
        consol_start = consol['start_idx']
        consol_end = consol['end_idx']
        consol_high = consol['high']
        consol_low = consol['low']

        # FINAL INTERPRETATION: No-wick candle IS the breakout/sweep candle
        # Whitepaper: "no-wick appears AT the sweep" = they're the SAME candle
        # Search AFTER consolidation ends for breakout candle that is ALSO a no-wick

        search_start = consol_end  # Start right after consolidation
        search_end = min(consol_end + 40, len(df) - 1)

        print(f"    [SWEEP+NOWICK] Searching for breakout no-wick from idx {search_start} to {search_end}")

        sweep_count = 0
        for i in range(search_start, search_end + 1):
            candle = df.iloc[i]

            if direction == 'short':
                # SHORT: Break ABOVE consolidation HIGH with bullish no-wick
                if candle['High'] > consol_high:
                    sweep_count += 1
                    print(f"    [SWEEP] Candle {i} breaks HIGH: {candle['High']:.2f} > {consol_high:.2f}, bullish={candle['Close']>candle['Open']}")

                    # Check if THIS breakout candle is ALSO a bullish no-wick
                    if candle['Close'] > candle['Open']:
                        is_nowick = NoWickDetector.is_no_wick_candle(
                            candle, df, i,
                            direction='bullish'
                        )

                        if is_nowick:
                            # Verify with LiquidityDetector for quality score
                            liq_result = LiquidityDetector.detect_liquidity_grab(
                                df, i, consol_high, direction='up'
                            )

                            if liq_result and liq_result['detected']:
                                print(f"    [SWEEP+NOWICK] ✅ Breakout candle IS no-wick at idx {i}")
                                # Return combined result (same candle is both sweep and no-wick)
                                return {
                                    'idx': i,
                                    'sweep_idx': i,
                                    'sweep_level': consol_high,
                                    'sweep_price': candle['High'],
                                    'nowick_idx': i,  # SAME candle
                                    'nowick_open': candle['Open'],
                                    'nowick_high': candle['High'],
                                    'nowick_low': candle['Low'],
                                    'time': candle.name,
                                    'liq_score': liq_result['score']
                                }

            else:  # direction == 'long'
                # LONG: Break BELOW consolidation LOW with bearish no-wick
                if candle['Low'] < consol_low:
                    sweep_count += 1
                    print(f"    [SWEEP] Candle {i} breaks LOW: {candle['Low']:.2f} < {consol_low:.2f}, bearish={candle['Close']<candle['Open']}")

                    # Check if THIS breakout candle is ALSO a bearish no-wick
                    if candle['Close'] < candle['Open']:
                        is_nowick = NoWickDetector.is_no_wick_candle(
                            candle, df, i,
                            direction='bearish'
                        )

                        if is_nowick:
                            # Verify with LiquidityDetector for quality score
                            liq_result = LiquidityDetector.detect_liquidity_grab(
                                df, i, consol_low, direction='down'
                            )

                            if liq_result and liq_result['detected']:
                                print(f"    [SWEEP+NOWICK] ✅ Breakout candle IS no-wick at idx {i}")
                                # Return combined result (same candle is both sweep and no-wick)
                                return {
                                    'idx': i,
                                    'sweep_idx': i,
                                    'sweep_level': consol_low,
                                    'sweep_price': candle['Low'],
                                    'nowick_idx': i,  # SAME candle
                                    'nowick_open': candle['Open'],
                                    'nowick_high': candle['High'],
                                    'nowick_low': candle['Low'],
                                    'time': candle.name,
                                    'liq_score': liq_result['score']
                                }

        print(f"    [SWEEP+NOWICK] No breakout no-wick found (breakouts checked={sweep_count})")
        return None

    def _find_entry_trigger(
        self,
        df: pd.DataFrame,
        liq2: Dict,
        nowick: Dict,
        direction: str
    ) -> Optional[Dict]:
        """
        Find entry trigger - BIDIRECTIONAL.

        SHORT: Candle that CLOSES below no-wick low
        LONG: Candle that CLOSES above no-wick high

        Critical rules:
        - Search AFTER LIQ #2
        - Entry = NEXT candle's OPEN
        - Invalidation: If price moves too far against direction
        - Max wait: 20 candles

        Returns:
            Dict with {trigger_idx, entry_idx, entry_price, entry_time}
        """
        liq2_idx = liq2['idx']
        nowick_low = nowick['low']
        nowick_high = nowick['high']
        nowick_open = nowick['open']  # WHITEPAPER FIX: Use OPEN for entry trigger

        search_start = liq2_idx
        search_end = min(liq2_idx + self.max_entry_wait_candles, len(df) - 2)

        for i in range(search_start, search_end + 1):
            candle = df.iloc[i]

            if direction == 'short':
                # SHORT: Check invalidation (price goes too high)
                if candle['High'] > nowick_high + self.max_retracement_pips:
                    logger.debug(f"SHORT setup invalidated: price {candle['High']} > nowick_high {nowick_high} + {self.max_retracement_pips}")
                    return None

                # SHORT: Trigger = close below no-wick OPEN + bearish candle (whitepaper spec)
                if candle['Close'] < nowick_open:
                    # Also verify BEARISH movement (genuine reversal)
                    if candle['Close'] < candle['Open']:  # Bearish candle
                        trigger_idx = i
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

            else:  # direction == 'long'
                # LONG: Check invalidation (price goes too low)
                if candle['Low'] < nowick_low - self.max_retracement_pips:
                    logger.debug(f"LONG setup invalidated: price {candle['Low']} < nowick_low {nowick_low} - {self.max_retracement_pips}")
                    return None

                # LONG: Trigger = close above no-wick OPEN + bullish candle (whitepaper spec)
                if candle['Close'] > nowick_open:
                    # Also verify BULLISH movement (genuine reversal)
                    if candle['Close'] > candle['Open']:  # Bullish candle
                        trigger_idx = i
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

    def _calculate_sl(self, df: pd.DataFrame, liq2: Dict, direction: str) -> float:
        """
        Calculate stop loss - BIDIRECTIONAL.

        SHORT: SL above LIQ #2 high + buffer
        LONG: SL below LIQ #2 low - buffer

        Rules:
        - If spike detected (wick > 2x body): Use body extreme instead
        - Buffer: 1-2 pips

        Returns:
            SL price
        """
        liq2_idx = liq2['idx']
        candle = df.iloc[liq2_idx]

        high = candle['High']
        low = candle['Low']
        close = candle['Close']
        open_price = candle['Open']

        body = abs(close - open_price)

        if direction == 'short':
            # SHORT: SL above LIQ #2
            upper_wick = high - max(close, open_price)

            # Check for spike
            if upper_wick > 2 * body and body > 0:
                # Spike detected - use body top
                sl_price = max(close, open_price) + 2  # +2 pips buffer
                logger.debug(f"SHORT LIQ #2 spike detected (wick {upper_wick:.1f} > 2*body {body:.1f}), using body top SL")
            else:
                # Normal - use actual high
                sl_price = high + 2  # +2 pips buffer

        else:  # direction == 'long'
            # LONG: SL below LIQ #2
            lower_wick = min(close, open_price) - low

            # Check for spike
            if lower_wick > 2 * body and body > 0:
                # Spike detected - use body bottom
                sl_price = min(close, open_price) - 2  # -2 pips buffer
                logger.debug(f"LONG LIQ #2 spike detected (wick {lower_wick:.1f} > 2*body {body:.1f}), using body bottom SL")
            else:
                # Normal - use actual low
                sl_price = low - 2  # -2 pips buffer

        return sl_price

    def __repr__(self) -> str:
        return (f"SetupFinder(consol_duration={self.consol_min_duration}-{self.consol_max_duration}, "
                f"atr_mult={self.atr_multiplier_min}-{self.atr_multiplier_max})")


if __name__ == "__main__":
    print("5/1 SLOB Setup Finder")
    print("Use: finder = SetupFinder(); setups = finder.find_setups(df)")
