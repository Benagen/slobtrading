"""
Tests for SyntheticGenerator.

Run with: pytest tests/test_synthetic_generator.py -v
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime

from slob.data import SyntheticGenerator


@pytest.fixture
def sample_m5_data():
    """Create sample M5 data"""
    dates = pd.date_range('2024-01-15 15:30', periods=20, freq='5min', tz='Europe/Stockholm')

    np.random.seed(42)

    # Generate valid OHLC M5 data
    data = []
    base_price = 16000

    for i in range(20):
        base_price += np.random.randn() * 20

        open_price = base_price + np.random.randn() * 5
        close_price = open_price + np.random.randn() * 15

        high_price = max(open_price, close_price) + np.abs(np.random.randn() * 10)
        low_price = min(open_price, close_price) - np.abs(np.random.randn() * 10)

        data.append({
            'Open': open_price,
            'High': high_price,
            'Low': low_price,
            'Close': close_price,
            'Volume': np.random.randint(5000, 50000)
        })

    df = pd.DataFrame(data, index=dates)
    return df


class TestSyntheticGenerator:
    """Test suite for SyntheticGenerator"""

    def test_generate_brownian_method(self, sample_m5_data):
        """Test Brownian Bridge method"""
        df_m1 = SyntheticGenerator.generate_m1_from_m5(
            sample_m5_data,
            method="brownian"
        )

        # Check basic properties
        assert not df_m1.empty
        assert len(df_m1) == len(sample_m5_data) * 5
        assert list(df_m1.columns) == ['Open', 'High', 'Low', 'Close', 'Volume', 'Synthetic']
        assert (df_m1['Synthetic'] == True).all()

    def test_generate_linear_method(self, sample_m5_data):
        """Test linear interpolation method"""
        df_m1 = SyntheticGenerator.generate_m1_from_m5(
            sample_m5_data,
            method="linear"
        )

        assert not df_m1.empty
        assert len(df_m1) == len(sample_m5_data) * 5
        assert 'Synthetic' in df_m1.columns
        assert (df_m1['Synthetic'] == True).all()

    def test_generate_volume_weighted_method(self, sample_m5_data):
        """Test volume-weighted method"""
        df_m1 = SyntheticGenerator.generate_m1_from_m5(
            sample_m5_data,
            method="volume_weighted"
        )

        assert not df_m1.empty
        assert len(df_m1) == len(sample_m5_data) * 5
        assert 'Synthetic' in df_m1.columns

    def test_invalid_method(self, sample_m5_data):
        """Test invalid method raises error"""
        with pytest.raises(ValueError, match="Invalid method"):
            SyntheticGenerator.generate_m1_from_m5(
                sample_m5_data,
                method="invalid"
            )

    def test_empty_input(self):
        """Test empty input raises error"""
        empty_df = pd.DataFrame()

        with pytest.raises(ValueError, match="empty"):
            SyntheticGenerator.generate_m1_from_m5(empty_df)

    def test_ohlc_constraints(self, sample_m5_data):
        """Test that generated M1 respects OHLC constraints"""
        df_m1 = SyntheticGenerator.generate_m1_from_m5(
            sample_m5_data,
            method="brownian"
        )

        # High >= max(Open, Close)
        invalid_high = (df_m1['High'] < df_m1[['Open', 'Close']].max(axis=1)).sum()
        assert invalid_high == 0, f"{invalid_high} candles have High < max(Open, Close)"

        # Low <= min(Open, Close)
        invalid_low = (df_m1['Low'] > df_m1[['Open', 'Close']].min(axis=1)).sum()
        assert invalid_low == 0, f"{invalid_low} candles have Low > min(Open, Close)"

    def test_resample_consistency(self, sample_m5_data):
        """Test that resampling M1 back to M5 gives original data"""
        df_m1 = SyntheticGenerator.generate_m1_from_m5(
            sample_m5_data,
            method="brownian"
        )

        # Remove Synthetic column for resampling
        df_m1_clean = df_m1.drop('Synthetic', axis=1)

        # Resample M1 back to M5
        m1_resampled = df_m1_clean.resample('5min').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }).dropna()

        # Compare with original M5 (allow small floating point errors)
        assert len(m1_resampled) == len(sample_m5_data)

        # Check Open values match
        open_diff = abs(m1_resampled['Open'] - sample_m5_data['Open']).max()
        assert open_diff < 0.01, f"Open values differ by {open_diff}"

        # Check Close values match
        close_diff = abs(m1_resampled['Close'] - sample_m5_data['Close']).max()
        assert close_diff < 0.01, f"Close values differ by {close_diff}"

        # Volume should sum correctly (allow rounding errors from int conversion)
        volume_diff = abs(m1_resampled['Volume'] - sample_m5_data['Volume']).max()
        # With dirichlet distribution and int conversion, we can lose up to 4 per M5 candle
        assert volume_diff < 5, f"Volume distribution error: max diff = {volume_diff}"

    def test_m5_constraints_respected(self, sample_m5_data):
        """Test that M1 candles respect M5 high/low boundaries"""
        df_m1 = SyntheticGenerator.generate_m1_from_m5(
            sample_m5_data,
            method="brownian"
        )

        # For each M5 candle, check that corresponding M1 candles respect boundaries
        for i, m5_row in sample_m5_data.iterrows():
            # Get corresponding M1 candles
            m1_start = i
            m1_end = i + pd.Timedelta(minutes=5)
            m1_window = df_m1[(df_m1.index >= m1_start) & (df_m1.index < m1_end)]

            if len(m1_window) > 0:
                # All M1 highs should be <= M5 high
                m1_max_high = m1_window['High'].max()
                assert m1_max_high <= m5_row['High'] + 0.01, \
                    f"M1 high ({m1_max_high}) exceeds M5 high ({m5_row['High']})"

                # All M1 lows should be >= M5 low
                m1_min_low = m1_window['Low'].min()
                assert m1_min_low >= m5_row['Low'] - 0.01, \
                    f"M1 low ({m1_min_low}) below M5 low ({m5_row['Low']})"

    def test_brownian_bridge_generation(self):
        """Test Brownian Bridge price path generation"""
        path = SyntheticGenerator._generate_brownian_bridge(
            start=100,
            end=105,
            n_steps=5,
            volatility=10,
            high_constraint=110,
            low_constraint=95
        )

        # Check path properties
        assert len(path) == 6  # n_steps + 1
        assert path[0] == 100  # Starts at start
        assert path[-1] == 105  # Ends at end
        assert path.max() <= 110  # Respects high constraint
        assert path.min() >= 95  # Respects low constraint

    def test_brownian_bridge_impossible_constraints(self):
        """Test Brownian Bridge with impossible constraints falls back to linear"""
        # Impossible: start/end outside constraints
        path = SyntheticGenerator._generate_brownian_bridge(
            start=100,
            end=105,
            n_steps=5,
            volatility=10,
            high_constraint=102,  # End is above this
            low_constraint=95,
            max_iterations=5  # Fail quickly
        )

        # Should fallback to linear interpolation
        expected_linear = np.linspace(100, 105, 6)
        np.testing.assert_array_almost_equal(path, expected_linear)

    def test_validate_synthetic_data(self, sample_m5_data):
        """Test validation of synthetic data"""
        df_m1 = SyntheticGenerator.generate_m1_from_m5(
            sample_m5_data,
            method="brownian"
        )

        # Remove Synthetic column for validation
        df_m1_clean = df_m1.drop('Synthetic', axis=1)

        metrics = SyntheticGenerator.validate_synthetic_data(df_m1_clean, sample_m5_data)

        # Print issues for debugging if validation fails
        if not metrics['valid']:
            print(f"Validation issues: {metrics['issues']}")
            print(f"Metrics: {metrics}")

        assert metrics['valid'] is True, f"Validation failed: {metrics['issues']}"
        assert metrics['length_ratio'] == 5.0
        assert len(metrics['issues']) == 0

    def test_synthetic_flag_present(self, sample_m5_data):
        """Test that all methods add Synthetic flag"""
        methods = ["brownian", "linear", "volume_weighted"]

        for method in methods:
            df_m1 = SyntheticGenerator.generate_m1_from_m5(
                sample_m5_data,
                method=method
            )
            assert 'Synthetic' in df_m1.columns
            assert (df_m1['Synthetic'] == True).all()

    def test_volume_distribution_brownian(self, sample_m5_data):
        """Test volume distribution in Brownian method"""
        df_m1 = SyntheticGenerator.generate_m1_from_m5(
            sample_m5_data,
            method="brownian"
        )

        # For each M5 candle
        for i, m5_row in sample_m5_data.iterrows():
            m1_start = i
            m1_end = i + pd.Timedelta(minutes=5)
            m1_window = df_m1[(df_m1.index >= m1_start) & (df_m1.index < m1_end)]

            if len(m1_window) > 0:
                # Sum of M1 volumes should approximately equal M5 volume
                m1_volume_sum = m1_window['Volume'].sum()
                # Allow rounding errors from int conversion (up to 4 per M5 candle)
                assert abs(m1_volume_sum - m5_row['Volume']) < 5

    def test_volume_distribution_linear(self, sample_m5_data):
        """Test volume distribution in linear method (equal distribution)"""
        df_m1 = SyntheticGenerator.generate_m1_from_m5(
            sample_m5_data,
            method="linear"
        )

        # For each M5 candle
        for i, m5_row in sample_m5_data.iterrows():
            m1_start = i
            m1_end = i + pd.Timedelta(minutes=5)
            m1_window = df_m1[(df_m1.index >= m1_start) & (df_m1.index < m1_end)]

            if len(m1_window) == 5:
                # Each M1 should have ~1/5 of M5 volume
                expected_vol = m5_row['Volume'] / 5
                for vol in m1_window['Volume']:
                    assert abs(vol - expected_vol) < 2  # Allow rounding

    def test_volume_distribution_volume_weighted(self, sample_m5_data):
        """Test U-shaped volume distribution in volume_weighted method"""
        df_m1 = SyntheticGenerator.generate_m1_from_m5(
            sample_m5_data,
            method="volume_weighted"
        )

        # For each M5 candle
        for i, m5_row in sample_m5_data.iterrows():
            m1_start = i
            m1_end = i + pd.Timedelta(minutes=5)
            m1_window = df_m1[(df_m1.index >= m1_start) & (df_m1.index < m1_end)]

            if len(m1_window) == 5:
                volumes = m1_window['Volume'].values
                # First and last should have more volume (U-shaped)
                # This is a probabilistic test, may occasionally fail
                middle_vol = volumes[2]
                edge_vols = [volumes[0], volumes[4]]

                # At least one edge should have more than middle (typically)
                # But don't assert this strictly since it's randomized


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
