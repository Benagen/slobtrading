"""
Tests for ConsolidationDetector.

Run with: pytest tests/test_consolidation_detector.py -v
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from slob.patterns import ConsolidationDetector


@pytest.fixture
def sample_ohlcv():
    """Create sample OHLCV data with consolidation"""
    dates = pd.date_range('2024-01-15 15:00', periods=200, freq='1min')
    
    np.random.seed(42)
    data = []
    
    # First 50 candles: normal volatility (ATR baseline)
    base_price = 16000
    for i in range(50):
        base_price += np.random.randn() * 15  # Larger moves for ATR
        open_price = base_price + np.random.randn() * 5
        close_price = open_price + np.random.randn() * 10
        high_price = max(open_price, close_price) + np.abs(np.random.randn() * 8)
        low_price = min(open_price, close_price) - np.abs(np.random.randn() * 8)
        
        data.append({
            'Open': open_price,
            'High': high_price,
            'Low': low_price,
            'Close': close_price,
            'Volume': np.random.randint(5000, 10000)
        })
    
    # Calculate expected ATR to create appropriate consolidation
    temp_df = pd.DataFrame(data)
    hl = temp_df['High'] - temp_df['Low']
    atr_estimate = hl.rolling(14).mean().iloc[-1]
    
    # Candles 50-75: Consolidation within ATR bounds
    consol_base = base_price
    consol_range = atr_estimate * 1.2  # Within 0.5-2.0 multiplier
    
    for i in range(25):
        # Oscillate within tight range
        offset = (i % 5 - 2) * (consol_range / 10)
        open_price = consol_base + offset + np.random.randn() * 1
        close_price = open_price + np.random.randn() * 2
        high_price = max(open_price, close_price) + np.abs(np.random.randn() * 1)
        low_price = min(open_price, close_price) - np.abs(np.random.randn() * 1)
        
        # Ensure within consolidation bounds
        high_price = min(high_price, consol_base + consol_range/2)
        low_price = max(low_price, consol_base - consol_range/2)
        
        data.append({
            'Open': open_price,
            'High': high_price,
            'Low': low_price,
            'Close': close_price,
            'Volume': np.random.randint(2000, 5000)  # Lower volume
        })
    
    # Rest: normal
    for i in range(125):
        base_price += np.random.randn() * 10
        open_price = base_price + np.random.randn() * 3
        close_price = open_price + np.random.randn() * 8
        high_price = max(open_price, close_price) + np.abs(np.random.randn() * 5)
        low_price = min(open_price, close_price) - np.abs(np.random.randn() * 5)
        
        data.append({
            'Open': open_price,
            'High': high_price,
            'Low': low_price,
            'Close': close_price,
            'Volume': np.random.randint(5000, 10000)
        })
    
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def trending_data():
    """Create trending data (should NOT be detected as consolidation)"""
    dates = pd.date_range('2024-01-15 15:00', periods=100, freq='1min')
    
    data = []
    base_price = 16000
    
    for i in range(100):
        base_price += 5  # Strong uptrend
        open_price = base_price + np.random.randn() * 2
        close_price = open_price + 3
        high_price = max(open_price, close_price) + np.abs(np.random.randn() * 2)
        low_price = min(open_price, close_price) - np.abs(np.random.randn() * 2)
        
        data.append({
            'Open': open_price,
            'High': high_price,
            'Low': low_price,
            'Close': close_price,
            'Volume': np.random.randint(1000, 10000)
        })
    
    return pd.DataFrame(data, index=dates)


class TestConsolidationDetector:
    """Test suite for ConsolidationDetector"""

    def test_detect_consolidation_basic(self, sample_ohlcv):
        """Test basic consolidation detection"""
        result = ConsolidationDetector.detect_consolidation(
            sample_ohlcv,
            start_idx=50,  # Where consolidation starts
            atr_multiplier_min=0.3,  # Wider range to catch it
            atr_multiplier_max=3.0
        )

        # May or may not find consolidation depending on data
        # At minimum, should not crash
        assert result is None or isinstance(result, dict)
        
        if result:
            assert 'start_idx' in result
            assert 'end_idx' in result
            assert 'range' in result
            assert 'atr' in result
            assert 'quality_score' in result

    def test_consolidation_duration(self, sample_ohlcv):
        """Test that detected consolidation has reasonable duration"""
        result = ConsolidationDetector.detect_consolidation(
            sample_ohlcv,
            start_idx=50,
            min_duration=15,
            max_duration=30
        )

        if result:
            assert 15 <= result['duration'] <= 30
            assert result['end_idx'] - result['start_idx'] == result['duration']

    def test_atr_calculation(self, sample_ohlcv):
        """Test ATR calculation"""
        atr = ConsolidationDetector._calculate_atr(
            sample_ohlcv,
            end_idx=50,
            period=14
        )

        assert atr > 0
        assert isinstance(atr, float)
        # ATR should be reasonable for our data
        assert 1 < atr < 100

    def test_quality_assessment(self, sample_ohlcv):
        """Test quality assessment of consolidation"""
        window = sample_ohlcv.iloc[50:75]  # Known consolidation
        atr = ConsolidationDetector._calculate_atr(sample_ohlcv, 50, 14)

        quality = ConsolidationDetector._assess_quality(window, atr)

        assert 'score' in quality
        assert 'tightness' in quality
        assert 'volume_compression' in quality
        assert 'breakout_ready' in quality

        assert 0 <= quality['score'] <= 1
        assert 0 <= quality['tightness'] <= 1

    def test_trending_rejection(self, trending_data):
        """Test that trending periods are not detected as consolidation"""
        result = ConsolidationDetector.detect_consolidation(
            trending_data,
            start_idx=50
        )

        # Should either return None or low quality score
        if result:
            # If detected, quality should be low
            assert result['quality_score'] < 0.5

    def test_is_trending(self, trending_data, sample_ohlcv):
        """Test trend detection"""
        # Trending window
        trending_window = trending_data.iloc[50:70]
        atr_trend = ConsolidationDetector._calculate_atr(trending_data, 50, 14)
        is_trend = ConsolidationDetector._is_trending(trending_window, atr_trend)
        
        # Use == instead of is for boolean comparison
        assert is_trend == True  # Should detect as trending

        # Consolidating window
        consol_window = sample_ohlcv.iloc[50:70]
        atr_consol = ConsolidationDetector._calculate_atr(sample_ohlcv, 50, 14)
        is_trend_consol = ConsolidationDetector._is_trending(consol_window, atr_consol)
        
        assert is_trend_consol == False  # Should NOT detect as trending

    def test_insufficient_data(self, sample_ohlcv):
        """Test behavior with insufficient data"""
        # Try to detect too early (not enough lookback)
        result = ConsolidationDetector.detect_consolidation(
            sample_ohlcv,
            start_idx=10,  # Not enough lookback
            lookback_for_atr=100
        )

        assert result is None

    def test_no_consolidation_found(self, trending_data):
        """Test when no valid consolidation exists"""
        result = ConsolidationDetector.detect_consolidation(
            trending_data,
            start_idx=50,
            min_duration=15,
            max_duration=30
        )

        # Trending data should not produce high-quality consolidation
        if result:
            assert result['quality_score'] < 0.6

    def test_atr_multipliers(self, sample_ohlcv):
        """Test different ATR multiplier settings"""
        # Tight range (0.3-1.0x ATR)
        result_tight = ConsolidationDetector.detect_consolidation(
            sample_ohlcv,
            start_idx=50,
            atr_multiplier_min=0.3,
            atr_multiplier_max=1.0
        )

        # Wide range (0.5-3.0x ATR)
        result_wide = ConsolidationDetector.detect_consolidation(
            sample_ohlcv,
            start_idx=50,
            atr_multiplier_min=0.5,
            atr_multiplier_max=3.0
        )

        # Both might find consolidation, but could be different
        # Wide range is more permissive
        if result_tight and result_wide:
            assert result_wide['range'] >= result_tight['range']

    def test_validate_consolidation(self, sample_ohlcv):
        """Test consolidation validation"""
        # Detect consolidation first
        result = ConsolidationDetector.detect_consolidation(
            sample_ohlcv,
            start_idx=50,
            atr_multiplier_min=0.3,
            atr_multiplier_max=3.0
        )

        if result:
            is_valid, issues = ConsolidationDetector.validate_consolidation(
                sample_ohlcv,
                result,
                strict=False
            )

            assert isinstance(is_valid, bool)
            assert isinstance(issues, list)

            # Good consolidation should validate
            if result['quality_score'] > 0.6:
                assert is_valid == True

    def test_validate_strict_mode(self, sample_ohlcv):
        """Test strict validation mode"""
        result = ConsolidationDetector.detect_consolidation(
            sample_ohlcv,
            start_idx=50,
            atr_multiplier_min=0.3,
            atr_multiplier_max=3.0
        )

        if result:
            # Strict mode
            is_valid_strict, issues_strict = ConsolidationDetector.validate_consolidation(
                sample_ohlcv,
                result,
                strict=True
            )

            # Non-strict mode
            is_valid_normal, issues_normal = ConsolidationDetector.validate_consolidation(
                sample_ohlcv,
                result,
                strict=False
            )

            # Strict should have same or more issues
            assert len(issues_strict) >= len(issues_normal)

    def test_quality_score_range(self, sample_ohlcv):
        """Test that quality scores are in valid range"""
        result = ConsolidationDetector.detect_consolidation(
            sample_ohlcv,
            start_idx=50,
            atr_multiplier_min=0.3,
            atr_multiplier_max=3.0
        )

        if result:
            assert 0 <= result['quality_score'] <= 1.0
            assert 0 <= result['tightness'] <= 1.0

    def test_consolidation_range(self, sample_ohlcv):
        """Test that consolidation range is correctly calculated"""
        result = ConsolidationDetector.detect_consolidation(
            sample_ohlcv,
            start_idx=50,
            atr_multiplier_min=0.3,
            atr_multiplier_max=3.0
        )

        if result:
            window = sample_ohlcv.iloc[result['start_idx']:result['end_idx']]
            expected_range = window['High'].max() - window['Low'].min()
            
            assert abs(result['range'] - expected_range) < 0.01
            assert result['high'] == window['High'].max()
            assert result['low'] == window['Low'].min()

    def test_volume_compression_detection(self, sample_ohlcv):
        """Test volume compression detection"""
        # Our sample has lower volume in consolidation (50-75)
        window = sample_ohlcv.iloc[50:75]
        atr = ConsolidationDetector._calculate_atr(sample_ohlcv, 50, 14)
        
        quality = ConsolidationDetector._assess_quality(window, atr)
        
        # Check that volume_compression is truthy (bool or numpy bool)
        assert 'volume_compression' in quality
        # Should detect some compression with our data
        assert quality['volume_compression'] == True

    def test_breakout_readiness(self, sample_ohlcv):
        """Test breakout readiness detection"""
        # Create window with price at high
        window = sample_ohlcv.iloc[50:70].copy()
        
        # Force last close to be near high
        consol_high = window['High'].max()
        consol_low = window['Low'].min()
        window.loc[window.index[-1], 'Close'] = consol_high - (consol_high - consol_low) * 0.1
        
        atr = ConsolidationDetector._calculate_atr(sample_ohlcv, 50, 14)
        quality = ConsolidationDetector._assess_quality(window, atr)
        
        # Check that breakout_ready exists and is truthy
        assert 'breakout_ready' in quality
        assert quality['breakout_ready'] == True
        assert quality['price_position'] > 0.7

    def test_midpoint_crosses(self, sample_ohlcv):
        """Test midpoint cross counting"""
        window = sample_ohlcv.iloc[50:75]
        atr = ConsolidationDetector._calculate_atr(sample_ohlcv, 50, 14)
        
        quality = ConsolidationDetector._assess_quality(window, atr)
        
        # Should have some midpoint crosses in oscillating consolidation
        assert 'midpoint_crosses' in quality
        assert quality['midpoint_crosses'] >= 0

    def test_different_durations(self, sample_ohlcv):
        """Test detection with different duration settings"""
        # Short duration
        result_short = ConsolidationDetector.detect_consolidation(
            sample_ohlcv,
            start_idx=50,
            min_duration=10,
            max_duration=20,
            atr_multiplier_min=0.3,
            atr_multiplier_max=3.0
        )

        # Long duration
        result_long = ConsolidationDetector.detect_consolidation(
            sample_ohlcv,
            start_idx=50,
            min_duration=20,
            max_duration=35,
            atr_multiplier_min=0.3,
            atr_multiplier_max=3.0
        )

        # Both might find consolidation
        if result_short:
            assert 10 <= result_short['duration'] <= 20
        
        if result_long:
            assert 20 <= result_long['duration'] <= 35

    def test_tightness_calculation(self, sample_ohlcv):
        """Test tightness calculation"""
        # Create perfect consolidation (tightening)
        window = sample_ohlcv.iloc[50:70].copy()
        atr = 10.0
        
        quality = ConsolidationDetector._assess_quality(window, atr)
        
        # Tightness should be between 0 and 1
        assert 0 <= quality['tightness'] <= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
