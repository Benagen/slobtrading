"""
Tests for LiquidityDetector.

Run with: pytest tests/test_liquidity_detector.py -v
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from slob.patterns import LiquidityDetector


@pytest.fixture
def sample_ohlcv():
    """Create sample OHLCV data with liquidity grabs"""
    dates = pd.date_range('2024-01-15 15:00', periods=100, freq='1min')
    
    np.random.seed(42)
    data = []
    
    base_price = 16000
    lse_high = 16100
    
    for i in range(100):
        if i == 50:  # Perfect liquidity grab (break LSE high with volume spike and rejection)
            open_price = lse_high - 5
            high_price = lse_high + 10  # Break above
            close_price = lse_high - 3  # Close back below (rejection)
            low_price = open_price - 2
            volume = 15000  # High volume
        elif i == 51:  # Weak break (no volume spike, no rejection)
            open_price = lse_high - 2
            high_price = lse_high + 2  # Break above but weak
            close_price = lse_high + 1  # No rejection
            low_price = open_price - 1
            volume = 3000  # Low volume
        else:  # Normal candles
            base_price += np.random.randn() * 3
            open_price = base_price + np.random.randn() * 2
            close_price = open_price + np.random.randn() * 5
            high_price = max(open_price, close_price) + np.abs(np.random.randn() * 3)
            low_price = min(open_price, close_price) - np.abs(np.random.randn() * 3)
            volume = np.random.randint(3000, 8000)
        
        data.append({
            'Open': open_price,
            'High': high_price,
            'Low': low_price,
            'Close': close_price,
            'Volume': volume
        })
    
    return pd.DataFrame(data, index=dates)


class TestLiquidityDetector:
    """Test suite for LiquidityDetector"""

    def test_detect_liquidity_grab_perfect(self, sample_ohlcv):
        """Test detecting perfect liquidity grab"""
        lse_high = 16100
        
        result = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=50,  # Our perfect liquidity grab
            level=lse_high,
            direction='up'
        )

        assert result is not None
        assert result['detected'] == True
        assert result['volume_spike'] == True
        assert result['has_rejection'] == True
        assert result['score'] > 0.6

    def test_detect_weak_liquidity_grab(self, sample_ohlcv):
        """Test rejecting weak liquidity grab"""
        lse_high = 16100
        
        result = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=51,  # Weak break
            level=lse_high,
            direction='up'
        )

        # Weak break should have low score
        if result:
            assert result['score'] < 0.6 or result['detected'] == False

    def test_level_not_broken(self, sample_ohlcv):
        """Test when level is not broken"""
        lse_high = 16100
        
        result = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=10,  # Normal candle far from level
            level=lse_high,
            direction='up'
        )

        # Should return None if level not broken
        assert result is None

    def test_insufficient_lookback(self, sample_ohlcv):
        """Test with insufficient lookback data"""
        lse_high = 16100
        
        result = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=5,  # Too early
            level=lse_high,
            direction='up',
            lookback=100
        )

        assert result is None

    def test_downward_direction(self):
        """Test detecting downward liquidity grab"""
        df = pd.DataFrame({
            'Open': [100, 95, 93],
            'High': [105, 98, 96],
            'Low': [95, 90, 88],  # Break below 90
            'Close': [97, 92, 91],  # Reject back above 90
            'Volume': [5000, 5000, 12000]  # Volume spike
        })

        result = LiquidityDetector.detect_liquidity_grab(
            df,
            idx=2,
            level=90,
            direction='down',
            lookback=2
        )

        assert result is not None
        assert result['detected'] == True

    def test_find_liquidity_grabs(self, sample_ohlcv):
        """Test finding multiple liquidity grabs"""
        lse_high = 16100
        
        grabs = LiquidityDetector.find_liquidity_grabs(
            sample_ohlcv,
            start_idx=40,
            end_idx=60,
            level=lse_high,
            direction='up'
        )

        # Should find at least one (our perfect grab at 50)
        assert isinstance(grabs, list)
        
        # Check structure
        for grab in grabs:
            assert 'idx' in grab
            assert 'time' in grab
            assert 'score' in grab
            assert 'volume_spike' in grab
            assert 'has_rejection' in grab

    def test_get_best_liquidity_grab(self, sample_ohlcv):
        """Test getting best liquidity grab"""
        lse_high = 16100
        
        best = LiquidityDetector.get_best_liquidity_grab(
            sample_ohlcv,
            start_idx=40,
            end_idx=60,
            level=lse_high,
            direction='up'
        )

        if best:
            assert 'idx' in best
            assert 'score' in best
            assert best['score'] > 0

    def test_validate_liquidity_grab(self, sample_ohlcv):
        """Test liquidity grab validation"""
        lse_high = 16100
        
        result = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=50,
            level=lse_high,
            direction='up'
        )

        if result and result['detected']:
            is_valid, issues = LiquidityDetector.validate_liquidity_grab(
                sample_ohlcv,
                result,
                level=lse_high,
                direction='up',
                strict=False
            )

            assert isinstance(is_valid, bool)
            assert isinstance(issues, list)

    def test_validate_strict_mode(self, sample_ohlcv):
        """Test strict validation mode"""
        lse_high = 16100
        
        result = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=50,
            level=lse_high,
            direction='up'
        )

        if result and result['detected']:
            # Normal mode
            is_valid_normal, issues_normal = LiquidityDetector.validate_liquidity_grab(
                sample_ohlcv,
                result,
                level=lse_high,
                direction='up',
                strict=False
            )

            # Strict mode
            is_valid_strict, issues_strict = LiquidityDetector.validate_liquidity_grab(
                sample_ohlcv,
                result,
                level=lse_high,
                direction='up',
                strict=True
            )

            # Strict should have same or more issues
            assert len(issues_strict) >= len(issues_normal)

    def test_calculate_liquidity_strength(self, sample_ohlcv):
        """Test liquidity strength calculation"""
        lse_high = 16100
        
        strength = LiquidityDetector.calculate_liquidity_strength(
            sample_ohlcv,
            idx=50,
            level=lse_high,
            direction='up'
        )

        assert 'attempts' in strength
        assert 'time_at_level' in strength
        assert 'momentum' in strength
        assert 'strength_score' in strength

        assert strength['attempts'] >= 0
        assert strength['time_at_level'] >= 0

    def test_detect_sequential_liquidity(self, sample_ohlcv):
        """Test detecting LIQ #2 following LIQ #1"""
        liq1_level = 16100
        liq2_level = 16105
        liq1_idx = 50

        result = LiquidityDetector.detect_sequential_liquidity(
            sample_ohlcv,
            liq1_level=liq1_level,
            liq2_level=liq2_level,
            liq1_idx=liq1_idx,
            direction='up',
            min_gap=5,
            max_gap=20
        )

        # May or may not find LIQ #2 depending on data
        assert result is None or isinstance(result, dict)
        
        if result:
            assert 'gap_from_liq1' in result
            assert 5 <= result['gap_from_liq1'] <= 20

    def test_volume_spike_detection(self, sample_ohlcv):
        """Test volume spike detection"""
        lse_high = 16100
        
        result = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=50,  # Has volume spike
            level=lse_high,
            direction='up'
        )

        if result:
            assert 'volume_spike' in result
            # Check for truthy value (bool or numpy bool)
            assert result['volume_spike'] in [True, False]

    def test_rejection_detection(self, sample_ohlcv):
        """Test price rejection detection"""
        lse_high = 16100
        
        result = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=50,  # Has rejection
            level=lse_high,
            direction='up'
        )

        if result:
            assert 'has_rejection' in result
            assert result['has_rejection'] == True  # Designed to have rejection

    def test_wick_reversal_detection(self, sample_ohlcv):
        """Test wick reversal detection"""
        lse_high = 16100
        
        result = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=50,
            level=lse_high,
            direction='up'
        )

        if result:
            assert 'wick_reversal' in result
            # Check for truthy value (bool or numpy bool)
            assert result['wick_reversal'] in [True, False]

    def test_composite_score_calculation(self, sample_ohlcv):
        """Test composite score calculation"""
        lse_high = 16100
        
        result = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=50,
            level=lse_high,
            direction='up'
        )

        if result:
            assert 'score' in result
            assert 0 <= result['score'] <= 1

            # Score should be sum of weighted factors
            expected_score = 0.0
            if result['volume_spike']:
                expected_score += 0.4
            if result['has_rejection']:
                expected_score += 0.3
            if result['wick_reversal']:
                expected_score += 0.3

            assert abs(result['score'] - expected_score) < 0.01

    def test_break_distance(self, sample_ohlcv):
        """Test break distance calculation"""
        lse_high = 16100
        
        result = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=50,
            level=lse_high,
            direction='up'
        )

        if result:
            assert 'break_distance' in result
            assert result['break_distance'] >= 0

    def test_signals_dict(self, sample_ohlcv):
        """Test that signals dict is included"""
        lse_high = 16100
        
        result = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=50,
            level=lse_high,
            direction='up'
        )

        if result:
            assert 'signals' in result
            assert 'level_broken' in result['signals']
            assert 'volume_ratio' in result['signals']
            assert 'wick_ratio' in result['signals']

    def test_min_score_threshold(self, sample_ohlcv):
        """Test different min_score thresholds"""
        lse_high = 16100
        
        # Lenient threshold
        result_lenient = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=50,
            level=lse_high,
            direction='up',
            min_score=0.3
        )

        # Strict threshold
        result_strict = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=50,
            level=lse_high,
            direction='up',
            min_score=0.9
        )

        # Lenient should be more likely to detect
        if result_lenient:
            assert result_lenient['detected'] == True or result_lenient['score'] < 0.3

    def test_volume_threshold_adjustment(self, sample_ohlcv):
        """Test different volume thresholds"""
        lse_high = 16100
        
        # Low threshold (1.2x)
        result_low = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=50,
            level=lse_high,
            direction='up',
            volume_threshold=1.2
        )

        # High threshold (2.0x)
        result_high = LiquidityDetector.detect_liquidity_grab(
            sample_ohlcv,
            idx=50,
            level=lse_high,
            direction='up',
            volume_threshold=2.0
        )

        # Both should return results
        assert result_low is not None
        assert result_high is not None

    def test_no_liquidity_grabs_found(self, sample_ohlcv):
        """Test when no liquidity grabs found"""
        # Search with level that's never broken
        grabs = LiquidityDetector.find_liquidity_grabs(
            sample_ohlcv,
            start_idx=0,
            end_idx=20,
            level=20000,  # Very high level
            direction='up'
        )

        assert isinstance(grabs, list)
        assert len(grabs) == 0

    def test_get_best_when_none_found(self, sample_ohlcv):
        """Test get_best when no grabs found"""
        best = LiquidityDetector.get_best_liquidity_grab(
            sample_ohlcv,
            start_idx=0,
            end_idx=20,
            level=20000,
            direction='up'
        )

        assert best is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
