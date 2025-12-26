"""
Risk Management Module.

Provides position sizing, drawdown protection, and risk metrics calculation.

Features:
- ATR-based position sizing
- Kelly Criterion
- Max drawdown protection
- Dynamic risk adjustment

Example:
    risk_mgr = RiskManager(capital=50000, max_risk_per_trade=0.02)
    position_size = risk_mgr.calculate_position_size(atr=15, entry=4800, sl=4815)
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class RiskManager:
    """Manages position sizing and risk for trading strategy"""

    def __init__(
        self,
        initial_capital: float = 50000.0,
        max_risk_per_trade: float = 0.02,  # 2% per trade
        max_drawdown_stop: float = 0.25,   # 25% max DD
        reduce_size_at_dd: float = 0.15,   # Reduce size at 15% DD
        use_kelly: bool = False,
        kelly_fraction: float = 0.5        # Half-Kelly
    ):
        """
        Initialize Risk Manager.

        Args:
            initial_capital: Starting capital (SEK)
            max_risk_per_trade: Max % of capital to risk per trade (0.02 = 2%)
            max_drawdown_stop: Max drawdown before stopping trading (0.25 = 25%)
            reduce_size_at_dd: Drawdown level to reduce position size (0.15 = 15%)
            use_kelly: Use Kelly Criterion for position sizing
            kelly_fraction: Fraction of Kelly to use (0.5 = Half-Kelly)
        """
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.max_risk_per_trade = max_risk_per_trade
        self.max_drawdown_stop = max_drawdown_stop
        self.reduce_size_at_dd = reduce_size_at_dd
        self.use_kelly = use_kelly
        self.kelly_fraction = kelly_fraction

        # Tracking
        self.equity_curve = [initial_capital]
        self.peak_equity = initial_capital
        self.current_drawdown = 0.0
        self.trades_history = []

        # State
        self.trading_enabled = True
        self.risk_reduction_active = False

    def calculate_position_size(
        self,
        entry_price: float,
        sl_price: float,
        atr: Optional[float] = None,
        current_equity: Optional[float] = None
    ) -> Dict:
        """
        Calculate position size for a trade.

        Methods:
        1. Fixed % risk: Risk 2% of capital on SL distance
        2. ATR-based: Position size inversely proportional to ATR (volatility)
        3. Kelly Criterion: Optimal position size based on edge

        Args:
            entry_price: Entry price
            sl_price: Stop loss price
            atr: Average True Range (optional, for ATR-based sizing)
            current_equity: Current account equity (optional, defaults to self.current_capital)

        Returns:
            Dict with position_size, risk_amount, contracts, method
        """
        if not self.trading_enabled:
            return {
                'position_size': 0,
                'risk_amount': 0,
                'contracts': 0,
                'method': 'trading_disabled',
                'reason': f'Max drawdown {self.current_drawdown:.1%} exceeded'
            }

        equity = current_equity or self.current_capital

        # Calculate SL distance
        sl_distance = abs(entry_price - sl_price)

        if sl_distance == 0:
            logger.warning("SL distance is zero, cannot calculate position size")
            return {'position_size': 0, 'risk_amount': 0, 'contracts': 0, 'method': 'error'}

        # Base risk amount (2% of capital)
        base_risk = equity * self.max_risk_per_trade

        # Apply risk reduction if in drawdown
        if self.risk_reduction_active:
            risk_multiplier = 0.5  # Reduce to 50% size
            base_risk *= risk_multiplier
            logger.info(f"Risk reduction active (DD: {self.current_drawdown:.1%}), "
                       f"position size reduced by 50%")

        # Method 1: Fixed % risk
        if not self.use_kelly and atr is None:
            contracts = base_risk / sl_distance
            position_size = contracts * entry_price

            return {
                'position_size': position_size,
                'risk_amount': base_risk,
                'contracts': int(contracts),
                'method': 'fixed_risk',
                'risk_pct': self.max_risk_per_trade * (0.5 if self.risk_reduction_active else 1.0)
            }

        # Method 2: ATR-based
        if atr is not None and not self.use_kelly:
            # Position size inversely proportional to volatility
            # Higher ATR = smaller position size

            # Validate ATR before division
            if atr == 0 or np.isnan(atr) or np.isinf(atr):
                logger.warning(f"Invalid ATR value ({atr}), using fallback position size of 1 contract")
                contracts = 1
            else:
                contracts = base_risk / atr

                # Safety check after calculation
                if np.isinf(contracts) or np.isnan(contracts) or contracts <= 0:
                    logger.warning(f"Invalid contracts calculation ({contracts}), using fallback of 1 contract")
                    contracts = 1

            position_size = contracts * entry_price

            return {
                'position_size': position_size,
                'risk_amount': base_risk,
                'contracts': int(contracts),
                'method': 'atr_based',
                'atr': atr,
                'risk_pct': self.max_risk_per_trade * (0.5 if self.risk_reduction_active else 1.0)
            }

        # Method 3: Kelly Criterion
        if self.use_kelly:
            kelly_size = self._calculate_kelly_size(equity)

            if kelly_size <= 0:
                logger.warning("Kelly size is negative or zero, using fixed risk instead")
                return self.calculate_position_size(entry_price, sl_price, atr=None)

            # Apply Kelly fraction (Half-Kelly)
            position_size = equity * kelly_size * self.kelly_fraction

            contracts = position_size / entry_price
            risk_amount = contracts * sl_distance

            return {
                'position_size': position_size,
                'risk_amount': risk_amount,
                'contracts': int(contracts),
                'method': 'kelly_criterion',
                'kelly_fraction': self.kelly_fraction,
                'kelly_size': kelly_size
            }

        # Default: fixed risk
        contracts = base_risk / sl_distance
        position_size = contracts * entry_price

        return {
            'position_size': position_size,
            'risk_amount': base_risk,
            'contracts': int(contracts),
            'method': 'fixed_risk'
        }

    def _calculate_kelly_size(self, equity: float) -> float:
        """
        Calculate Kelly Criterion position size.

        Formula: f* = (p*b - q) / b
        Where:
            p = win probability
            q = loss probability (1-p)
            b = win/loss ratio (avg_win / avg_loss)
            f* = fraction of capital to bet

        Returns:
            Kelly fraction (0-1)
        """
        if len(self.trades_history) < 10:
            # Not enough data, use conservative 0.02
            return 0.02

        df_trades = pd.DataFrame(self.trades_history)

        wins = df_trades[df_trades['pnl'] > 0]
        losses = df_trades[df_trades['pnl'] < 0]

        if len(wins) == 0 or len(losses) == 0:
            return 0.02

        p = len(wins) / len(df_trades)  # Win rate
        q = 1 - p

        avg_win = wins['pnl'].mean()
        avg_loss = abs(losses['pnl'].mean())

        b = avg_win / avg_loss if avg_loss > 0 else 1

        # Kelly formula
        kelly = (p * b - q) / b

        # Cap at 0.5 (very aggressive)
        kelly = max(0, min(kelly, 0.5))

        return kelly

    def update_after_trade(self, trade: Dict):
        """
        Update risk manager state after a trade.

        Args:
            trade: Trade dict with 'pnl', 'result', etc.
        """
        pnl = trade.get('pnl', 0)

        # Update capital
        self.current_capital += pnl

        # Update equity curve
        self.equity_curve.append(self.current_capital)

        # Update peak
        if self.current_capital > self.peak_equity:
            self.peak_equity = self.current_capital

        # Calculate current drawdown
        self.current_drawdown = (self.peak_equity - self.current_capital) / self.peak_equity

        # Store trade
        self.trades_history.append(trade)

        # Check risk reduction
        if self.current_drawdown >= self.reduce_size_at_dd:
            if not self.risk_reduction_active:
                self.risk_reduction_active = True
                logger.warning(f"Risk reduction activated at {self.current_drawdown:.1%} drawdown")
        else:
            if self.risk_reduction_active:
                self.risk_reduction_active = False
                logger.info(f"Risk reduction deactivated, drawdown recovered to {self.current_drawdown:.1%}")

        # Check max drawdown stop
        if self.current_drawdown >= self.max_drawdown_stop:
            if self.trading_enabled:
                self.trading_enabled = False
                logger.critical(f"TRADING STOPPED: Max drawdown {self.current_drawdown:.1%} reached")

    def get_current_state(self) -> Dict:
        """Get current risk manager state"""
        return {
            'current_capital': self.current_capital,
            'initial_capital': self.initial_capital,
            'peak_equity': self.peak_equity,
            'current_drawdown': self.current_drawdown,
            'trading_enabled': self.trading_enabled,
            'risk_reduction_active': self.risk_reduction_active,
            'total_trades': len(self.trades_history),
            'total_return': (self.current_capital - self.initial_capital) / self.initial_capital
        }

    def calculate_metrics(self) -> Dict:
        """
        Calculate comprehensive risk metrics.

        Returns:
            Dict with Sharpe, Sortino, Calmar, max DD, recovery time, etc.
        """
        if len(self.equity_curve) < 2:
            return {}

        equity_series = pd.Series(self.equity_curve)
        returns = equity_series.pct_change().dropna()

        # Sharpe Ratio (annualized, assuming daily returns)
        if returns.std() > 0:
            sharpe = returns.mean() / returns.std() * np.sqrt(252)
        else:
            sharpe = 0

        # Sortino Ratio (only downside volatility)
        downside_returns = returns[returns < 0]
        if len(downside_returns) > 0 and downside_returns.std() > 0:
            sortino = returns.mean() / downside_returns.std() * np.sqrt(252)
        else:
            sortino = 0

        # Max Drawdown
        running_max = equity_series.expanding().max()
        drawdown = (equity_series - running_max) / running_max
        max_dd = drawdown.min()

        # Max Drawdown Duration (days underwater)
        underwater = drawdown < 0
        if underwater.any():
            # Find longest continuous underwater period
            underwater_periods = underwater.astype(int).groupby(
                (underwater != underwater.shift()).cumsum()
            ).sum()
            max_dd_duration = underwater_periods.max() if len(underwater_periods) > 0 else 0
        else:
            max_dd_duration = 0

        # Calmar Ratio (return / max DD)
        total_return = (self.current_capital - self.initial_capital) / self.initial_capital
        calmar = total_return / abs(max_dd) if max_dd != 0 else 0

        # Win rate and profit factor
        if len(self.trades_history) > 0:
            df_trades = pd.DataFrame(self.trades_history)
            wins = df_trades[df_trades['pnl'] > 0]
            losses = df_trades[df_trades['pnl'] < 0]

            win_rate = len(wins) / len(df_trades)

            gross_profit = wins['pnl'].sum() if len(wins) > 0 else 0
            gross_loss = abs(losses['pnl'].sum()) if len(losses) > 0 else 0
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        else:
            win_rate = 0
            profit_factor = 0

        return {
            'sharpe_ratio': sharpe,
            'sortino_ratio': sortino,
            'calmar_ratio': calmar,
            'max_drawdown': max_dd,
            'max_drawdown_duration': max_dd_duration,
            'current_drawdown': self.current_drawdown,
            'total_return': total_return,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'total_trades': len(self.trades_history)
        }

    def reset(self):
        """Reset risk manager to initial state"""
        self.current_capital = self.initial_capital
        self.equity_curve = [self.initial_capital]
        self.peak_equity = self.initial_capital
        self.current_drawdown = 0.0
        self.trades_history = []
        self.trading_enabled = True
        self.risk_reduction_active = False

    def __repr__(self) -> str:
        state = self.get_current_state()
        return (f"RiskManager(capital={state['current_capital']:.0f}, "
                f"DD={state['current_drawdown']:.1%}, "
                f"trades={state['total_trades']}, "
                f"enabled={state['trading_enabled']})")


class PositionSizer:
    """Static helper for position size calculations"""

    @staticmethod
    def fixed_risk(
        capital: float,
        risk_pct: float,
        entry: float,
        sl: float
    ) -> Tuple[float, int]:
        """
        Fixed % risk position sizing.

        Args:
            capital: Account capital
            risk_pct: Risk percentage (0.02 = 2%)
            entry: Entry price
            sl: Stop loss price

        Returns:
            (position_size, contracts)
        """
        risk_amount = capital * risk_pct
        sl_distance = abs(entry - sl)

        if sl_distance == 0:
            return 0, 0

        contracts = risk_amount / sl_distance
        position_size = contracts * entry

        return position_size, int(contracts)

    @staticmethod
    def atr_based(
        capital: float,
        risk_pct: float,
        entry: float,
        atr: float
    ) -> Tuple[float, int]:
        """
        ATR-based position sizing.

        Args:
            capital: Account capital
            risk_pct: Risk percentage
            entry: Entry price
            atr: Average True Range

        Returns:
            (position_size, contracts)
        """
        risk_amount = capital * risk_pct

        # Validate ATR
        if atr == 0 or atr is None or np.isnan(atr) or np.isinf(atr):
            # Fallback to 1 contract
            contracts = 1
            position_size = contracts * entry
            return position_size, int(contracts)

        contracts = risk_amount / atr

        # Safety check after calculation
        if np.isinf(contracts) or np.isnan(contracts) or contracts <= 0:
            contracts = 1

        position_size = contracts * entry

        return position_size, int(contracts)

    @staticmethod
    def kelly_criterion(
        capital: float,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        fraction: float = 0.5
    ) -> float:
        """
        Kelly Criterion position sizing.

        Args:
            capital: Account capital
            win_rate: Historical win rate (0-1)
            avg_win: Average winning trade
            avg_loss: Average losing trade (absolute value)
            fraction: Fraction of Kelly to use (0.5 = Half-Kelly)

        Returns:
            Position size
        """
        p = win_rate
        q = 1 - p
        b = avg_win / avg_loss if avg_loss > 0 else 1

        kelly = (p * b - q) / b
        kelly = max(0, min(kelly, 0.5))  # Cap at 50%

        return capital * kelly * fraction


if __name__ == "__main__":
    # Example usage
    print("Risk Manager Example:\n")

    risk_mgr = RiskManager(
        initial_capital=50000,
        max_risk_per_trade=0.02,
        use_kelly=False
    )

    # Calculate position size
    sizing = risk_mgr.calculate_position_size(
        entry_price=4800,
        sl_price=4815,
        atr=12
    )

    print(f"Position sizing: {sizing}")
    print(f"Method: {sizing['method']}")
    print(f"Contracts: {sizing['contracts']}")
    print(f"Risk: {sizing['risk_amount']:.2f} SEK ({sizing.get('risk_pct', 0.02):.1%})")

    # Simulate some trades
    print("\nSimulating trades...")

    trades = [
        {'pnl': 500, 'result': 'WIN'},
        {'pnl': -300, 'result': 'LOSS'},
        {'pnl': 400, 'result': 'WIN'},
        {'pnl': -250, 'result': 'LOSS'},
        {'pnl': 600, 'result': 'WIN'},
    ]

    for trade in trades:
        risk_mgr.update_after_trade(trade)
        print(f"Trade: {trade['result']:4s} | PnL: {trade['pnl']:+6.0f} SEK | "
              f"Capital: {risk_mgr.current_capital:,.0f} SEK | "
              f"DD: {risk_mgr.current_drawdown:.1%}")

    # Calculate metrics
    print("\nRisk Metrics:")
    metrics = risk_mgr.calculate_metrics()
    for key, value in metrics.items():
        if isinstance(value, float):
            print(f"  {key:25s}: {value:.3f}")
        else:
            print(f"  {key:25s}: {value}")
