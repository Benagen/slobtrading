"""
5/1 SLOB Backtester Engine

Simulates trading the 5/1 SLOB strategy on historical data with:
- Proper execution simulation (no look-ahead bias)
- Risk management integration
- ML filtering
- News calendar filtering
- Comprehensive trade tracking

Example:
    finder = SetupFinder()
    backtester = Backtester(df, finder, initial_capital=50000)
    results = backtester.run()
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import logging

from slob.backtest.setup_finder import SetupFinder
from slob.backtest.risk_manager import RiskManager
from slob.features import FeatureEngineer
from slob.utils import NewsCalendar

logger = logging.getLogger(__name__)


class Backtester:
    """Backtests 5/1 SLOB strategy on historical data"""

    def __init__(
        self,
        df: pd.DataFrame,
        setup_finder: SetupFinder,
        initial_capital: float = 50000.0,
        risk_manager: Optional[RiskManager] = None,
        ml_classifier=None,
        ml_threshold: float = 0.70,
        news_calendar: Optional[NewsCalendar] = None,
        use_ml_filter: bool = True,
        use_news_filter: bool = True
    ):
        """
        Initialize Backtester.

        Args:
            df: OHLCV DataFrame with datetime index
            setup_finder: SetupFinder instance
            initial_capital: Starting capital (SEK)
            risk_manager: RiskManager instance (optional)
            ml_classifier: Trained ML classifier (optional)
            ml_threshold: ML probability threshold (default 0.70)
            news_calendar: NewsCalendar instance (optional)
            use_ml_filter: Enable ML filtering
            use_news_filter: Enable news calendar filtering
        """
        self.df = df
        self.setup_finder = setup_finder
        self.initial_capital = initial_capital

        # Risk manager
        if risk_manager is None:
            self.risk_manager = RiskManager(
                initial_capital=initial_capital,
                max_risk_per_trade=0.02
            )
        else:
            self.risk_manager = risk_manager

        # ML filtering
        self.ml_classifier = ml_classifier
        self.ml_threshold = ml_threshold
        self.use_ml_filter = use_ml_filter and ml_classifier is not None

        # News filtering
        if news_calendar is None:
            self.news_calendar = NewsCalendar()
        else:
            self.news_calendar = news_calendar
        self.use_news_filter = use_news_filter

        # Results tracking
        self.setups = []
        self.trades = []
        self.rejected_setups = []

    def run(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        verbose: bool = True
    ) -> Dict:
        """
        Run backtest.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            verbose: Print progress

        Returns:
            Dict with results: {
                'setups': List of all setups found,
                'trades': List of executed trades,
                'rejected_setups': List of rejected setups with reasons,
                'metrics': Performance metrics
            }
        """
        if verbose:
            print(f"\n{'='*80}")
            print(f"5/1 SLOB BACKTEST")
            print(f"{'='*80}")
            print(f"Period: {start_date or 'start'} to {end_date or 'end'}")
            print(f"Initial capital: {self.initial_capital:,.0f} SEK")
            print(f"ML filter: {'ON' if self.use_ml_filter else 'OFF'}")
            print(f"News filter: {'ON' if self.use_news_filter else 'OFF'}")
            print(f"{'='*80}\n")

        # Find all setups
        if verbose:
            print("Finding setups...")

        self.setups = self.setup_finder.find_setups(
            self.df,
            start_date=start_date,
            end_date=end_date,
            verbose=verbose
        )

        if verbose:
            print(f"\nTotal setups found: {len(self.setups)}")

        # Filter setups
        filtered_setups = self._filter_setups(self.setups, verbose=verbose)

        if verbose:
            print(f"Setups after filtering: {len(filtered_setups)}")

        # Execute trades
        if verbose:
            print(f"\nExecuting trades...")

        for setup in filtered_setups:
            trade = self._execute_trade(setup)
            self.trades.append(trade)

            # Update risk manager
            self.risk_manager.update_after_trade(trade)

            if verbose:
                result_str = "WIN" if trade['result'] == 'WIN' else "LOSS"
                print(f"  Trade #{len(self.trades)}: {trade['entry_time']} → {result_str} "
                      f"({trade['pnl']:+.0f} SEK, RR: {trade['rr_achieved']:.2f})")

        # Calculate metrics
        metrics = self._calculate_metrics()

        if verbose:
            self._print_summary(metrics)

        return {
            'setups': self.setups,
            'trades': self.trades,
            'rejected_setups': self.rejected_setups,
            'metrics': metrics
        }

    def _filter_setups(self, setups: List[Dict], verbose: bool = False) -> List[Dict]:
        """
        Filter setups through ML and news calendar.

        Returns:
            List of filtered setups
        """
        if verbose:
            print(f"\nFiltering setups...")

        filtered = []
        rejection_reasons = {
            'ml_filter': 0,
            'news_filter': 0,
            'passed': 0
        }

        for setup in setups:
            rejected = False
            reason = None

            # ML filtering
            if self.use_ml_filter:
                ml_prob = self._get_ml_probability(setup)

                if ml_prob < self.ml_threshold:
                    rejected = True
                    reason = f'ml_filter (prob={ml_prob:.2f} < {self.ml_threshold})'
                    rejection_reasons['ml_filter'] += 1
                else:
                    # Add ML prob to setup
                    setup['ml_probability'] = ml_prob

            # News filtering
            if not rejected and self.use_news_filter:
                entry_time = self.df.index[setup['entry_idx']]

                if not self.news_calendar.is_trading_allowed(entry_time):
                    rejected = True
                    reason = 'news_filter'
                    rejection_reasons['news_filter'] += 1

            if rejected:
                self.rejected_setups.append({
                    **setup,
                    'rejection_reason': reason
                })
            else:
                filtered.append(setup)
                rejection_reasons['passed'] += 1

        if verbose:
            print(f"  Total setups:      {len(setups)}")
            print(f"  Rejected (ML):     {rejection_reasons['ml_filter']}")
            print(f"  Rejected (News):   {rejection_reasons['news_filter']}")
            print(f"  Passed filtering:  {rejection_reasons['passed']}")

        return filtered

    def _get_ml_probability(self, setup: Dict) -> float:
        """
        Get ML probability for a setup.

        Returns:
            Win probability (0-1)
        """
        if self.ml_classifier is None:
            return 1.0

        # Extract features
        features = FeatureEngineer.extract_features(self.df, setup)

        # Convert to DataFrame
        import pandas as pd
        df_features = pd.DataFrame([features])

        # Predict
        prob = self.ml_classifier.predict_probability(df_features)[0]

        return prob

    def _execute_trade(self, setup: Dict) -> Dict:
        """
        Simulate trade execution.

        Simulates:
        - Entry at entry_price
        - SL hit or TP hit based on price action
        - Position sizing (using risk manager)
        - P&L calculation

        Returns:
            Trade dict with full details
        """
        entry_idx = setup['entry_idx']
        entry_price = setup['entry_price']
        sl_price = setup['sl_price']
        tp_price = setup['tp_price']
        direction = setup['direction']

        # Calculate position size
        atr = self._calculate_atr(entry_idx)

        sizing = self.risk_manager.calculate_position_size(
            entry_price=entry_price,
            sl_price=sl_price,
            atr=atr
        )

        # Simulate trade outcome
        # Search forward from entry to see if SL or TP hit first
        exit_idx, exit_price, exit_type = self._simulate_trade_outcome(
            entry_idx, entry_price, sl_price, tp_price, direction
        )

        # Calculate P&L
        if direction == 'SHORT':
            pnl_pips = entry_price - exit_price
        else:
            pnl_pips = exit_price - entry_price

        pnl_sek = pnl_pips * sizing['contracts']

        # Result
        result = 'WIN' if exit_type == 'TP' else 'LOSS'

        # R:R achieved
        if direction == 'SHORT':
            rr_achieved = (entry_price - exit_price) / (sl_price - entry_price) if (sl_price - entry_price) != 0 else 0
        else:
            rr_achieved = (exit_price - entry_price) / (entry_price - sl_price) if (entry_price - sl_price) != 0 else 0

        trade = {
            # Setup reference
            'setup': setup,

            # Entry
            'entry_idx': entry_idx,
            'entry_time': self.df.index[entry_idx],
            'entry_price': entry_price,

            # Exit
            'exit_idx': exit_idx,
            'exit_time': self.df.index[exit_idx],
            'exit_price': exit_price,
            'exit_type': exit_type,

            # Position
            'direction': direction,
            'contracts': sizing['contracts'],
            'position_size': sizing['position_size'],

            # Levels
            'sl_price': sl_price,
            'tp_price': tp_price,

            # Results
            'result': result,
            'pnl_pips': pnl_pips,
            'pnl': pnl_sek,
            'rr_achieved': rr_achieved,

            # Risk metrics
            'risk_pct': sizing.get('risk_pct', 0.02),
            'sizing_method': sizing['method']
        }

        return trade

    def _simulate_trade_outcome(
        self,
        entry_idx: int,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        direction: str,
        max_bars: int = 1000
    ) -> Tuple[int, float, str]:
        """
        Simulate if SL or TP gets hit first.

        Returns:
            (exit_idx, exit_price, exit_type)
        """
        for i in range(entry_idx + 1, min(entry_idx + max_bars, len(self.df))):
            candle = self.df.iloc[i]

            if direction == 'SHORT':
                # Check SL (price goes UP to SL)
                if candle['High'] >= sl_price:
                    return i, sl_price, 'SL'

                # Check TP (price goes DOWN to TP)
                if candle['Low'] <= tp_price:
                    return i, tp_price, 'TP'

            else:  # LONG
                # Check SL (price goes DOWN to SL)
                if candle['Low'] <= sl_price:
                    return i, sl_price, 'SL'

                # Check TP (price goes UP to TP)
                if candle['High'] >= tp_price:
                    return i, tp_price, 'TP'

        # If max_bars reached without hit, exit at market
        final_candle = self.df.iloc[min(entry_idx + max_bars - 1, len(self.df) - 1)]
        return len(self.df) - 1, final_candle['Close'], 'TIMEOUT'

    def _calculate_atr(self, idx: int, period: int = 14) -> float:
        """Calculate ATR at given index"""
        if idx < period:
            return 10.0  # Default fallback

        window = self.df.iloc[max(0, idx - period):idx]

        high_low = window['High'] - window['Low']
        high_close = np.abs(window['High'] - window['Close'].shift())
        low_close = np.abs(window['Low'] - window['Close'].shift())

        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.mean()

        return atr

    def _calculate_metrics(self) -> Dict:
        """Calculate performance metrics"""
        if len(self.trades) == 0:
            return {}

        df_trades = pd.DataFrame(self.trades)

        # Basic stats
        n_total = len(df_trades)
        n_wins = len(df_trades[df_trades['result'] == 'WIN'])
        n_losses = len(df_trades[df_trades['result'] == 'LOSS'])

        win_rate = n_wins / n_total if n_total > 0 else 0

        # P&L
        total_pnl = df_trades['pnl'].sum()
        avg_win = df_trades[df_trades['result'] == 'WIN']['pnl'].mean() if n_wins > 0 else 0
        avg_loss = df_trades[df_trades['result'] == 'LOSS']['pnl'].mean() if n_losses > 0 else 0

        # Profit factor
        gross_profit = df_trades[df_trades['result'] == 'WIN']['pnl'].sum() if n_wins > 0 else 0
        gross_loss = abs(df_trades[df_trades['result'] == 'LOSS']['pnl'].sum()) if n_losses > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # Risk metrics from risk manager
        risk_metrics = self.risk_manager.calculate_metrics()

        return {
            'total_trades': n_total,
            'wins': n_wins,
            'losses': n_losses,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'final_capital': self.risk_manager.current_capital,
            'total_return': (self.risk_manager.current_capital - self.initial_capital) / self.initial_capital,
            **risk_metrics
        }

    def _print_summary(self, metrics: Dict):
        """Print backtest summary"""
        print(f"\n{'='*80}")
        print(f"BACKTEST RESULTS")
        print(f"{'='*80}")
        print(f"Total Trades:     {metrics.get('total_trades', 0)}")
        print(f"Wins:             {metrics.get('wins', 0)}")
        print(f"Losses:           {metrics.get('losses', 0)}")
        print(f"Win Rate:         {metrics.get('win_rate', 0):.1%}")
        print(f"")
        print(f"Total P&L:        {metrics.get('total_pnl', 0):+,.0f} SEK")
        print(f"Avg Win:          {metrics.get('avg_win', 0):+,.0f} SEK")
        print(f"Avg Loss:         {metrics.get('avg_loss', 0):+,.0f} SEK")
        print(f"Profit Factor:    {metrics.get('profit_factor', 0):.2f}")
        print(f"")
        print(f"Final Capital:    {metrics.get('final_capital', 0):,.0f} SEK")
        print(f"Total Return:     {metrics.get('total_return', 0):+.1%}")
        print(f"")
        print(f"Sharpe Ratio:     {metrics.get('sharpe_ratio', 0):.2f}")
        print(f"Max Drawdown:     {metrics.get('max_drawdown', 0):.1%}")
        print(f"{'='*80}\n")


if __name__ == "__main__":
    print("5/1 SLOB Backtester")
    print("Use: backtester = Backtester(df, finder); results = backtester.run()")
