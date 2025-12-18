"""
Tests for ML Feature Stationarity

Verifies that features are invariant to absolute price levels (stationary).
This ensures model robustness across different market regimes.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from slob.features.feature_engineer import FeatureEngineer


def create_synthetic_setup(df: pd.DataFrame, price_scale: float = 1.0):
    """
    Create a synthetic setup with proportionally identical patterns at different price levels.

    Args:
        df: OHLCV DataFrame (already scaled)
        price_scale: Price multiplier (1.0, 1.5, 2.0, etc.)

    Returns:
        Setup dict
    """
    # Assume setup occurs around index 100
    liq1_idx = 50
    liq2_idx = 80
    entry_idx = 100
    nowick_idx = 75

    # LSE levels (proportional to price_scale)
    lse_high = 15300.0 * price_scale
    lse_low = 15200.0 * price_scale

    # Entry, SL, TP (proportional pattern)
    entry_price = 15265.0 * price_scale
    sl_level = 15307.0 * price_scale
    tp_level = 15199.0 * price_scale

    # Consolidation (proportional)
    consol = {
        'high': 15305.0 * price_scale,
        'low': 15270.0 * price_scale,
        'range': 35.0 * price_scale,
        'start_idx': 60,
        'end_idx': 80,
        'quality_score': 0.75,
        'tightness': 0.6
    }

    # No-wick candle (proportional)
    nowick_candle = {
        'Open': 15295.0 * price_scale,
        'High': 15300.0 * price_scale,
        'Low': 15270.0 * price_scale,
        'Close': 15275.0 * price_scale
    }

    # LIQ results
    liq1_result = {'score': 0.8}
    liq2_result = {'score': 0.85}

    # Entry timestamp (for temporal features)
    entry_time = datetime(2024, 1, 15, 10, 30, 0)  # Monday, 10:30 AM

    setup = {
        'liq1_idx': liq1_idx,
        'liq2_idx': liq2_idx,
        'entry_idx': entry_idx,
        'nowick_idx': nowick_idx,
        'entry_time': entry_time,
        'lse_high': lse_high,
        'lse_low': lse_low,
        'entry_price': entry_price,
        'sl_level': sl_level,
        'tp_level': tp_level,
        'consolidation': consol,
        'nowick_candle': nowick_candle,
        'liq1_result': liq1_result,
        'liq2_result': liq2_result
    }

    return setup


def create_scaled_df(base_price: float = 15000.0, scale: float = 1.0, n_rows: int = 150):
    """
    Create OHLCV DataFrame with proportionally scaled prices.

    Args:
        base_price: Base price level
        scale: Price multiplier (1.0 = 15k, 1.33 = 20k, 2.0 = 30k)
        n_rows: Number of rows

    Returns:
        DataFrame with OHLCV data
    """
    np.random.seed(42)  # Reproducible

    # Generate proportional price movement
    prices = []
    current = base_price * scale

    for _ in range(n_rows):
        # Random walk with proportional volatility (0.5% daily vol)
        change_pct = np.random.normal(0, 0.005)
        current = current * (1 + change_pct)
        prices.append(current)

    # Create OHLC from close prices (proportional patterns)
    data = []
    for i, close in enumerate(prices):
        # Proportional candle range (0.3% typical)
        candle_range = close * 0.003
        high = close + candle_range * np.random.uniform(0.3, 0.7)
        low = close - candle_range * np.random.uniform(0.3, 0.7)
        open_price = low + (high - low) * np.random.uniform(0.2, 0.8)

        # Proportional volume (scaled by price level)
        volume = int(10000 * np.random.uniform(0.8, 1.2))

        data.append({
            'Open': open_price,
            'High': high,
            'Low': low,
            'Close': close,
            'Volume': volume
        })

    df = pd.DataFrame(data)

    # Add datetime index (required for temporal features)
    start_time = datetime(2024, 1, 15, 9, 30, 0)  # Market open
    timestamps = [start_time + timedelta(minutes=i) for i in range(n_rows)]
    df.index = pd.DatetimeIndex(timestamps)

    return df


class TestFeatureStationarity:
    """Test that features are stationary (independent of absolute price level)."""

    def test_atr_relative_is_stationary(self):
        """Test that atr_relative is proportional across price levels."""
        # Create setups at 3 different price levels
        scales = [1.0, 1.5, 2.0]  # 15k, 22.5k, 30k
        atr_values = []

        for scale in scales:
            df = create_scaled_df(scale=scale)
            setup = create_synthetic_setup(df, price_scale=scale)
            features = FeatureEngineer.extract_features(df, setup, lookback=100)
            atr_values.append(features['atr_relative'])

        # atr_relative should be similar across scales (±10% tolerance)
        atr_mean = np.mean(atr_values)
        for atr in atr_values:
            assert abs(atr - atr_mean) / atr_mean < 0.10, \
                f"atr_relative varies across price levels: {atr_values}"

    def test_price_distances_are_percentage_based(self):
        """Test that price distances are normalized to percentages."""
        scales = [1.0, 1.5, 2.0]

        for scale in scales:
            df = create_scaled_df(scale=scale)
            setup = create_synthetic_setup(df, price_scale=scale)
            features = FeatureEngineer.extract_features(df, setup, lookback=100)

            # All percentage features should be in reasonable range (0-20%)
            assert 0 <= features['entry_to_lse_high_pct'] < 0.20
            assert 0 <= features['entry_to_lse_low_pct'] < 0.20
            assert 0 <= features['lse_range_pct'] < 0.20

    def test_identical_patterns_produce_identical_features(self):
        """Test that proportionally identical setups produce identical features."""
        # Create identical patterns at 15k and 30k (2x scale)
        df_15k = create_scaled_df(scale=1.0)
        setup_15k = create_synthetic_setup(df_15k, price_scale=1.0)
        features_15k = FeatureEngineer.extract_features(df_15k, setup_15k, lookback=100)

        df_30k = create_scaled_df(scale=2.0)
        setup_30k = create_synthetic_setup(df_30k, price_scale=2.0)
        features_30k = FeatureEngineer.extract_features(df_30k, setup_30k, lookback=100)

        # Key stationary features should match (±15% tolerance for randomness)
        stationary_features = [
            'atr_relative',
            'entry_to_lse_high_pct',
            'entry_to_lse_low_pct',
            'lse_range_pct',
            'nowick_body_pct',
            'liq2_sweep_pct',
            'price_volatility_cv',
            'consol_range_atr_ratio',
            'risk_reward_ratio',
            'entry_price_consol_position'
        ]

        for feat in stationary_features:
            val_15k = features_15k.get(feat, 0)
            val_30k = features_30k.get(feat, 0)

            # Skip if both are zero
            if val_15k == 0 and val_30k == 0:
                continue

            # Calculate relative difference
            avg = (abs(val_15k) + abs(val_30k)) / 2
            if avg > 0:
                rel_diff = abs(val_15k - val_30k) / avg
                assert rel_diff < 0.20, \
                    f"Feature '{feat}' not stationary: {val_15k:.4f} vs {val_30k:.4f} (diff: {rel_diff:.2%})"

    def test_no_correlation_with_absolute_price(self):
        """Test that features don't correlate with absolute price level."""
        scales = np.linspace(0.8, 2.5, 10)  # 12k to 37.5k
        feature_values = {
            'atr_relative': [],
            'entry_to_lse_high_pct': [],
            'lse_range_pct': []
        }

        for scale in scales:
            df = create_scaled_df(scale=scale)
            setup = create_synthetic_setup(df, price_scale=scale)
            features = FeatureEngineer.extract_features(df, setup, lookback=100)

            for feat in feature_values.keys():
                feature_values[feat].append(features[feat])

        # Calculate correlation between each feature and price scale
        for feat, values in feature_values.items():
            correlation = np.corrcoef(scales, values)[0, 1]

            # Absolute correlation should be < 0.4 (weak or no correlation)
            # Note: Some variation expected due to random walk in synthetic data
            assert abs(correlation) < 0.4, \
                f"Feature '{feat}' correlates with price level: r={correlation:.3f}"

    def test_price_volatility_cv_is_stationary(self):
        """Test that coefficient of variation is stable across price levels."""
        scales = [1.0, 1.5, 2.0]
        cv_values = []

        for scale in scales:
            df = create_scaled_df(scale=scale)
            setup = create_synthetic_setup(df, price_scale=scale)
            features = FeatureEngineer.extract_features(df, setup, lookback=100)
            cv_values.append(features['price_volatility_cv'])

        # CV should be similar across scales
        cv_mean = np.mean(cv_values)
        for cv in cv_values:
            if cv_mean > 0:
                assert abs(cv - cv_mean) / cv_mean < 0.15, \
                    f"price_volatility_cv varies: {cv_values}"

    def test_feature_names_updated(self):
        """Test that feature names reflect stationary versions."""
        feature_names = FeatureEngineer.get_feature_names()

        # Stationary features should be present
        assert 'atr_relative' in feature_names
        assert 'entry_to_lse_high_pct' in feature_names
        assert 'entry_to_lse_low_pct' in feature_names
        assert 'lse_range_pct' in feature_names
        assert 'nowick_body_pct' in feature_names
        assert 'liq2_sweep_pct' in feature_names
        assert 'price_volatility_cv' in feature_names

        # Old absolute features should NOT be present
        assert 'atr' not in feature_names  # Should be atr_relative
        assert 'entry_to_lse_high' not in feature_names  # Should be _pct
        assert 'lse_range' not in feature_names  # Should be _pct
        assert 'nowick_body_size' not in feature_names  # Should be _pct
        assert 'price_volatility_std' not in feature_names  # Should be _cv

    def test_all_features_extract_successfully(self):
        """Test that all features can be extracted without errors."""
        df = create_scaled_df()
        setup = create_synthetic_setup(df)
        features = FeatureEngineer.extract_features(df, setup, lookback=100)

        # Should have all expected features
        expected_count = 37  # Total feature count
        assert len(features) >= expected_count - 3, \
            f"Expected ~{expected_count} features, got {len(features)}"

        # No NaN values
        for name, value in features.items():
            assert not np.isnan(value), f"Feature '{name}' is NaN"
            assert np.isfinite(value), f"Feature '{name}' is infinite"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
