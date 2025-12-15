"""
Data validators for OHLCV data quality checks.

Validates:
- Required columns
- OHLC relationships
- NaN values
- Time gaps
- Outliers (price spikes)
- Zero/low volume
"""

import pandas as pd
import numpy as np
import logging
from typing import Tuple, List, Dict, Optional
from datetime import timedelta

logger = logging.getLogger(__name__)


class DataValidator:
    """Comprehensive validation for OHLCV data"""

    @staticmethod
    def validate_ohlcv(
        df: pd.DataFrame,
        strict: bool = False,
        atr_threshold: float = 5.0,
        zero_volume_threshold: float = 0.05
    ) -> Tuple[bool, List[str]]:
        """
        Comprehensive OHLCV data validation.

        Args:
            df: DataFrame to validate
            strict: If True, any issue causes validation to fail
            atr_threshold: ATR multiplier for outlier detection
            zero_volume_threshold: Max fraction of zero-volume candles (5% default)

        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []

        # Check 1: Required columns
        required_cols_issues = DataValidator._check_required_columns(df)
        if required_cols_issues:
            # Critical - can't continue without columns
            return False, required_cols_issues

        # Check 2: Empty DataFrame
        if df.empty:
            return False, ["DataFrame is empty"]

        # Check 3: DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            issues.append("Index is not DatetimeIndex")
            if strict:
                return False, issues

        # Check 4: OHLC relationships
        ohlc_issues = DataValidator._check_ohlc_relationships(df)
        issues.extend(ohlc_issues)

        # Check 5: NaN values
        nan_issues = DataValidator._check_nan_values(df)
        issues.extend(nan_issues)

        # Check 6: Time gaps
        gap_issues = DataValidator._check_time_gaps(df)
        issues.extend(gap_issues)

        # Check 7: Price outliers
        outlier_issues = DataValidator._check_price_outliers(df, atr_threshold)
        issues.extend(outlier_issues)

        # Check 8: Zero volume
        volume_issues = DataValidator._check_zero_volume(df, zero_volume_threshold)
        issues.extend(volume_issues)

        # Check 9: Negative values
        negative_issues = DataValidator._check_negative_values(df)
        issues.extend(negative_issues)

        is_valid = len(issues) == 0 or (not strict and len([i for i in issues if 'Critical' in i]) == 0)

        if issues:
            logger.warning(f"Validation found {len(issues)} issue(s): {issues}")
        else:
            logger.debug("Validation passed")

        return is_valid, issues

    @staticmethod
    def _check_required_columns(df: pd.DataFrame) -> List[str]:
        """Check if required columns are present"""
        required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            return [f"Critical: Missing required columns: {missing_columns}"]

        return []

    @staticmethod
    def _check_ohlc_relationships(df: pd.DataFrame) -> List[str]:
        """Validate OHLC price relationships"""
        issues = []

        # High must be >= max(Open, Close)
        invalid_high = (df['High'] < df[['Open', 'Close']].max(axis=1)).sum()
        if invalid_high > 0:
            issues.append(f"{invalid_high} candles have High < max(Open, Close)")

        # Low must be <= min(Open, Close)
        invalid_low = (df['Low'] > df[['Open', 'Close']].min(axis=1)).sum()
        if invalid_low > 0:
            issues.append(f"{invalid_low} candles have Low > min(Open, Close)")

        # High must be >= Low
        invalid_range = (df['High'] < df['Low']).sum()
        if invalid_range > 0:
            issues.append(f"Critical: {invalid_range} candles have High < Low")

        return issues

    @staticmethod
    def _check_nan_values(df: pd.DataFrame) -> List[str]:
        """Check for NaN values in data"""
        issues = []

        price_cols = ['Open', 'High', 'Low', 'Close']
        for col in price_cols:
            nan_count = df[col].isna().sum()
            if nan_count > 0:
                issues.append(f"{nan_count} NaN values in {col} column")

        # Volume NaN is less critical (some sources don't provide volume)
        volume_nan = df['Volume'].isna().sum()
        if volume_nan > 0:
            pct = (volume_nan / len(df)) * 100
            if pct > 10:
                issues.append(f"{volume_nan} ({pct:.1f}%) NaN values in Volume")

        return issues

    @staticmethod
    def _check_time_gaps(df: pd.DataFrame) -> List[str]:
        """Detect time gaps in the data"""
        issues = []

        if not isinstance(df.index, pd.DatetimeIndex) or len(df) < 2:
            return issues

        # Calculate time differences
        time_diffs = df.index.to_series().diff()

        # Determine expected interval (mode of time differences)
        # Ignore the first NaT value
        time_diffs_clean = time_diffs.dropna()

        if len(time_diffs_clean) == 0:
            return issues

        expected_diff = time_diffs_clean.mode()

        if len(expected_diff) == 0:
            # No clear pattern
            return issues

        expected_diff = expected_diff[0]

        # Find gaps (time diff > 2x expected)
        gaps = (time_diffs > expected_diff * 2).sum()

        if gaps > 0:
            gap_pct = (gaps / len(df)) * 100
            issues.append(
                f"{gaps} time gaps detected ({gap_pct:.1f}% of candles, "
                f"expected interval: {expected_diff})"
            )

        return issues

    @staticmethod
    def _check_price_outliers(
        df: pd.DataFrame,
        atr_threshold: float = 5.0,
        atr_period: int = 14
    ) -> List[str]:
        """Detect price outliers using ATR"""
        issues = []

        if len(df) < atr_period:
            return issues  # Not enough data for ATR calculation

        try:
            # Calculate ATR
            high_low = df['High'] - df['Low']
            high_close = np.abs(df['High'] - df['Close'].shift(1))
            low_close = np.abs(df['Low'] - df['Close'].shift(1))

            true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr = true_range.rolling(window=atr_period).mean()

            # Calculate candle range
            candle_range = df['High'] - df['Low']

            # Detect spikes (range > ATR * threshold)
            outliers = (candle_range > atr * atr_threshold).sum()

            if outliers > 0:
                outlier_pct = (outliers / len(df)) * 100
                issues.append(
                    f"{outliers} potential outliers detected "
                    f"({outlier_pct:.1f}% of candles, range > {atr_threshold}x ATR)"
                )

        except Exception as e:
            logger.warning(f"Failed to check price outliers: {e}")

        return issues

    @staticmethod
    def _check_zero_volume(
        df: pd.DataFrame,
        threshold: float = 0.05
    ) -> List[str]:
        """Check for excessive zero/low volume candles"""
        issues = []

        zero_volume = (df['Volume'] == 0).sum()

        if zero_volume > 0:
            zero_pct = (zero_volume / len(df))

            if zero_pct > threshold:
                issues.append(
                    f"{zero_volume} zero-volume candles ({zero_pct * 100:.1f}%, "
                    f"threshold: {threshold * 100:.0f}%)"
                )

        # Check for suspiciously low volume
        if df['Volume'].sum() > 0:
            median_volume = df['Volume'].median()
            very_low_volume = (df['Volume'] < median_volume * 0.01).sum()

            if very_low_volume > len(df) * 0.1:  # >10% of candles
                issues.append(
                    f"{very_low_volume} candles with very low volume "
                    f"(<1% of median)"
                )

        return issues

    @staticmethod
    def _check_negative_values(df: pd.DataFrame) -> List[str]:
        """Check for negative prices or volume"""
        issues = []

        # Negative prices
        price_cols = ['Open', 'High', 'Low', 'Close']
        for col in price_cols:
            negative_count = (df[col] < 0).sum()
            if negative_count > 0:
                issues.append(f"Critical: {negative_count} negative values in {col}")

        # Negative volume
        negative_volume = (df['Volume'] < 0).sum()
        if negative_volume > 0:
            issues.append(f"Critical: {negative_volume} negative values in Volume")

        return issues

    @staticmethod
    def get_data_quality_score(df: pd.DataFrame) -> Dict:
        """
        Calculate overall data quality score (0-100).

        Args:
            df: DataFrame to score

        Returns:
            Dict with quality metrics and overall score
        """
        if df.empty:
            return {'score': 0, 'reason': 'Empty DataFrame'}

        is_valid, issues = DataValidator.validate_ohlcv(df, strict=False)

        # Start with perfect score
        score = 100.0

        # Categorize issues and deduct points
        for issue in issues:
            if 'Critical' in issue:
                score -= 50  # Critical issues heavily penalized
            elif 'NaN' in issue:
                score -= 10
            elif 'gap' in issue.lower():
                score -= 5
            elif 'outlier' in issue.lower():
                score -= 3
            elif 'volume' in issue.lower():
                score -= 2
            else:
                score -= 5

        score = max(0, score)  # Don't go below 0

        return {
            'score': score,
            'is_valid': is_valid,
            'issue_count': len(issues),
            'issues': issues,
            'grade': DataValidator._get_grade(score)
        }

    @staticmethod
    def _get_grade(score: float) -> str:
        """Convert score to letter grade"""
        if score >= 95:
            return 'A+ (Excellent)'
        elif score >= 90:
            return 'A (Very Good)'
        elif score >= 80:
            return 'B (Good)'
        elif score >= 70:
            return 'C (Acceptable)'
        elif score >= 60:
            return 'D (Poor)'
        else:
            return 'F (Fail)'

    @staticmethod
    def validate_and_clean(
        df: pd.DataFrame,
        fill_method: str = 'ffill',
        drop_duplicates: bool = True
    ) -> Tuple[pd.DataFrame, List[str]]:
        """
        Validate and clean OHLCV data.

        Args:
            df: DataFrame to clean
            fill_method: Method to fill NaN values ('ffill', 'bfill', 'interpolate')
            drop_duplicates: Whether to drop duplicate timestamps

        Returns:
            Tuple of (cleaned_df, list_of_actions_taken)
        """
        actions = []
        df_clean = df.copy()

        # 1. Drop duplicates
        if drop_duplicates and df_clean.index.duplicated().any():
            dup_count = df_clean.index.duplicated().sum()
            df_clean = df_clean[~df_clean.index.duplicated(keep='first')]
            actions.append(f"Removed {dup_count} duplicate timestamps")

        # 2. Sort by index
        if not df_clean.index.is_monotonic_increasing:
            df_clean = df_clean.sort_index()
            actions.append("Sorted data by timestamp")

        # 3. Fill NaN values
        price_cols = ['Open', 'High', 'Low', 'Close']
        nan_counts = df_clean[price_cols].isna().sum()

        if nan_counts.any():
            if fill_method == 'ffill':
                df_clean[price_cols] = df_clean[price_cols].ffill()
            elif fill_method == 'bfill':
                df_clean[price_cols] = df_clean[price_cols].bfill()
            elif fill_method == 'interpolate':
                df_clean[price_cols] = df_clean[price_cols].interpolate(method='linear')

            actions.append(f"Filled NaN values using {fill_method}")

        # 4. Fill volume NaN with 0
        if df_clean['Volume'].isna().any():
            df_clean['Volume'] = df_clean['Volume'].fillna(0)
            actions.append("Filled NaN volumes with 0")

        # 5. Remove rows with remaining NaN in price columns
        remaining_nan = df_clean[price_cols].isna().any(axis=1).sum()
        if remaining_nan > 0:
            df_clean = df_clean.dropna(subset=price_cols)
            actions.append(f"Dropped {remaining_nan} rows with NaN values")

        return df_clean, actions
