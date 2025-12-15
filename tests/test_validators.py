"""
Tests for DataValidator.

Run with: pytest tests/test_validators.py -v
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime

from slob.utils import DataValidator


@pytest.fixture
def valid_data():
    """Create valid OHLCV data"""
    dates = pd.date_range('2024-01-15 15:30', periods=100, freq='1min', tz='Europe/Stockholm')

    np.random.seed(42)
    data = []
    base_price = 16000

    for i in range(100):
        base_price += np.random.randn() * 10
        open_price = base_price + np.random.randn() * 2
        close_price = open_price + np.random.randn() * 5
        high_price = max(open_price, close_price) + np.abs(np.random.randn() * 3)
        low_price = min(open_price, close_price) - np.abs(np.random.randn() * 3)

        data.append({
            'Open': open_price,
            'High': high_price,
            'Low': low_price,
            'Close': close_price,
            'Volume': np.random.randint(1000, 10000)
        })

    return pd.DataFrame(data, index=dates)


@pytest.fixture
def invalid_high_data():
    """Create data with invalid High values"""
    dates = pd.date_range('2024-01-15 15:30', periods=10, freq='1min', tz='Europe/Stockholm')

    df = pd.DataFrame({
        'Open': [100] * 10,
        'High': [99] * 10,  # Invalid: High < Open
        'Low': [98] * 10,
        'Close': [101] * 10,
        'Volume': [1000] * 10
    }, index=dates)

    return df


@pytest.fixture
def data_with_gaps():
    """Create data with time gaps"""
    dates = pd.date_range('2024-01-15 15:30', periods=50, freq='1min', tz='Europe/Stockholm')
    # Remove some dates to create gaps
    dates_with_gaps = dates.delete([10, 11, 12, 30, 31])

    np.random.seed(42)
    df = pd.DataFrame({
        'Open': np.random.randn(len(dates_with_gaps)) + 100,
        'High': np.random.randn(len(dates_with_gaps)) + 102,
        'Low': np.random.randn(len(dates_with_gaps)) + 98,
        'Close': np.random.randn(len(dates_with_gaps)) + 100,
        'Volume': np.random.randint(1000, 10000, len(dates_with_gaps))
    }, index=dates_with_gaps)

    return df


@pytest.fixture
def data_with_nan():
    """Create data with NaN values"""
    dates = pd.date_range('2024-01-15 15:30', periods=20, freq='1min', tz='Europe/Stockholm')

    df = pd.DataFrame({
        'Open': [100] * 20,
        'High': [102] * 20,
        'Low': [98] * 20,
        'Close': [100] * 20,
        'Volume': [1000] * 20
    }, index=dates)

    # Add NaN values
    df.loc[df.index[5], 'Close'] = np.nan
    df.loc[df.index[10], 'High'] = np.nan
    df.loc[df.index[15], 'Volume'] = np.nan

    return df


class TestDataValidator:
    """Test suite for DataValidator"""

    def test_valid_data_passes(self, valid_data):
        """Test that valid data passes validation"""
        is_valid, issues = DataValidator.validate_ohlcv(valid_data)

        assert is_valid is True
        assert len(issues) == 0

    def test_empty_dataframe_fails(self):
        """Test that empty DataFrame fails"""
        empty_df = pd.DataFrame()

        is_valid, issues = DataValidator.validate_ohlcv(empty_df)

        assert is_valid is False
        assert any('Missing required columns' in issue for issue in issues)

    def test_missing_columns_fails(self):
        """Test that missing columns are detected"""
        df = pd.DataFrame({
            'Open': [100],
            'Close': [101]
            # Missing High, Low, Volume
        })

        is_valid, issues = DataValidator.validate_ohlcv(df)

        assert is_valid is False
        assert any('Missing required columns' in issue for issue in issues)

    def test_invalid_high_detected(self, invalid_high_data):
        """Test that invalid High values are detected"""
        is_valid, issues = DataValidator.validate_ohlcv(invalid_high_data, strict=True)

        assert is_valid is False
        assert any('High < max(Open, Close)' in issue for issue in issues)

    def test_invalid_low_detected(self):
        """Test that invalid Low values are detected"""
        dates = pd.date_range('2024-01-15', periods=10, freq='1min')

        df = pd.DataFrame({
            'Open': [100] * 10,
            'High': [102] * 10,
            'Low': [101] * 10,  # Invalid: Low > Close
            'Close': [100] * 10,
            'Volume': [1000] * 10
        }, index=dates)

        is_valid, issues = DataValidator.validate_ohlcv(df, strict=True)

        assert is_valid is False
        assert any('Low > min(Open, Close)' in issue for issue in issues)

    def test_high_less_than_low_detected(self):
        """Test that High < Low is detected as critical"""
        dates = pd.date_range('2024-01-15', periods=10, freq='1min')

        df = pd.DataFrame({
            'Open': [100] * 10,
            'High': [98] * 10,  # Invalid: High < Low
            'Low': [99] * 10,
            'Close': [100] * 10,
            'Volume': [1000] * 10
        }, index=dates)

        is_valid, issues = DataValidator.validate_ohlcv(df)

        assert is_valid is False
        assert any('Critical' in issue and 'High < Low' in issue for issue in issues)

    def test_nan_values_detected(self, data_with_nan):
        """Test that NaN values are detected"""
        is_valid, issues = DataValidator.validate_ohlcv(data_with_nan)

        # Should detect NaN in Close and High
        assert any('NaN' in issue for issue in issues)

    def test_time_gaps_detected(self, data_with_gaps):
        """Test that time gaps are detected"""
        is_valid, issues = DataValidator.validate_ohlcv(data_with_gaps)

        # Should detect gaps
        assert any('gap' in issue.lower() for issue in issues)

    def test_negative_prices_detected(self):
        """Test that negative prices are detected"""
        dates = pd.date_range('2024-01-15', periods=10, freq='1min')

        df = pd.DataFrame({
            'Open': [-100] * 10,  # Negative prices
            'High': [102] * 10,
            'Low': [98] * 10,
            'Close': [100] * 10,
            'Volume': [1000] * 10
        }, index=dates)

        is_valid, issues = DataValidator.validate_ohlcv(df)

        assert is_valid is False
        assert any('Critical' in issue and 'negative' in issue.lower() for issue in issues)

    def test_zero_volume_detected(self):
        """Test that excessive zero volume is detected"""
        dates = pd.date_range('2024-01-15', periods=100, freq='1min')

        df = pd.DataFrame({
            'Open': [100] * 100,
            'High': [102] * 100,
            'Low': [98] * 100,
            'Close': [100] * 100,
            'Volume': [0] * 100  # All zero volume
        }, index=dates)

        is_valid, issues = DataValidator.validate_ohlcv(df, zero_volume_threshold=0.05)

        # Should detect excessive zero volume (100% > 5% threshold)
        assert any('zero-volume' in issue.lower() for issue in issues)

    def test_price_outliers_detected(self, valid_data):
        """Test that price outliers are detected"""
        # Add a spike
        spike_df = valid_data.copy()
        spike_df.iloc[50, spike_df.columns.get_loc('High')] = spike_df.iloc[50, spike_df.columns.get_loc('Close')] + 500

        is_valid, issues = DataValidator.validate_ohlcv(spike_df, atr_threshold=5.0)

        # Should detect outlier
        assert any('outlier' in issue.lower() for issue in issues)

    def test_quality_score_perfect(self, valid_data):
        """Test quality score for perfect data"""
        quality = DataValidator.get_data_quality_score(valid_data)

        assert quality['score'] >= 95
        assert quality['grade'].startswith('A')
        assert quality['is_valid'] is True
        assert quality['issue_count'] == 0

    def test_quality_score_with_issues(self, invalid_high_data):
        """Test quality score with issues"""
        quality = DataValidator.get_data_quality_score(invalid_high_data)

        assert quality['score'] < 100
        assert quality['issue_count'] > 0
        assert len(quality['issues']) > 0

    def test_quality_score_empty(self):
        """Test quality score for empty DataFrame"""
        empty_df = pd.DataFrame()
        quality = DataValidator.get_data_quality_score(empty_df)

        assert quality['score'] == 0
        assert 'Empty DataFrame' in quality['reason']

    def test_validate_and_clean_duplicates(self):
        """Test cleaning duplicate timestamps"""
        dates = pd.date_range('2024-01-15', periods=10, freq='1min')
        # Add duplicates
        dates_with_dups = dates.append(dates[:3])

        df = pd.DataFrame({
            'Open': [100] * 13,
            'High': [102] * 13,
            'Low': [98] * 13,
            'Close': [100] * 13,
            'Volume': [1000] * 13
        }, index=dates_with_dups)

        df_clean, actions = DataValidator.validate_and_clean(df, drop_duplicates=True)

        assert len(df_clean) == 10  # Duplicates removed
        assert any('duplicate' in action.lower() for action in actions)

    def test_validate_and_clean_nan(self, data_with_nan):
        """Test cleaning NaN values"""
        df_clean, actions = DataValidator.validate_and_clean(
            data_with_nan,
            fill_method='ffill'
        )

        # Should have no NaN in price columns
        price_cols = ['Open', 'High', 'Low', 'Close']
        assert df_clean[price_cols].isna().sum().sum() == 0
        assert any('NaN' in action for action in actions)

    def test_validate_and_clean_unsorted(self):
        """Test cleaning unsorted data"""
        dates = pd.date_range('2024-01-15', periods=10, freq='1min')
        # Shuffle dates
        shuffled_dates = dates[[5, 2, 8, 1, 9, 0, 4, 7, 3, 6]]

        df = pd.DataFrame({
            'Open': [100] * 10,
            'High': [102] * 10,
            'Low': [98] * 10,
            'Close': [100] * 10,
            'Volume': [1000] * 10
        }, index=shuffled_dates)

        df_clean, actions = DataValidator.validate_and_clean(df)

        assert df_clean.index.is_monotonic_increasing
        assert any('Sorted' in action for action in actions)

    def test_strict_mode(self, data_with_nan):
        """Test strict mode fails on any issue"""
        is_valid, issues = DataValidator.validate_ohlcv(data_with_nan, strict=True)

        # Strict mode should fail even on minor issues
        assert is_valid is False
        assert len(issues) > 0

    def test_non_strict_mode_allows_minor_issues(self, data_with_gaps):
        """Test non-strict mode allows minor issues"""
        is_valid, issues = DataValidator.validate_ohlcv(data_with_gaps, strict=False)

        # Non-strict mode may pass despite gaps (not critical)
        # But should still report issues
        assert len(issues) > 0

    def test_not_datetime_index(self):
        """Test validation with non-DatetimeIndex"""
        df = pd.DataFrame({
            'Open': [100] * 10,
            'High': [102] * 10,
            'Low': [98] * 10,
            'Close': [100] * 10,
            'Volume': [1000] * 10
        })  # Regular integer index

        is_valid, issues = DataValidator.validate_ohlcv(df)

        # Should detect non-DatetimeIndex but not fail if not strict
        assert any('DatetimeIndex' in issue for issue in issues)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
