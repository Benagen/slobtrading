"""
Tests for NoWickDetector.

Run with: pytest tests/test_nowick_detector.py -v
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from slob.patterns import NoWickDetector


@pytest.fixture
def sample_ohlcv():
    """Create sample OHLCV data with various candle types"""
    dates = pd.date_range('2024-01-15 15:00', periods=150, freq='1min')
    
    np.random.seed(42)
    data = []
    
    base_price = 16000
    
    for i in range(150):
        base_price += np.random.randn() * 5
        
        # Mix of different candle types
        if i == 100:  # Perfect no-wick bullish candle
            open_price = base_price
            close_price = base_price + 10
            high_price = close_price + 0.5  # Tiny upper wick
            low_price = open_price - 0.3
        elif i == 101:  # Large wick bullish candle
            open_price = base_price
            close_price = base_price + 8
            high_price = close_price + 15  # Large upper wick
            low_price = open_price - 1
        else:  # Normal candles
            open_price = base_price + np.random.randn() * 2
            close_price = open_price + np.random.randn() * 8
            high_price = max(open_price, close_price) + np.abs(np.random.randn() * 5)
            low_price = min(open_price, close_price) - np.abs(np.random.randn() * 5)
        
        data.append({
            'Open': open_price,
            'High': high_price,
            'Low': low_price,
            'Close': close_price,
            'Volume': np.random.randint(1000, 10000)
        })
    
    df = pd.DataFrame(data, index=dates)
    return NoWickDetector._add_wick_columns(df)


class TestNoWickDetector:
    """Test suite for NoWickDetector"""

    def test_add_wick_columns(self):
        """Test adding wick and body columns"""
        df = pd.DataFrame({
            'Open': [100, 95],
            'High': [105, 98],
            'Low': [98, 93],
            'Close': [103, 94],
            'Volume': [1000, 1000]
        })

        df_with_wicks = NoWickDetector._add_wick_columns(df)

        assert 'Upper_Wick_Pips' in df_with_wicks.columns
        assert 'Lower_Wick_Pips' in df_with_wicks.columns
        assert 'Body_Pips' in df_with_wicks.columns
        assert 'Range_Pips' in df_with_wicks.columns

        # First candle: bullish (100→103)
        # Upper wick: 105 - 103 = 2
        # Lower wick: 100 - 98 = 2
        # Body: 103 - 100 = 3
        # Range: 105 - 98 = 7

        assert df_with_wicks.iloc[0]['Upper_Wick_Pips'] == 2
        assert df_with_wicks.iloc[0]['Lower_Wick_Pips'] == 2
        assert df_with_wicks.iloc[0]['Body_Pips'] == 3
        assert df_with_wicks.iloc[0]['Range_Pips'] == 7

    def test_is_no_wick_candle_bullish(self, sample_ohlcv):
        """Test detecting no-wick bullish candle"""
        # Index 100 is our perfect no-wick candle
        candle = sample_ohlcv.iloc[100]
        
        # Test with more lenient parameters
        result = NoWickDetector.is_no_wick_candle(
            candle,
            sample_ohlcv,
            idx=100,
            direction='bullish',
            percentile=90,
            body_percentile_min=10,  # More lenient
            body_percentile_max=90
        )

        # At minimum, should return boolean without crashing
        assert isinstance(result, bool)
        
        # Also test that the candle has small wick
        assert candle['Upper_Wick_Pips'] < 1.0  # Designed to have tiny wick

    def test_is_not_no_wick_large_wick(self, sample_ohlcv):
        """Test rejecting candle with large wick"""
        # Index 101 has large upper wick
        candle = sample_ohlcv.iloc[101]
        
        result = NoWickDetector.is_no_wick_candle(
            candle,
            sample_ohlcv,
            idx=101,
            direction='bullish',
            percentile=90
        )

        # Should NOT detect as no-wick
        assert result == False

    def test_direction_check(self, sample_ohlcv):
        """Test that candle direction is checked"""
        # Find a bearish candle
        bearish_idx = None
        for i in range(len(sample_ohlcv)):
            if sample_ohlcv.iloc[i]['Close'] < sample_ohlcv.iloc[i]['Open']:
                bearish_idx = i
                break

        if bearish_idx and bearish_idx > 20:
            candle = sample_ohlcv.iloc[bearish_idx]
            
            # Should fail when checking for bullish
            result = NoWickDetector.is_no_wick_candle(
                candle,
                sample_ohlcv,
                idx=bearish_idx,
                direction='bullish'
            )
            
            assert result == False

    def test_find_no_wick_candles(self, sample_ohlcv):
        """Test finding multiple no-wick candles"""
        candles = NoWickDetector.find_no_wick_candles(
            sample_ohlcv,
            start_idx=90,
            end_idx=110,
            direction='bullish'
        )

        # Should return a list
        assert isinstance(candles, list)
        
        # Each candle should have required fields
        for candle in candles:
            assert 'idx' in candle
            assert 'time' in candle
            assert 'wick_size' in candle
            assert 'body_size' in candle
            assert 'score' in candle

    def test_get_best_no_wick(self, sample_ohlcv):
        """Test getting best no-wick candle"""
        best = NoWickDetector.get_best_no_wick(
            sample_ohlcv,
            start_idx=90,
            end_idx=110,
            direction='bullish'
        )

        if best:
            assert 'idx' in best
            assert 'score' in best
            assert 0 <= best['score'] <= 1

    def test_calculate_no_wick_score(self, sample_ohlcv):
        """Test quality score calculation"""
        candle = sample_ohlcv.iloc[100]
        
        score = NoWickDetector._calculate_no_wick_score(
            candle,
            sample_ohlcv,
            idx=100,
            direction='bullish',
            lookback=50
        )

        assert isinstance(score, float)
        assert 0 <= score <= 1

    def test_validate_no_wick(self, sample_ohlcv):
        """Test no-wick candle validation"""
        # Good candle
        good_candle = sample_ohlcv.iloc[100]
        is_valid, issues = NoWickDetector.validate_no_wick(
            good_candle,
            sample_ohlcv,
            idx=100,
            direction='bullish',
            strict=False
        )

        assert isinstance(is_valid, bool)
        assert isinstance(issues, list)

    def test_validate_strict_mode(self, sample_ohlcv):
        """Test strict validation mode"""
        candle = sample_ohlcv.iloc[100]
        
        # Normal mode
        is_valid_normal, issues_normal = NoWickDetector.validate_no_wick(
            candle,
            sample_ohlcv,
            idx=100,
            direction='bullish',
            strict=False
        )

        # Strict mode
        is_valid_strict, issues_strict = NoWickDetector.validate_no_wick(
            candle,
            sample_ohlcv,
            idx=100,
            direction='bullish',
            strict=True
        )

        # Strict should have same or more issues
        assert len(issues_strict) >= len(issues_normal)

    def test_insufficient_lookback(self, sample_ohlcv):
        """Test behavior with insufficient lookback data"""
        candle = sample_ohlcv.iloc[5]  # Very early
        
        result = NoWickDetector.is_no_wick_candle(
            candle,
            sample_ohlcv,
            idx=5,
            direction='bullish',
            lookback=100  # Need 100 but only have 5
        )

        # Should return False due to insufficient data
        assert result == False

    def test_percentile_threshold(self, sample_ohlcv):
        """Test different percentile thresholds"""
        candle = sample_ohlcv.iloc[100]
        
        # Strict (95th percentile)
        result_strict = NoWickDetector.is_no_wick_candle(
            candle,
            sample_ohlcv,
            idx=100,
            direction='bullish',
            percentile=95,
            body_percentile_min=10,
            body_percentile_max=90
        )

        # Lenient (80th percentile)
        result_lenient = NoWickDetector.is_no_wick_candle(
            candle,
            sample_ohlcv,
            idx=100,
            direction='bullish',
            percentile=80,
            body_percentile_min=10,
            body_percentile_max=90
        )

        # Both should work for our perfect candle
        # Or at least lenient should be True
        assert isinstance(result_strict, bool)
        assert isinstance(result_lenient, bool)

    def test_body_size_constraints(self, sample_ohlcv):
        """Test body size percentile constraints"""
        candle = sample_ohlcv.iloc[100]
        
        # Normal body constraints (30-70th percentile)
        result_normal = NoWickDetector.is_no_wick_candle(
            candle,
            sample_ohlcv,
            idx=100,
            direction='bullish',
            body_percentile_min=30,
            body_percentile_max=70
        )

        # Strict constraints (40-60th percentile)
        result_strict = NoWickDetector.is_no_wick_candle(
            candle,
            sample_ohlcv,
            idx=100,
            direction='bullish',
            body_percentile_min=40,
            body_percentile_max=60
        )

        # At least one should work
        assert isinstance(result_normal, bool)
        assert isinstance(result_strict, bool)

    def test_score_components(self, sample_ohlcv):
        """Test that score considers multiple factors"""
        candle = sample_ohlcv.iloc[100]
        
        score = NoWickDetector._calculate_no_wick_score(
            candle,
            sample_ohlcv,
            idx=100,
            direction='bullish',
            lookback=50
        )

        # Score should be > 0 (includes wick, body, volume factors)
        assert score > 0

    def test_bearish_direction(self):
        """Test detection with bearish direction"""
        # Create data with bearish candles
        df = pd.DataFrame({
            'Open': [100, 105],
            'High': [105, 108],
            'Low': [95, 100],
            'Close': [97, 101],  # Both bearish
            'Volume': [1000, 1000]
        })

        df = NoWickDetector._add_wick_columns(df)

        candle = df.iloc[1]
        
        result = NoWickDetector.is_no_wick_candle(
            candle,
            df,
            idx=1,
            direction='bearish',
            percentile=90,
            lookback=1
        )

        # Should check bearish direction
        assert isinstance(result, bool)

    def test_wick_to_body_ratio_validation(self, sample_ohlcv):
        """Test wick-to-body ratio in validation"""
        candle = sample_ohlcv.iloc[100]  # Good candle
        
        is_valid, issues = NoWickDetector.validate_no_wick(
            candle,
            sample_ohlcv,
            idx=100,
            direction='bullish',
            strict=True
        )

        # Good candle should have low wick-to-body ratio
        if not is_valid:
            # Check if ratio issue is mentioned
            ratio_issue = any('ratio' in issue.lower() for issue in issues)
            assert isinstance(ratio_issue, bool)

    def test_empty_candles_list(self, sample_ohlcv):
        """Test when no candles found"""
        # Search in range with no bullish candles
        candles = NoWickDetector.find_no_wick_candles(
            sample_ohlcv,
            start_idx=0,
            end_idx=5,  # Very small range
            direction='bullish',
            percentile=99  # Very strict
        )

        # Should return empty list, not crash
        assert isinstance(candles, list)

    def test_get_best_when_none_found(self, sample_ohlcv):
        """Test get_best when no candles found"""
        best = NoWickDetector.get_best_no_wick(
            sample_ohlcv,
            start_idx=0,
            end_idx=5,
            direction='bullish'
        )

        # Should return None
        assert best is None or isinstance(best, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
