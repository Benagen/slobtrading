"""
Parameter Optimization with Walk-Forward Analysis.

Finds optimal strategy parameters using walk-forward analysis to avoid overfitting.
Tests parameters on rolling windows: train on past data, test on forward period.

Example:
    optimizer = ParameterOptimizer(df, setup_finder, backtester)
    results = optimizer.optimize(param_grid, train_months=6, test_months=1)
    best_params = results.iloc[0]  # Best by stability
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Callable, Optional, Tuple
from itertools import product
from datetime import datetime, timedelta
import logging
from tqdm import tqdm

logger = logging.getLogger(__name__)


class ParameterOptimizer:
    """Walk-forward parameter optimization for trading strategy"""

    def __init__(self, df: pd.DataFrame, setup_finder, backtester_class,
                 initial_capital: float = 50000.0):
        """
        Initialize optimizer.

        Args:
            df: Full OHLCV dataframe
            setup_finder: Setup finder instance (with find_setups method)
            backtester_class: Backtester class (will instantiate with setups)
            initial_capital: Starting capital
        """
        self.df = df
        self.setup_finder = setup_finder
        self.backtester_class = backtester_class
        self.initial_capital = initial_capital

    def optimize(
        self,
        param_grid: Dict[str, List],
        train_months: int = 6,
        test_months: int = 1,
        metric: str = 'sharpe_ratio',
        min_trades: int = 10,
        verbose: bool = True
    ) -> pd.DataFrame:
        """
        Run walk-forward optimization.

        Strategy:
        1. Split data into rolling windows (e.g. 6 months train, 1 month test)
        2. For each window:
           - Test all parameter combinations on training period
           - Apply best parameters to test period
        3. Calculate stability: mean / std of test period metrics

        Args:
            param_grid: Dict of param_name -> [values to test]
                Example: {'atr_multiplier_min': [0.4, 0.5, 0.6],
                         'atr_multiplier_max': [1.5, 2.0, 2.5],
                         'percentile': [85, 90, 95]}
            train_months: Training window size (months)
            test_months: Test window size (months)
            metric: Metric to optimize ('sharpe_ratio', 'win_rate', 'profit_factor')
            min_trades: Minimum trades required in test period
            verbose: Print progress

        Returns:
            DataFrame with results sorted by stability
        """
        if verbose:
            print(f"\n{'='*80}")
            print(f"Parameter Optimization - Walk-Forward Analysis")
            print(f"{'='*80}")
            print(f"Train window: {train_months} months")
            print(f"Test window:  {test_months} months")
            print(f"Metric:       {metric}")
            print(f"Parameters:   {list(param_grid.keys())}")
            print(f"{'='*80}\n")

        # Generate all parameter combinations
        param_combinations = self._generate_combinations(param_grid)

        if verbose:
            print(f"Testing {len(param_combinations)} parameter combinations...\n")

        # Create walk-forward windows
        windows = self._create_windows(train_months, test_months)

        if verbose:
            print(f"Walk-forward windows: {len(windows)}\n")

        # Test each parameter combination on all windows
        results = []

        iterator = tqdm(param_combinations) if verbose else param_combinations

        for params in iterator:
            if verbose and not isinstance(iterator, tqdm):
                print(f"Testing params: {params}")

            window_metrics = []

            for train_df, test_df, window_idx in windows:
                # Run backtest on test period with these params
                try:
                    test_metric = self._backtest_with_params(
                        test_df, params, metric, min_trades
                    )

                    if test_metric is not None:
                        window_metrics.append(test_metric)

                except Exception as e:
                    logger.warning(f"Window {window_idx} failed with params {params}: {e}")
                    continue

            # Calculate stability across windows
            if len(window_metrics) > 0:
                mean_metric = np.mean(window_metrics)
                std_metric = np.std(window_metrics)
                stability = mean_metric / std_metric if std_metric > 0 else 0

                results.append({
                    **params,
                    f'mean_{metric}': mean_metric,
                    f'std_{metric}': std_metric,
                    'stability': stability,
                    'n_windows': len(window_metrics),
                    'window_metrics': window_metrics
                })

        # Convert to DataFrame and sort by stability
        df_results = pd.DataFrame(results)

        if len(df_results) == 0:
            raise ValueError("No valid results from optimization")

        df_results = df_results.sort_values('stability', ascending=False)

        if verbose:
            self._print_results(df_results, param_grid, metric)

        return df_results

    def _generate_combinations(self, param_grid: Dict[str, List]) -> List[Dict]:
        """Generate all parameter combinations"""
        keys = param_grid.keys()
        values = param_grid.values()

        combinations = []
        for combination in product(*values):
            combinations.append(dict(zip(keys, combination)))

        return combinations

    def _create_windows(
        self,
        train_months: int,
        test_months: int
    ) -> List[Tuple[pd.DataFrame, pd.DataFrame, int]]:
        """
        Create rolling windows for walk-forward analysis.

        Returns:
            List of (train_df, test_df, window_idx) tuples
        """
        windows = []

        start_date = self.df.index.min()
        end_date = self.df.index.max()

        current_date = start_date
        window_idx = 0

        while True:
            # Training period
            train_start = current_date
            train_end = train_start + pd.DateOffset(months=train_months)

            # Test period
            test_start = train_end
            test_end = test_start + pd.DateOffset(months=test_months)

            # Check if we have enough data
            if test_end > end_date:
                break

            # Extract windows
            train_df = self.df.loc[train_start:train_end]
            test_df = self.df.loc[test_start:test_end]

            windows.append((train_df, test_df, window_idx))

            # Move forward by test_months (rolling)
            current_date = test_start
            window_idx += 1

        return windows

    def _backtest_with_params(
        self,
        df: pd.DataFrame,
        params: Dict,
        metric: str,
        min_trades: int
    ) -> Optional[float]:
        """
        Run backtest with specific parameters.

        Args:
            df: Data to backtest on
            params: Parameter dict
            metric: Metric to return
            min_trades: Minimum trades required

        Returns:
            Metric value, or None if insufficient trades
        """
        # Update setup_finder parameters
        self._apply_params_to_finder(params)

        # Find setups
        setups = self.setup_finder.find_setups(df)

        if len(setups) < min_trades:
            return None

        # Run backtest
        backtester = self.backtester_class(
            df=df,
            setups=setups,
            initial_capital=self.initial_capital
        )

        trades = backtester.run_backtest()

        if len(trades) < min_trades:
            return None

        # Calculate metric
        return self._calculate_metric(trades, metric)

    def _apply_params_to_finder(self, params: Dict):
        """Apply parameters to setup finder"""
        for param_name, param_value in params.items():
            if hasattr(self.setup_finder, param_name):
                setattr(self.setup_finder, param_name, param_value)
            else:
                logger.warning(f"Setup finder has no parameter: {param_name}")

    def _calculate_metric(self, trades: List[Dict], metric: str) -> float:
        """Calculate performance metric from trades"""
        if len(trades) == 0:
            return 0.0

        # Calculate basic metrics
        df_trades = pd.DataFrame(trades)

        wins = df_trades[df_trades['result'] == 'WIN']
        losses = df_trades[df_trades['result'] == 'LOSS']

        n_wins = len(wins)
        n_losses = len(losses)
        n_total = len(df_trades)

        win_rate = n_wins / n_total if n_total > 0 else 0

        # PnL
        pnl_series = df_trades['pnl']
        total_pnl = pnl_series.sum()

        # Sharpe ratio (assuming daily returns)
        if len(pnl_series) > 1:
            returns = pnl_series / self.initial_capital
            sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
        else:
            sharpe = 0

        # Profit factor
        gross_profit = wins['pnl'].sum() if n_wins > 0 else 0
        gross_loss = abs(losses['pnl'].sum()) if n_losses > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # Return requested metric
        metrics_map = {
            'sharpe_ratio': sharpe,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'total_pnl': total_pnl,
            'avg_win': wins['pnl'].mean() if n_wins > 0 else 0,
            'avg_loss': losses['pnl'].mean() if n_losses > 0 else 0
        }

        return metrics_map.get(metric, 0)

    def _print_results(self, df_results: pd.DataFrame, param_grid: Dict, metric: str):
        """Print optimization results"""
        print(f"\n{'='*80}")
        print(f"Optimization Results (Top 10 by Stability)")
        print(f"{'='*80}\n")

        # Show top 10
        top_10 = df_results.head(10)

        param_cols = list(param_grid.keys())
        metric_cols = [f'mean_{metric}', f'std_{metric}', 'stability', 'n_windows']

        display_cols = param_cols + metric_cols

        print(top_10[display_cols].to_string(index=False))
        print(f"\n{'='*80}\n")

        # Best parameters
        best = df_results.iloc[0]

        print("BEST PARAMETERS (by stability):")
        for param in param_cols:
            print(f"  {param:30s} = {best[param]}")

        print(f"\nPERFORMANCE:")
        print(f"  Mean {metric:25s} = {best[f'mean_{metric}']:.4f}")
        print(f"  Std {metric:26s} = {best[f'std_{metric}']:.4f}")
        print(f"  Stability:                    = {best['stability']:.4f}")
        print(f"  Valid windows:                = {best['n_windows']}")
        print(f"\n{'='*80}\n")

    def optimize_threshold(
        self,
        classifier,
        df: pd.DataFrame,
        setups: List[Dict],
        trades: List[Dict],
        thresholds: List[float] = None,
        verbose: bool = True
    ) -> pd.DataFrame:
        """
        Optimize ML probability threshold.

        Args:
            classifier: Trained SetupClassifier
            df: OHLCV data
            setups: All setups found
            trades: Corresponding trade results
            thresholds: List of thresholds to test (default: 0.5 to 0.9 in 0.05 steps)
            verbose: Print progress

        Returns:
            DataFrame with results sorted by Sharpe ratio
        """
        if thresholds is None:
            thresholds = np.arange(0.5, 0.91, 0.05).tolist()

        if verbose:
            print(f"\n{'='*80}")
            print(f"ML Probability Threshold Optimization")
            print(f"{'='*80}")
            print(f"Testing {len(thresholds)} thresholds: {thresholds}")
            print(f"Total setups: {len(setups)}")
            print(f"{'='*80}\n")

        from slob.ml import MLFilteredBacktester
        from slob.features import FeatureEngineer

        results = []

        for threshold in thresholds:
            # Create filtered backtester
            ml_backtester = MLFilteredBacktester(
                classifier=classifier,
                probability_threshold=threshold
            )

            # Filter setups
            filtered_setups, probabilities, _ = ml_backtester.filter_setups(
                df, setups, verbose=False
            )

            # Get corresponding trades
            filtered_trades = [trades[i] for i, prob in enumerate(probabilities)
                              if prob >= threshold]

            if len(filtered_trades) == 0:
                continue

            # Calculate metrics
            df_trades = pd.DataFrame(filtered_trades)

            n_total = len(df_trades)
            n_wins = len(df_trades[df_trades['result'] == 'WIN'])
            win_rate = n_wins / n_total

            pnl_series = df_trades['pnl']
            total_pnl = pnl_series.sum()

            returns = pnl_series / self.initial_capital
            sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0

            results.append({
                'threshold': threshold,
                'n_setups': len(filtered_setups),
                'pct_kept': len(filtered_setups) / len(setups) * 100,
                'win_rate': win_rate,
                'total_pnl': total_pnl,
                'sharpe_ratio': sharpe,
                'avg_pnl': pnl_series.mean()
            })

        df_results = pd.DataFrame(results).sort_values('sharpe_ratio', ascending=False)

        if verbose:
            print(df_results.to_string(index=False))
            print(f"\n{'='*80}\n")

            best = df_results.iloc[0]
            print(f"BEST THRESHOLD: {best['threshold']:.2f}")
            print(f"  Setups kept:  {best['n_setups']} ({best['pct_kept']:.1f}%)")
            print(f"  Win rate:     {best['win_rate']:.1%}")
            print(f"  Sharpe ratio: {best['sharpe_ratio']:.3f}")
            print(f"  Total PnL:    {best['total_pnl']:.2f} SEK")
            print(f"\n{'='*80}\n")

        return df_results


def example_usage():
    """Example of how to use ParameterOptimizer"""
    # Placeholder - requires actual setup finder and backtester
    print("Example usage:")
    print("""
    from slob.data import DataAggregator
    from slob.patterns import SetupFinder
    from slob.backtest import Backtester

    # Get data
    df = aggregator.fetch_data("ES=F", "2024-01-01", "2024-12-31", interval="1m")

    # Define parameter grid
    param_grid = {
        'atr_multiplier_min': [0.4, 0.5, 0.6],
        'atr_multiplier_max': [1.5, 2.0, 2.5],
        'percentile': [85, 90, 95],
        'min_consol_duration': [15, 20],
        'max_consol_duration': [30, 35]
    }

    # Initialize optimizer
    setup_finder = SetupFinder()
    optimizer = ParameterOptimizer(df, setup_finder, Backtester)

    # Run optimization
    results = optimizer.optimize(
        param_grid,
        train_months=6,
        test_months=1,
        metric='sharpe_ratio',
        verbose=True
    )

    # Apply best parameters
    best_params = results.iloc[0]
    for param_name, value in best_params.items():
        if param_name in param_grid:
            setattr(setup_finder, param_name, value)

    # ML threshold optimization
    threshold_results = optimizer.optimize_threshold(
        classifier=trained_classifier,
        df=df,
        setups=all_setups,
        trades=all_trades,
        verbose=True
    )
    """)


if __name__ == "__main__":
    example_usage()
