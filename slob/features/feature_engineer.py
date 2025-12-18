"""
Feature Engineering for 5/1 SLOB ML Classifier.

Extracts ~35 features from each setup for ML-based filtering.

Feature Categories:
- Volume (8 features)
- Volatility (7 features)
- Temporal (8 features)
- Price Action (8 features)
- Pattern Quality (4 features)
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """Extract features from trading setups for ML classification"""

    @staticmethod
    def extract_features(
        df: pd.DataFrame,
        setup: Dict,
        lookback: int = 100
    ) -> Dict[str, float]:
        """
        Extract all features from a single setup.

        Args:
            df: OHLCV DataFrame
            setup: Setup dict with keys:
                - liq1_idx: LIQ #1 index
                - liq2_idx: LIQ #2 index
                - entry_idx: Entry index
                - lse_high: LSE High level
                - lse_low: LSE Low level
                - entry_price: Entry price
                - sl_level: Stop loss level
                - tp_level: Take profit level
                - consolidation: Dict from consolidation detector
                - liq1_result: Dict from liquidity detector (LIQ #1)
                - liq2_result: Dict from liquidity detector (LIQ #2)
                - nowick_candle: Series (no-wick candle)
                - nowick_idx: Index of no-wick candle
            lookback: Historical lookback period

        Returns:
            Dict with feature name -> value
        """
        features = {}

        # Extract all feature categories
        features.update(FeatureEngineer._extract_volume_features(df, setup, lookback))
        features.update(FeatureEngineer._extract_volatility_features(df, setup, lookback))
        features.update(FeatureEngineer._extract_temporal_features(df, setup))
        features.update(FeatureEngineer._extract_price_action_features(df, setup))
        features.update(FeatureEngineer._extract_pattern_quality_features(setup))

        return features

    @staticmethod
    def _extract_volume_features(
        df: pd.DataFrame,
        setup: Dict,
        lookback: int
    ) -> Dict[str, float]:
        """Extract volume-based features"""
        features = {}

        liq1_idx = setup.get('liq1_idx')
        liq2_idx = setup.get('liq2_idx')
        entry_idx = setup.get('entry_idx')
        nowick_idx = setup.get('nowick_idx')

        if liq1_idx is None or liq2_idx is None:
            # Return zeros if missing data
            return {
                'vol_liq1_ratio': 0.0,
                'vol_liq2_ratio': 0.0,
                'vol_entry_ratio': 0.0,
                'vol_consol_trend': 0.0,
                'vol_consol_mean': 0.0,
                'vol_spike_magnitude': 0.0,
                'vol_distribution_skew': 0.0,
                'vol_at_nowick': 0.0
            }

        # Calculate average volume
        vol_start = max(0, liq1_idx - lookback)
        vol_window = df.iloc[vol_start:liq1_idx]
        avg_volume = vol_window['Volume'].mean() if len(vol_window) > 0 else 1.0

        # 1. LIQ #1 volume ratio
        features['vol_liq1_ratio'] = df.iloc[liq1_idx]['Volume'] / avg_volume if avg_volume > 0 else 1.0

        # 2. LIQ #2 volume ratio
        features['vol_liq2_ratio'] = df.iloc[liq2_idx]['Volume'] / avg_volume if avg_volume > 0 else 1.0

        # 3. Entry volume ratio
        if entry_idx is not None and entry_idx < len(df):
            features['vol_entry_ratio'] = df.iloc[entry_idx]['Volume'] / avg_volume if avg_volume > 0 else 1.0
        else:
            features['vol_entry_ratio'] = 1.0

        # 4. Consolidation volume trend (regression slope)
        consol = setup.get('consolidation', {})
        consol_start = consol.get('start_idx', liq1_idx)
        consol_end = consol.get('end_idx', liq2_idx)

        if consol_start < consol_end and consol_end <= len(df):
            consol_volumes = df.iloc[consol_start:consol_end]['Volume'].values
            if len(consol_volumes) > 1:
                x = np.arange(len(consol_volumes))
                slope, _ = np.polyfit(x, consol_volumes, 1)
                features['vol_consol_trend'] = slope / avg_volume if avg_volume > 0 else 0.0
            else:
                features['vol_consol_trend'] = 0.0
        else:
            features['vol_consol_trend'] = 0.0

        # 5. Mean consolidation volume
        if consol_start < consol_end and consol_end <= len(df):
            features['vol_consol_mean'] = df.iloc[consol_start:consol_end]['Volume'].mean() / avg_volume if avg_volume > 0 else 1.0
        else:
            features['vol_consol_mean'] = 1.0

        # 6. Volume spike magnitude (max volume in pattern)
        pattern_start = min(liq1_idx, consol_start)
        pattern_end = max(liq2_idx, consol_end, entry_idx or liq2_idx)
        if pattern_end <= len(df):
            max_volume = df.iloc[pattern_start:pattern_end]['Volume'].max()
            features['vol_spike_magnitude'] = max_volume / avg_volume if avg_volume > 0 else 1.0
        else:
            features['vol_spike_magnitude'] = 1.0

        # 7. Volume distribution skew
        if pattern_end <= len(df):
            pattern_volumes = df.iloc[pattern_start:pattern_end]['Volume'].values
            if len(pattern_volumes) > 2:
                try:
                    from scipy import stats
                    skew_val = stats.skew(pattern_volumes)
                    # Handle NaN/inf from identical values
                    if np.isnan(skew_val) or np.isinf(skew_val):
                        features['vol_distribution_skew'] = 0.0
                    else:
                        features['vol_distribution_skew'] = float(skew_val)
                except:
                    features['vol_distribution_skew'] = 0.0
            else:
                features['vol_distribution_skew'] = 0.0
        else:
            features['vol_distribution_skew'] = 0.0

        # 8. Volume at no-wick candle
        if nowick_idx is not None and nowick_idx < len(df):
            features['vol_at_nowick'] = df.iloc[nowick_idx]['Volume'] / avg_volume if avg_volume > 0 else 1.0
        else:
            features['vol_at_nowick'] = 1.0

        return features

    @staticmethod
    def _extract_volatility_features(
        df: pd.DataFrame,
        setup: Dict,
        lookback: int
    ) -> Dict[str, float]:
        """Extract volatility-based features"""
        features = {}

        liq1_idx = setup.get('liq1_idx')
        entry_idx = setup.get('entry_idx', liq1_idx)

        if liq1_idx is None or entry_idx >= len(df):
            return {
                'atr_relative': 0.0,
                'atr_percentile': 50.0,
                'consol_range_atr_ratio': 1.0,
                'bollinger_bandwidth': 0.0,
                'consol_tightness': 0.5,
                'price_volatility_cv': 0.0,
                'atr_change_rate': 0.0
            }

        # Calculate ATR at entry
        atr_start = max(0, entry_idx - lookback)
        atr_window = df.iloc[atr_start:entry_idx]

        if len(atr_window) >= 14:
            hl = atr_window['High'] - atr_window['Low']
            hc = abs(atr_window['High'] - atr_window['Close'].shift(1))
            lc = abs(atr_window['Low'] - atr_window['Close'].shift(1))
            tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
        else:
            atr = (atr_window['High'] - atr_window['Low']).mean() if len(atr_window) > 0 else 1.0

        # 1. ATR value (relative to entry price for stationarity)
        entry_price = df.iloc[entry_idx]['Close']
        features['atr_relative'] = float(atr / entry_price) if entry_price > 0 else 0.0

        # 2. ATR percentile (is market volatile?)
        if len(atr_window) >= 14:
            atr_series = tr.rolling(14).mean().dropna()
            if len(atr_series) > 0:
                percentile = (atr_series < atr).sum() / len(atr_series) * 100
                features['atr_percentile'] = float(percentile)
            else:
                features['atr_percentile'] = 50.0
        else:
            features['atr_percentile'] = 50.0

        # 3. Consolidation range / ATR ratio
        consol = setup.get('consolidation', {})
        consol_range = consol.get('range', atr)
        features['consol_range_atr_ratio'] = float(consol_range / atr) if atr > 0 else 1.0

        # 4. Bollinger bandwidth
        if len(atr_window) >= 20:
            sma = atr_window['Close'].rolling(20).mean().iloc[-1]
            std = atr_window['Close'].rolling(20).std().iloc[-1]
            if sma > 0:
                features['bollinger_bandwidth'] = float((std * 2) / sma)
            else:
                features['bollinger_bandwidth'] = 0.0
        else:
            features['bollinger_bandwidth'] = 0.0

        # 5. Consolidation tightness
        features['consol_tightness'] = float(consol.get('tightness', 0.5))

        # 6. Price volatility coefficient of variation during consolidation (stationary)
        consol_start = consol.get('start_idx', liq1_idx)
        consol_end = consol.get('end_idx', entry_idx)
        if consol_start < consol_end and consol_end <= len(df):
            consol_closes = df.iloc[consol_start:consol_end]['Close']
            if len(consol_closes) > 1:
                mean_price = consol_closes.mean()
                std_price = consol_closes.std()
                features['price_volatility_cv'] = float(std_price / mean_price) if mean_price > 0 else 0.0
            else:
                features['price_volatility_cv'] = 0.0
        else:
            features['price_volatility_cv'] = 0.0

        # 7. ATR change rate (is volatility increasing/decreasing?)
        if len(atr_window) >= 28:
            atr_recent = tr.iloc[-14:].mean()
            atr_older = tr.iloc[-28:-14].mean()
            if atr_older > 0:
                features['atr_change_rate'] = float((atr_recent - atr_older) / atr_older)
            else:
                features['atr_change_rate'] = 0.0
        else:
            features['atr_change_rate'] = 0.0

        return features

    @staticmethod
    def _extract_temporal_features(
        df: pd.DataFrame,
        setup: Dict
    ) -> Dict[str, float]:
        """Extract time-based features"""
        features = {}

        entry_idx = setup.get('entry_idx')
        liq1_idx = setup.get('liq1_idx')

        if entry_idx is None or entry_idx >= len(df):
            return {
                'hour': 15.0,
                'minute': 30.0,
                'weekday_0': 0.0, 'weekday_1': 0.0, 'weekday_2': 0.0,
                'weekday_3': 0.0, 'weekday_4': 0.0,
                'minutes_since_nyse_open': 0.0,
                'consol_duration': 20.0,
                'time_liq1_to_entry': 30.0
            }

        entry_time = df.index[entry_idx]

        # 1. Hour of day
        features['hour'] = float(entry_time.hour)

        # 2. Minute
        features['minute'] = float(entry_time.minute)

        # 3. Weekday (one-hot encoded: Mon=0, Fri=4)
        weekday = entry_time.weekday()
        for i in range(5):
            features[f'weekday_{i}'] = 1.0 if weekday == i else 0.0

        # 4. Minutes since NYSE open (15:30)
        nyse_open = entry_time.replace(hour=15, minute=30, second=0, microsecond=0)
        minutes_since = (entry_time - nyse_open).total_seconds() / 60
        features['minutes_since_nyse_open'] = float(minutes_since)

        # 5. Consolidation duration
        consol = setup.get('consolidation', {})
        consol_start = consol.get('start_idx', liq1_idx)
        consol_end = consol.get('end_idx', entry_idx)
        if consol_start is not None and consol_end is not None and consol_start < consol_end:
            features['consol_duration'] = float(consol_end - consol_start)
        else:
            features['consol_duration'] = 20.0

        # 6. Time from LIQ #1 to entry
        if liq1_idx is not None and liq1_idx < len(df):
            features['time_liq1_to_entry'] = float(entry_idx - liq1_idx)
        else:
            features['time_liq1_to_entry'] = 30.0

        return features

    @staticmethod
    def _extract_price_action_features(
        df: pd.DataFrame,
        setup: Dict
    ) -> Dict[str, float]:
        """Extract price action features"""
        features = {}

        entry_price = setup.get('entry_price', 0.0)
        lse_high = setup.get('lse_high', entry_price)
        lse_low = setup.get('lse_low', entry_price)
        sl_level = setup.get('sl_level', entry_price)
        tp_level = setup.get('tp_level', entry_price)
        nowick_candle = setup.get('nowick_candle')
        liq2_idx = setup.get('liq2_idx')

        # 1. Entry distance to LSE high (as percentage for stationarity)
        features['entry_to_lse_high_pct'] = float(abs(entry_price - lse_high) / entry_price) if entry_price > 0 else 0.0

        # 2. Entry distance to LSE low (as percentage for stationarity)
        features['entry_to_lse_low_pct'] = float(abs(entry_price - lse_low) / entry_price) if entry_price > 0 else 0.0

        # 3. Risk:Reward ratio
        risk = abs(sl_level - entry_price)
        reward = abs(tp_level - entry_price)
        if risk > 0:
            features['risk_reward_ratio'] = float(reward / risk)
        else:
            features['risk_reward_ratio'] = 2.0  # Default

        # 4. No-wick body as percentage of candle range (stationary)
        if nowick_candle is not None:
            candle_range_full = nowick_candle.get('High', 0) - nowick_candle.get('Low', 0)
            body_size = abs(nowick_candle.get('Close', 0) - nowick_candle.get('Open', 0))
            features['nowick_body_pct'] = float(body_size / candle_range_full) if candle_range_full > 0 else 0.0
        else:
            features['nowick_body_pct'] = 0.0

        # 5. No-wick wick ratio
        if nowick_candle is not None:
            candle_range = nowick_candle.get('High', 0) - nowick_candle.get('Low', 0)
            if candle_range > 0:
                upper_wick = nowick_candle.get('High', 0) - max(nowick_candle.get('Open', 0), nowick_candle.get('Close', 0))
                features['nowick_wick_ratio'] = float(upper_wick / candle_range)
            else:
                features['nowick_wick_ratio'] = 0.0
        else:
            features['nowick_wick_ratio'] = 0.0

        # 6. LIQ #2 sweep as percentage of consolidation high (stationary)
        consol = setup.get('consolidation', {})
        consol_high = consol.get('high', entry_price)
        if liq2_idx is not None and liq2_idx < len(df):
            liq2_high = df.iloc[liq2_idx]['High']
            features['liq2_sweep_pct'] = float((liq2_high - consol_high) / consol_high) if consol_high > 0 else 0.0
        else:
            features['liq2_sweep_pct'] = 0.0

        # 7. Entry price position in consolidation (0-1)
        consol_low = consol.get('low', entry_price)
        consol_range = consol_high - consol_low
        if consol_range > 0:
            features['entry_price_consol_position'] = float((entry_price - consol_low) / consol_range)
        else:
            features['entry_price_consol_position'] = 0.5

        # 8. LSE range as percentage of LSE low (stationary)
        features['lse_range_pct'] = float((lse_high - lse_low) / lse_low) if lse_low > 0 else 0.0

        return features

    @staticmethod
    def _extract_pattern_quality_features(setup: Dict) -> Dict[str, float]:
        """Extract pattern quality features"""
        features = {}

        # 1. Consolidation quality score
        consol = setup.get('consolidation', {})
        features['consol_quality_score'] = float(consol.get('quality_score', 0.5))

        # 2. LIQ #1 confidence
        liq1_result = setup.get('liq1_result', {})
        features['liq1_confidence'] = float(liq1_result.get('score', 0.5))

        # 3. LIQ #2 confidence
        liq2_result = setup.get('liq2_result', {})
        features['liq2_confidence'] = float(liq2_result.get('score', 0.5))

        # 4. Pattern alignment score (composite)
        # Average of all quality scores
        scores = [
            features['consol_quality_score'],
            features['liq1_confidence'],
            features['liq2_confidence']
        ]
        features['pattern_alignment_score'] = float(np.mean(scores))

        return features

    @staticmethod
    def create_feature_matrix(
        df: pd.DataFrame,
        setups: List[Dict],
        trades: Optional[List[Dict]] = None,
        lookback: int = 100
    ) -> pd.DataFrame:
        """
        Create feature matrix from multiple setups.

        Args:
            df: OHLCV DataFrame
            setups: List of setup dicts
            trades: Optional list of trade results (for labels)
            lookback: Historical lookback period

        Returns:
            DataFrame with features (and 'label' column if trades provided)
        """
        X = []
        y = []

        for i, setup in enumerate(setups):
            try:
                features = FeatureEngineer.extract_features(df, setup, lookback)
                X.append(features)

                if trades is not None and i < len(trades):
                    # 1 if WIN, 0 if LOSS
                    label = 1 if trades[i].get('result') == 'WIN' else 0
                    y.append(label)
            except Exception as e:
                logger.warning(f"Failed to extract features for setup {i}: {e}")
                continue

        df_features = pd.DataFrame(X)

        if trades is not None and len(y) > 0:
            df_features['label'] = y

        return df_features

    @staticmethod
    def get_feature_names() -> List[str]:
        """
        Get list of all feature names in order.

        Returns:
            List of feature names
        """
        return [
            # Volume (8)
            'vol_liq1_ratio', 'vol_liq2_ratio', 'vol_entry_ratio',
            'vol_consol_trend', 'vol_consol_mean', 'vol_spike_magnitude',
            'vol_distribution_skew', 'vol_at_nowick',

            # Volatility (7)
            'atr_relative', 'atr_percentile', 'consol_range_atr_ratio',
            'bollinger_bandwidth', 'consol_tightness', 'price_volatility_cv',
            'atr_change_rate',

            # Temporal (10)
            'hour', 'minute', 'weekday_0', 'weekday_1', 'weekday_2',
            'weekday_3', 'weekday_4', 'minutes_since_nyse_open',
            'consol_duration', 'time_liq1_to_entry',

            # Price Action (8)
            'entry_to_lse_high_pct', 'entry_to_lse_low_pct', 'risk_reward_ratio',
            'nowick_body_pct', 'nowick_wick_ratio', 'liq2_sweep_pct',
            'entry_price_consol_position', 'lse_range_pct',

            # Pattern Quality (4)
            'consol_quality_score', 'liq1_confidence', 'liq2_confidence',
            'pattern_alignment_score'
        ]
