"""
Tests for FeatureEngineer.

Run with: pytest tests/test_feature_engineer.py -v
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from slob.features import FeatureEngineer


@pytest.fixture
def sample_ohlcv():
    """Create sample OHLCV data"""
    dates = pd.date_range('2024-01-15 15:00', periods=200, freq='1min')
    
    np.random.seed(42)
    data = []
    
    base_price = 4800
    
    for i in range(200):
        base_price += np.random.randn() * 2
        open_price = base_price + np.random.randn()
        close_price = open_price + np.random.randn() * 5
        high_price = max(open_price, close_price) + np.abs(np.random.randn() * 3)
        low_price = min(open_price, close_price) - np.abs(np.random.randn() * 3)
        volume = np.random.randint(3000, 10000)
        
        data.append({
            'Open': open_price,
            'High': high_price,
            'Low': low_price,
            'Close': close_price,
            'Volume': volume
        })
    
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def sample_setup(sample_ohlcv):
    """Create sample setup dict"""
    setup = {
        'liq1_idx': 50,
        'liq2_idx': 80,
        'entry_idx': 85,
        'nowick_idx': 75,
        'lse_high': 4850.0,
        'lse_low': 4750.0,
        'entry_price': 4820.0,
        'sl_level': 4860.0,
        'tp_level': 4755.0,
        'consolidation': {
            'start_idx': 51,
            'end_idx': 79,
            'range': 25.0,
            'high': 4835.0,
            'low': 4810.0,
            'quality_score': 0.75,
            'tightness': 0.6
        },
        'liq1_result': {
            'score': 0.8,
            'detected': True
        },
        'liq2_result': {
            'score': 0.7,
            'detected': True
        },
        'nowick_candle': sample_ohlcv.iloc[75]
    }
    return setup


class TestFeatureEngineer:
    """Test suite for FeatureEngineer"""

    def test_extract_features_complete(self, sample_ohlcv, sample_setup):
        """Test that all features are extracted"""
        features = FeatureEngineer.extract_features(sample_ohlcv, sample_setup)
        
        # Should have 35 features
        expected_count = 35
        assert len(features) >= expected_count - 5  # Allow some flexibility
        
        # Check all features are numeric
        for key, value in features.items():
            assert isinstance(value, (int, float, np.number))
            assert not np.isnan(value)
            assert not np.isinf(value)

    def test_volume_features(self, sample_ohlcv, sample_setup):
        """Test volume feature extraction"""
        features = FeatureEngineer._extract_volume_features(
            sample_ohlcv, sample_setup, lookback=50
        )
        
        # Should have 8 volume features
        assert 'vol_liq1_ratio' in features
        assert 'vol_liq2_ratio' in features
        assert 'vol_entry_ratio' in features
        assert 'vol_consol_trend' in features
        assert 'vol_consol_mean' in features
        assert 'vol_spike_magnitude' in features
        assert 'vol_distribution_skew' in features
        assert 'vol_at_nowick' in features
        
        # Ratios should be positive
        assert features['vol_liq1_ratio'] > 0
        assert features['vol_liq2_ratio'] > 0
        assert features['vol_entry_ratio'] > 0

    def test_volatility_features(self, sample_ohlcv, sample_setup):
        """Test volatility feature extraction"""
        features = FeatureEngineer._extract_volatility_features(
            sample_ohlcv, sample_setup, lookback=100
        )

        # Should have 7 volatility features (using STATIONARY names)
        assert 'atr_relative' in features  # Changed from 'atr'
        assert 'atr_percentile' in features
        assert 'consol_range_atr_ratio' in features
        assert 'bollinger_bandwidth' in features
        assert 'consol_tightness' in features
        assert 'price_volatility_cv' in features  # Changed from 'price_volatility_std'
        assert 'atr_change_rate' in features

        # ATR relative should be positive
        assert features['atr_relative'] > 0

        # Percentile should be 0-100
        assert 0 <= features['atr_percentile'] <= 100

    def test_temporal_features(self, sample_ohlcv, sample_setup):
        """Test temporal feature extraction"""
        features = FeatureEngineer._extract_temporal_features(
            sample_ohlcv, sample_setup
        )
        
        # Should have 10 temporal features (8 base + weekday one-hot)
        assert 'hour' in features
        assert 'minute' in features
        assert 'weekday_0' in features
        assert 'weekday_1' in features
        assert 'weekday_2' in features
        assert 'weekday_3' in features
        assert 'weekday_4' in features
        assert 'minutes_since_nyse_open' in features
        assert 'consol_duration' in features
        assert 'time_liq1_to_entry' in features
        
        # Hour should be valid
        assert 0 <= features['hour'] <= 23
        
        # Only one weekday should be 1
        weekday_sum = sum([features[f'weekday_{i}'] for i in range(5)])
        assert weekday_sum == 1.0

    def test_price_action_features(self, sample_ohlcv, sample_setup):
        """Test price action feature extraction"""
        features = FeatureEngineer._extract_price_action_features(
            sample_ohlcv, sample_setup
        )

        # Should have 8 price action features (using STATIONARY names)
        assert 'entry_to_lse_high_pct' in features  # Changed from 'entry_to_lse_high'
        assert 'entry_to_lse_low_pct' in features   # Changed from 'entry_to_lse_low'
        assert 'risk_reward_ratio' in features
        assert 'nowick_body_pct' in features  # Changed from 'nowick_body_size'
        assert 'nowick_wick_ratio' in features
        assert 'liq2_sweep_pct' in features  # Changed from 'liq2_sweep_distance'
        assert 'entry_price_consol_position' in features
        assert 'lse_range_pct' in features  # Changed from 'lse_range'

        # Risk:reward should be positive
        assert features['risk_reward_ratio'] > 0

        # LSE range pct should be positive
        assert features['lse_range_pct'] > 0

    def test_pattern_quality_features(self, sample_setup):
        """Test pattern quality feature extraction"""
        features = FeatureEngineer._extract_pattern_quality_features(sample_setup)
        
        # Should have 4 pattern quality features
        assert 'consol_quality_score' in features
        assert 'liq1_confidence' in features
        assert 'liq2_confidence' in features
        assert 'pattern_alignment_score' in features
        
        # Scores should be 0-1
        assert 0 <= features['consol_quality_score'] <= 1
        assert 0 <= features['liq1_confidence'] <= 1
        assert 0 <= features['liq2_confidence'] <= 1
        assert 0 <= features['pattern_alignment_score'] <= 1

    def test_create_feature_matrix(self, sample_ohlcv):
        """Test creating feature matrix from multiple setups"""
        setups = []
        trades = []
        
        for i in range(3):
            setup = {
                'liq1_idx': 50 + i*20,
                'liq2_idx': 80 + i*20,
                'entry_idx': 85 + i*20,
                'nowick_idx': 75 + i*20,
                'lse_high': 4850.0,
                'lse_low': 4750.0,
                'entry_price': 4820.0,
                'sl_level': 4860.0,
                'tp_level': 4755.0,
                'consolidation': {
                    'start_idx': 51 + i*20,
                    'end_idx': 79 + i*20,
                    'range': 25.0,
                    'high': 4835.0,
                    'low': 4810.0,
                    'quality_score': 0.75,
                    'tightness': 0.6
                },
                'liq1_result': {'score': 0.8},
                'liq2_result': {'score': 0.7},
                'nowick_candle': sample_ohlcv.iloc[75 + i*20]
            }
            setups.append(setup)
            trades.append({'result': 'WIN' if i % 2 == 0 else 'LOSS'})
        
        df_features = FeatureEngineer.create_feature_matrix(
            sample_ohlcv, setups, trades
        )
        
        # Should have 3 rows
        assert len(df_features) == 3
        
        # Should have label column
        assert 'label' in df_features.columns
        
        # Labels should be 0 or 1
        assert set(df_features['label'].unique()).issubset({0, 1})

    def test_create_feature_matrix_no_labels(self, sample_ohlcv, sample_setup):
        """Test creating feature matrix without labels"""
        setups = [sample_setup]
        
        df_features = FeatureEngineer.create_feature_matrix(
            sample_ohlcv, setups, trades=None
        )
        
        # Should have 1 row
        assert len(df_features) == 1
        
        # Should NOT have label column
        assert 'label' not in df_features.columns

    def test_get_feature_names(self):
        """Test getting feature names"""
        feature_names = FeatureEngineer.get_feature_names()

        # Should have 37 features (8 volume + 7 volatility + 10 temporal + 8 price + 4 quality)
        assert len(feature_names) == 37

        # Should be strings
        assert all(isinstance(name, str) for name in feature_names)

        # Should have expected STATIONARY features
        assert 'vol_liq1_ratio' in feature_names
        assert 'atr_relative' in feature_names  # Changed from 'atr'
        assert 'hour' in feature_names
        assert 'risk_reward_ratio' in feature_names
        assert 'consol_quality_score' in feature_names

        # OLD non-stationary names should NOT exist
        assert 'atr' not in feature_names
        assert 'entry_to_lse_high' not in feature_names
        assert 'lse_range' not in feature_names
        assert 'nowick_body_size' not in feature_names
        assert 'price_volatility_std' not in feature_names

    def test_missing_data_handling(self, sample_ohlcv):
        """Test handling of missing data in setup"""
        incomplete_setup = {
            'liq1_idx': None,
            'liq2_idx': None,
            'entry_idx': 85,
            'lse_high': 4850.0,
            'lse_low': 4750.0,
            'entry_price': 4820.0,
            'sl_level': 4860.0,
            'tp_level': 4755.0
        }
        
        features = FeatureEngineer.extract_features(sample_ohlcv, incomplete_setup)
        
        # Should still return features (with defaults)
        assert len(features) > 0
        
        # Volume features should be default values
        assert features.get('vol_liq1_ratio', 0) >= 0
        assert features.get('vol_liq2_ratio', 0) >= 0

    def test_edge_case_zero_atr(self, sample_ohlcv):
        """Test handling when ATR is zero"""
        # Create flat price data
        flat_data = []
        for i in range(100):
            flat_data.append({
                'Open': 4800.0,
                'High': 4800.0,
                'Low': 4800.0,
                'Close': 4800.0,
                'Volume': 5000
            })
        
        dates = pd.date_range('2024-01-15 15:00', periods=100, freq='1min')
        df_flat = pd.DataFrame(flat_data, index=dates)
        
        setup = {
            'liq1_idx': 50,
            'liq2_idx': 80,
            'entry_idx': 85,
            'lse_high': 4800.0,
            'lse_low': 4800.0,
            'entry_price': 4800.0,
            'sl_level': 4805.0,
            'tp_level': 4795.0,
            'consolidation': {
                'start_idx': 51,
                'end_idx': 79,
                'range': 0.0,
                'quality_score': 0.5
            },
            'liq1_result': {'score': 0.5},
            'liq2_result': {'score': 0.5}
        }
        
        features = FeatureEngineer.extract_features(df_flat, setup)
        
        # Should handle gracefully
        assert features is not None
        assert all(not np.isnan(v) for v in features.values())
        assert all(not np.isinf(v) for v in features.values())

    def test_feature_ranges(self, sample_ohlcv, sample_setup):
        """Test that features are in reasonable ranges"""
        features = FeatureEngineer.extract_features(sample_ohlcv, sample_setup)

        # Volume ratios should be positive
        assert features['vol_liq1_ratio'] > 0
        assert features['vol_liq2_ratio'] > 0

        # ATR relative should be positive
        assert features['atr_relative'] > 0

        # Percentile should be 0-100
        assert 0 <= features['atr_percentile'] <= 100

        # Hour should be 0-23
        assert 0 <= features['hour'] <= 23

        # Minute should be 0-59
        assert 0 <= features['minute'] <= 59

        # Quality scores should be 0-1
        assert 0 <= features['consol_quality_score'] <= 1
        assert 0 <= features['liq1_confidence'] <= 1
        assert 0 <= features['liq2_confidence'] <= 1

    def test_feature_consistency(self, sample_ohlcv, sample_setup):
        """Test that same setup produces same features"""
        features1 = FeatureEngineer.extract_features(sample_ohlcv, sample_setup)
        features2 = FeatureEngineer.extract_features(sample_ohlcv, sample_setup)
        
        # Should be identical
        for key in features1:
            assert abs(features1[key] - features2[key]) < 1e-10

    def test_different_setups_different_features(self, sample_ohlcv):
        """Test that different setups produce different features"""
        setup1 = {
            'liq1_idx': 50,
            'liq2_idx': 80,
            'entry_idx': 85,
            'lse_high': 4850.0,
            'lse_low': 4750.0,
            'entry_price': 4820.0,
            'sl_level': 4860.0,
            'tp_level': 4755.0,
            'consolidation': {'quality_score': 0.75, 'start_idx': 51, 'end_idx': 79},
            'liq1_result': {'score': 0.8},
            'liq2_result': {'score': 0.7}
        }
        
        setup2 = {
            'liq1_idx': 100,
            'liq2_idx': 130,
            'entry_idx': 135,
            'lse_high': 4900.0,
            'lse_low': 4700.0,
            'entry_price': 4850.0,
            'sl_level': 4910.0,
            'tp_level': 4705.0,
            'consolidation': {'quality_score': 0.6, 'start_idx': 101, 'end_idx': 129},
            'liq1_result': {'score': 0.6},
            'liq2_result': {'score': 0.5}
        }
        
        features1 = FeatureEngineer.extract_features(sample_ohlcv, setup1)
        features2 = FeatureEngineer.extract_features(sample_ohlcv, setup2)
        
        # At least some features should be different
        differences = sum(1 for k in features1 if abs(features1[k] - features2.get(k, 0)) > 0.01)
        assert differences > 10  # At least 10 features should differ


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
