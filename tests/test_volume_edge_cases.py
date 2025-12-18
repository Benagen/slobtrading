"""
Test Volume Edge Cases för LiquidityDetector
"""

import sys
import pandas as pd
import numpy as np

sys.path.insert(0, '/Users/erikaberg/Downloads/slobprototype')

from slob.patterns.liquidity_detector import LiquidityDetector


def test_volume_zero():
    """Test: Volume = 0 för LIQ #1 candle"""

    # Create sample data
    dates = pd.date_range('2024-01-15 15:00', periods=60, freq='1min')
    df = pd.DataFrame({
        'Open': 16000.0,
        'High': 16005.0,
        'Low': 15995.0,
        'Close': 16000.0,
        'Volume': 1000
    }, index=dates)

    # LIQ #1 @ index 30 with ZERO volume
    df.iloc[30, df.columns.get_loc('High')] = 16110  # Breaks level 16100
    df.iloc[30, df.columns.get_loc('Volume')] = 0  # ← ZERO VOLUME

    # Test detection
    result = LiquidityDetector.detect_liquidity_grab(
        df, idx=30, level=16100.0, direction='up'
    )

    print("="*80)
    print("TEST 1: Volume = 0")
    print("="*80)
    print(f"Result: {result}")

    if result:
        print(f"  Detected: {result['detected']}")
        print(f"  Score: {result['score']:.2f}")
        print(f"  Volume spike: {result['volume_spike']}")
        print(f"  Has rejection: {result['has_rejection']}")
        print(f"  Wick reversal: {result['wick_reversal']}")
        print(f"  Volume ratio: {result['signals']['volume_ratio']:.2f}")
    else:
        print("  No liquidity grab detected")

    print()


def test_volume_nan():
    """Test: Volume = NaN för LIQ #1 candle"""

    dates = pd.date_range('2024-01-15 15:00', periods=60, freq='1min')
    df = pd.DataFrame({
        'Open': 16000.0,
        'High': 16005.0,
        'Low': 15995.0,
        'Close': 16000.0,
        'Volume': 1000.0
    }, index=dates)

    # LIQ #1 @ index 30 with NaN volume
    df.iloc[30, df.columns.get_loc('High')] = 16110
    df.iloc[30, df.columns.get_loc('Volume')] = np.nan  # ← NaN VOLUME

    try:
        result = LiquidityDetector.detect_liquidity_grab(
            df, idx=30, level=16100.0, direction='up'
        )

        print("="*80)
        print("TEST 2: Volume = NaN")
        print("="*80)
        print(f"Result: {result}")

        if result:
            print(f"  Detected: {result['detected']}")
            print(f"  Score: {result['score']:.2f}")
            print(f"  Volume spike: {result['volume_spike']}")
        else:
            print("  No liquidity grab detected")

        print()

    except Exception as e:
        print("="*80)
        print("TEST 2: Volume = NaN")
        print("="*80)
        print(f"ERROR: {type(e).__name__}: {e}")
        print()


def test_volume_with_rejection():
    """Test: Zero volume BUT has price rejection + wick reversal"""

    dates = pd.date_range('2024-01-15 15:00', periods=60, freq='1min')
    df = pd.DataFrame({
        'Open': 16000.0,
        'High': 16005.0,
        'Low': 15995.0,
        'Close': 16000.0,
        'Volume': 1000.0
    }, index=dates)

    # LIQ #1 @ index 30:
    # - Zero volume
    # - But has rejection (breaks level, closes back below)
    # - And has wick reversal (large upper wick)
    df.iloc[30, df.columns.get_loc('Open')] = 16095
    df.iloc[30, df.columns.get_loc('High')] = 16110  # Breaks 16100
    df.iloc[30, df.columns.get_loc('Low')] = 16092
    df.iloc[30, df.columns.get_loc('Close')] = 16098  # Closes BELOW 16100 (rejection!)
    df.iloc[30, df.columns.get_loc('Volume')] = 0  # Zero volume

    result = LiquidityDetector.detect_liquidity_grab(
        df, idx=30, level=16100.0, direction='up'
    )

    print("="*80)
    print("TEST 3: Zero Volume but Rejection + Wick Reversal")
    print("="*80)
    print(f"Candle: Open=16095, High=16110, Low=16092, Close=16098, Vol=0")
    print(f"Level: 16100")
    print()

    if result:
        print(f"  Detected: {result['detected']}")
        print(f"  Score: {result['score']:.2f}")
        print(f"    Volume spike (0.4): {result['volume_spike']}")
        print(f"    Rejection (0.3):    {result['has_rejection']}")
        print(f"    Wick reversal (0.3): {result['wick_reversal']}")
        print()
        print(f"  Interpretation:")
        if result['detected']:
            print(f"    ✅ LIQ detected DESPITE zero volume")
            print(f"    ✅ Price action (rejection + wick) sufficient for detection")
        else:
            print(f"    ❌ Score {result['score']:.2f} < 0.6 threshold")
            print(f"    ❌ Requires volume spike to reach 0.6 threshold")
    else:
        print("  No result returned (level not broken)")

    print()


def test_missing_volume_column():
    """Test: DataFrame saknar 'Volume' kolumn helt"""

    dates = pd.date_range('2024-01-15 15:00', periods=60, freq='1min')
    df = pd.DataFrame({
        'Open': 16000.0,
        'High': 16005.0,
        'Low': 15995.0,
        'Close': 16000.0
        # NO VOLUME COLUMN!
    }, index=dates)

    df.iloc[30, df.columns.get_loc('High')] = 16110

    try:
        result = LiquidityDetector.detect_liquidity_grab(
            df, idx=30, level=16100.0, direction='up'
        )

        print("="*80)
        print("TEST 4: Missing 'Volume' Column")
        print("="*80)
        print(f"Result: {result}")
        print("  ⚠️ WARNING: Function did not crash - check implementation")
        print()

    except KeyError as e:
        print("="*80)
        print("TEST 4: Missing 'Volume' Column")
        print("="*80)
        print(f"❌ KeyError as expected: {e}")
        print("  This is NOT handled gracefully")
        print("  RECOMMENDATION: Add column validation")
        print()
    except Exception as e:
        print("="*80)
        print("TEST 4: Missing 'Volume' Column")
        print("="*80)
        print(f"ERROR: {type(e).__name__}: {e}")
        print()


if __name__ == "__main__":
    test_volume_zero()
    test_volume_nan()
    test_volume_with_rejection()
    test_missing_volume_column()

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print("Volume edge cases tested:")
    print("  1. Volume = 0        → Handled (no spike, but can still detect)")
    print("  2. Volume = NaN      → Check if comparison works")
    print("  3. Zero vol + signals → Can detect with rejection+wick")
    print("  4. Missing column    → Likely KeyError (not handled)")
    print()
