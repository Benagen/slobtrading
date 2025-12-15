"""
ML-Filtered Backtester.

Filters trading setups using ML classifier before backtesting.
Compares filtered vs unfiltered performance.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
import logging

from .setup_classifier import SetupClassifier
from ..features import FeatureEngineer

logger = logging.getLogger(__name__)


class MLFilteredBacktester:
    """Backtest with ML-based setup filtering"""

    def __init__(
        self,
        classifier: SetupClassifier,
        probability_threshold: float = 0.7,
        lookback: int = 100
    ):
        """
        Initialize ML-Filtered Backtester.

        Args:
            classifier: Trained SetupClassifier
            probability_threshold: Minimum ML probability to accept setup (0-1)
            lookback: Lookback for feature extraction
        """
        self.classifier = classifier
        self.probability_threshold = probability_threshold
        self.lookback = lookback
        
        if not classifier.is_trained:
            raise ValueError("Classifier must be trained before use")

    def filter_setups(
        self,
        df: pd.DataFrame,
        setups: List[Dict],
        verbose: bool = True
    ) -> Tuple[List[Dict], List[float], pd.DataFrame]:
        """
        Filter setups using ML classifier.

        Args:
            df: OHLCV DataFrame
            setups: List of setup dicts
            verbose: Print filtering info

        Returns:
            Tuple of:
                - filtered_setups: List of accepted setups
                - probabilities: ML probabilities for all setups
                - df_features: Feature DataFrame (for analysis)
        """
        logger.info(f"Filtering {len(setups)} setups with ML (threshold={self.probability_threshold})...")

        # Extract features
        df_features = FeatureEngineer.create_feature_matrix(
            df, setups, trades=None, lookback=self.lookback
        )

        # Get ML predictions
        probabilities = self.classifier.predict_probability(df_features)

        # Filter setups
        filtered_setups = []
        rejected_count = 0

        for i, (setup, prob) in enumerate(zip(setups, probabilities)):
            if prob >= self.probability_threshold:
                # Accept setup
                setup_with_ml = setup.copy()
                setup_with_ml['ml_probability'] = float(prob)
                filtered_setups.append(setup_with_ml)
                
                if verbose:
                    logger.debug(f"✓ Setup {i}: prob={prob:.3f} (ACCEPTED)")
            else:
                rejected_count += 1
                if verbose:
                    logger.debug(f"✗ Setup {i}: prob={prob:.3f} (REJECTED)")

        if verbose:
            print(f"\n{'='*70}")
            print(f"ML Filtering Results:")
            print(f"{'='*70}")
            print(f"Total setups:      {len(setups)}")
            print(f"Accepted setups:   {len(filtered_setups)} ({len(filtered_setups)/len(setups)*100:.1f}%)")
            print(f"Rejected setups:   {rejected_count} ({rejected_count/len(setups)*100:.1f}%)")
            print(f"Probability range: {probabilities.min():.3f} - {probabilities.max():.3f}")
            print(f"Mean probability:  {probabilities.mean():.3f}")
            print(f"{'='*70}\n")

        return filtered_setups, probabilities.tolist(), df_features

    def backtest_comparison(
        self,
        df: pd.DataFrame,
        setups: List[Dict],
        trades: List[Dict],
        execute_trade_func,
        verbose: bool = True
    ) -> Dict:
        """
        Compare filtered vs unfiltered backtest performance.

        Args:
            df: OHLCV DataFrame
            setups: List of setups
            trades: List of actual trade results
            execute_trade_func: Function to execute trades (setup -> trade result)
            verbose: Print comparison

        Returns:
            Dict with comparison metrics:
                - unfiltered_*: Unfiltered backtest metrics
                - filtered_*: Filtered backtest metrics
                - improvement_*: Improvement metrics
        """
        logger.info("Running filtered vs unfiltered backtest comparison...")

        # 1. Unfiltered backtest
        logger.info("\n1. Running UNFILTERED backtest...")
        unfiltered_results = self._calculate_metrics(trades, "Unfiltered")

        # 2. Filter setups
        filtered_setups, probabilities, df_features = self.filter_setups(
            df, setups, verbose=False
        )

        # 3. Get filtered trades
        # Match filtered setups to their actual trade results
        filtered_trades = []
        for setup in filtered_setups:
            # Find matching trade by comparing indices
            for i, original_setup in enumerate(setups):
                if self._setups_equal(setup, original_setup):
                    if i < len(trades):
                        trade_with_ml = trades[i].copy()
                        trade_with_ml['ml_probability'] = setup.get('ml_probability', 0.0)
                        filtered_trades.append(trade_with_ml)
                    break

        # 4. Filtered backtest
        logger.info(f"\n2. Running FILTERED backtest ({len(filtered_trades)} trades)...")
        filtered_results = self._calculate_metrics(filtered_trades, "Filtered")

        # 5. Calculate improvements
        improvements = {}
        for key in ['win_rate', 'total_pnl', 'avg_win', 'avg_loss', 'profit_factor', 'sharpe_ratio']:
            unfilt_val = unfiltered_results.get(key, 0)
            filt_val = filtered_results.get(key, 0)
            
            if unfilt_val != 0:
                improvement = ((filt_val - unfilt_val) / abs(unfilt_val)) * 100
            else:
                improvement = 0
            
            improvements[f'{key}_improvement'] = improvement

        if verbose:
            self._print_comparison(unfiltered_results, filtered_results, improvements)

        return {
            **{f'unfiltered_{k}': v for k, v in unfiltered_results.items()},
            **{f'filtered_{k}': v for k, v in filtered_results.items()},
            **improvements,
            'filter_rate': 1 - (len(filtered_trades) / len(trades)) if trades else 0,
            'probabilities': probabilities
        }

    def _calculate_metrics(self, trades: List[Dict], label: str) -> Dict:
        """Calculate backtest metrics for a list of trades"""
        if not trades:
            return {
                'num_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'sharpe_ratio': 0.0,
                'max_drawdown': 0.0
            }

        wins = [t['pnl'] for t in trades if t.get('result') == 'WIN']
        losses = [t['pnl'] for t in trades if t.get('result') == 'LOSS']

        num_wins = len(wins)
        num_losses = len(losses)
        total_trades = len(trades)

        win_rate = num_wins / total_trades if total_trades > 0 else 0.0
        total_pnl = sum([t.get('pnl', 0) for t in trades])
        
        avg_win = np.mean(wins) if wins else 0.0
        avg_loss = np.mean(losses) if losses else 0.0
        
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

        # Sharpe ratio (simplified)
        pnls = [t.get('pnl', 0) for t in trades]
        sharpe_ratio = (np.mean(pnls) / np.std(pnls)) * np.sqrt(252) if len(pnls) > 1 and np.std(pnls) > 0 else 0.0

        # Max drawdown
        cumulative_pnl = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative_pnl)
        drawdown = running_max - cumulative_pnl
        max_drawdown = np.max(drawdown) if len(drawdown) > 0 else 0.0

        return {
            'num_trades': total_trades,
            'num_wins': num_wins,
            'num_losses': num_losses,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown
        }

    def _setups_equal(self, setup1: Dict, setup2: Dict) -> bool:
        """Check if two setups are the same"""
        # Compare key fields to identify same setup
        keys_to_compare = ['liq1_idx', 'liq2_idx', 'entry_idx', 'entry_price']
        
        for key in keys_to_compare:
            if setup1.get(key) != setup2.get(key):
                return False
        
        return True

    def _print_comparison(
        self,
        unfiltered: Dict,
        filtered: Dict,
        improvements: Dict
    ):
        """Print formatted comparison"""
        print(f"\n{'='*90}")
        print(f"BACKTEST COMPARISON: Unfiltered vs ML-Filtered")
        print(f"{'='*90}")
        print(f"{'Metric':<25} {'Unfiltered':>15} {'Filtered':>15} {'Improvement':>20}")
        print(f"{'-'*90}")

        metrics = [
            ('Number of Trades', 'num_trades', None),
            ('Win Rate', 'win_rate', 'win_rate_improvement'),
            ('Total P&L', 'total_pnl', 'total_pnl_improvement'),
            ('Avg Win', 'avg_win', 'avg_win_improvement'),
            ('Avg Loss', 'avg_loss', 'avg_loss_improvement'),
            ('Profit Factor', 'profit_factor', 'profit_factor_improvement'),
            ('Sharpe Ratio', 'sharpe_ratio', 'sharpe_ratio_improvement'),
            ('Max Drawdown', 'max_drawdown', None)
        ]

        for label, key, imp_key in metrics:
            unfilt_val = unfiltered.get(key, 0)
            filt_val = filtered.get(key, 0)

            if key == 'win_rate':
                unfilt_str = f"{unfilt_val*100:.1f}%"
                filt_str = f"{filt_val*100:.1f}%"
            elif key in ['num_trades', 'num_wins', 'num_losses']:
                unfilt_str = f"{int(unfilt_val)}"
                filt_str = f"{int(filt_val)}"
            else:
                unfilt_str = f"{unfilt_val:.2f}"
                filt_str = f"{filt_val:.2f}"

            if imp_key and imp_key in improvements:
                imp = improvements[imp_key]
                imp_str = f"{imp:+.1f}%" if imp != 0 else "-"
            else:
                imp_str = "-"

            print(f"{label:<25} {unfilt_str:>15} {filt_str:>15} {imp_str:>20}")

        print(f"{'='*90}\n")

    def analyze_rejected_setups(
        self,
        df: pd.DataFrame,
        setups: List[Dict],
        trades: List[Dict],
        verbose: bool = True
    ) -> Dict:
        """
        Analyze characteristics of rejected setups.

        Args:
            df: OHLCV DataFrame
            setups: All setups
            trades: Trade results
            verbose: Print analysis

        Returns:
            Dict with rejection analysis
        """
        # Filter setups
        filtered_setups, probabilities, df_features = self.filter_setups(
            df, setups, verbose=False
        )

        # Identify rejected setups
        rejected_indices = []
        accepted_indices = []

        for i, prob in enumerate(probabilities):
            if prob < self.probability_threshold:
                rejected_indices.append(i)
            else:
                accepted_indices.append(i)

        # Analyze rejected trades
        rejected_trades = [trades[i] for i in rejected_indices if i < len(trades)]
        accepted_trades = [trades[i] for i in accepted_indices if i < len(trades)]

        rejected_win_rate = sum(1 for t in rejected_trades if t.get('result') == 'WIN') / len(rejected_trades) if rejected_trades else 0
        accepted_win_rate = sum(1 for t in accepted_trades if t.get('result') == 'WIN') / len(accepted_trades) if accepted_trades else 0

        if verbose:
            print(f"\n{'='*70}")
            print(f"Rejected Setups Analysis:")
            print(f"{'='*70}")
            print(f"Rejected setups:     {len(rejected_indices)}")
            print(f"Rejected win rate:   {rejected_win_rate*100:.1f}%")
            print(f"Accepted setups:     {len(accepted_indices)}")
            print(f"Accepted win rate:   {accepted_win_rate*100:.1f}%")
            print(f"Win rate difference: {(accepted_win_rate - rejected_win_rate)*100:+.1f}%")
            print(f"{'='*70}\n")

        return {
            'num_rejected': len(rejected_indices),
            'num_accepted': len(accepted_indices),
            'rejected_win_rate': rejected_win_rate,
            'accepted_win_rate': accepted_win_rate,
            'win_rate_diff': accepted_win_rate - rejected_win_rate,
            'rejected_probabilities': [probabilities[i] for i in rejected_indices],
            'accepted_probabilities': [probabilities[i] for i in accepted_indices]
        }

    def get_optimal_threshold(
        self,
        df: pd.DataFrame,
        setups: List[Dict],
        trades: List[Dict],
        thresholds: List[float] = None
    ) -> Tuple[float, Dict]:
        """
        Find optimal probability threshold by testing multiple values.

        Args:
            df: OHLCV DataFrame
            setups: All setups
            trades: Trade results
            thresholds: List of thresholds to test (default: 0.5-0.9 in 0.05 steps)

        Returns:
            Tuple of (optimal_threshold, metrics_dict)
        """
        if thresholds is None:
            thresholds = np.arange(0.5, 0.95, 0.05).tolist()

        logger.info(f"Testing {len(thresholds)} thresholds to find optimal...")

        # Extract features once
        df_features = FeatureEngineer.create_feature_matrix(
            df, setups, trades=None, lookback=self.lookback
        )
        probabilities = self.classifier.predict_probability(df_features)

        results = []

        for threshold in thresholds:
            # Filter with this threshold
            filtered_indices = [i for i, p in enumerate(probabilities) if p >= threshold]
            filtered_trades = [trades[i] for i in filtered_indices if i < len(trades)]

            # Calculate metrics
            metrics = self._calculate_metrics(filtered_trades, f"thresh={threshold:.2f}")
            metrics['threshold'] = threshold
            metrics['num_filtered'] = len(filtered_indices)
            metrics['filter_rate'] = 1 - (len(filtered_indices) / len(setups))

            results.append(metrics)

        # Find optimal (maximize Sharpe ratio)
        optimal = max(results, key=lambda x: x['sharpe_ratio'])

        print(f"\n{'='*70}")
        print(f"Optimal Threshold Search:")
        print(f"{'='*70}")
        print(f"Tested thresholds:   {len(thresholds)}")
        print(f"Optimal threshold:   {optimal['threshold']:.2f}")
        print(f"Optimal Sharpe:      {optimal['sharpe_ratio']:.3f}")
        print(f"Optimal win rate:    {optimal['win_rate']*100:.1f}%")
        print(f"Trades at optimal:   {optimal['num_filtered']}")
        print(f"{'='*70}\n")

        return optimal['threshold'], optimal
