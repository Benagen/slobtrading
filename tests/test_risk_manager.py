"""
Tests for RiskManager and PositionSizer.

Run with: pytest tests/test_risk_manager.py -v
"""

import pytest
import numpy as np

from slob.backtest import RiskManager, PositionSizer


class TestRiskManager:
    """Test suite for RiskManager"""

    def test_initialization(self):
        """Test risk manager initialization"""
        rm = RiskManager(initial_capital=50000, max_risk_per_trade=0.02)

        assert rm.initial_capital == 50000
        assert rm.current_capital == 50000
        assert rm.max_risk_per_trade == 0.02
        assert rm.trading_enabled is True

    def test_calculate_position_size_fixed_risk(self):
        """Test fixed risk position sizing"""
        rm = RiskManager(initial_capital=50000, max_risk_per_trade=0.02)

        sizing = rm.calculate_position_size(entry_price=4800, sl_price=4815)

        assert sizing['method'] == 'fixed_risk'
        assert sizing['risk_amount'] == 1000  # 2% of 50000
        assert sizing['contracts'] == 66  # 1000 / 15 pips

    def test_calculate_position_size_atr_based(self):
        """Test ATR-based position sizing"""
        rm = RiskManager(initial_capital=50000, max_risk_per_trade=0.02)

        sizing = rm.calculate_position_size(
            entry_price=4800,
            sl_price=4815,
            atr=12
        )

        assert sizing['method'] == 'atr_based'
        assert sizing['atr'] == 12
        assert 'contracts' in sizing

    def test_calculate_position_size_kelly(self):
        """Test Kelly Criterion position sizing"""
        rm = RiskManager(
            initial_capital=50000,
            max_risk_per_trade=0.02,
            use_kelly=True,
            kelly_fraction=0.5
        )

        # Add some trade history for Kelly calculation
        for i in range(15):
            rm.update_after_trade({'pnl': 500 if i % 2 == 0 else -300, 'result': 'WIN' if i % 2 == 0 else 'LOSS'})

        sizing = rm.calculate_position_size(entry_price=4800, sl_price=4815)

        assert sizing['method'] == 'kelly_criterion'
        assert 'kelly_size' in sizing
        assert sizing['kelly_fraction'] == 0.5

    def test_update_after_trade_win(self):
        """Test state update after winning trade"""
        rm = RiskManager(initial_capital=50000)

        rm.update_after_trade({'pnl': 500, 'result': 'WIN'})

        assert rm.current_capital == 50500
        assert rm.peak_equity == 50500
        assert rm.current_drawdown == 0

    def test_update_after_trade_loss(self):
        """Test state update after losing trade"""
        rm = RiskManager(initial_capital=50000)

        rm.update_after_trade({'pnl': -500, 'result': 'LOSS'})

        assert rm.current_capital == 49500
        assert rm.peak_equity == 50000
        assert rm.current_drawdown == pytest.approx(0.01)  # 1% DD

    def test_drawdown_calculation(self):
        """Test drawdown calculation"""
        rm = RiskManager(initial_capital=50000)

        rm.update_after_trade({'pnl': 1000, 'result': 'WIN'})  # 51000 (new peak)
        rm.update_after_trade({'pnl': -500, 'result': 'LOSS'}) # 50500
        rm.update_after_trade({'pnl': -500, 'result': 'LOSS'}) # 50000

        # DD from peak (51000) to current (50000) = 1000/51000 ≈ 1.96%
        assert rm.current_drawdown == pytest.approx(1000/51000, rel=1e-3)

    def test_risk_reduction_activation(self):
        """Test risk reduction at drawdown threshold"""
        rm = RiskManager(
            initial_capital=50000,
            max_risk_per_trade=0.02,
            reduce_size_at_dd=0.10  # 10% DD threshold
        )

        # Create 10% drawdown
        rm.update_after_trade({'pnl': -5000, 'result': 'LOSS'})

        assert rm.risk_reduction_active is True

        # Position size should be reduced
        sizing = rm.calculate_position_size(entry_price=4800, sl_price=4815)
        assert sizing['risk_amount'] == 450  # 50% of normal 900 (2% of 45000)

    def test_max_drawdown_stop(self):
        """Test trading stops at max drawdown"""
        rm = RiskManager(
            initial_capital=50000,
            max_drawdown_stop=0.20  # 20% max DD
        )

        # Create 25% drawdown
        rm.update_after_trade({'pnl': -12500, 'result': 'LOSS'})

        assert rm.trading_enabled is False

        # Should return zero position size
        sizing = rm.calculate_position_size(entry_price=4800, sl_price=4815)
        assert sizing['position_size'] == 0
        assert 'trading_disabled' in sizing['method']

    def test_get_current_state(self):
        """Test current state retrieval"""
        rm = RiskManager(initial_capital=50000)

        rm.update_after_trade({'pnl': 500, 'result': 'WIN'})

        state = rm.get_current_state()

        assert state['current_capital'] == 50500
        assert state['initial_capital'] == 50000
        assert state['peak_equity'] == 50500
        assert state['total_trades'] == 1
        assert state['trading_enabled'] is True

    def test_calculate_metrics(self):
        """Test metrics calculation"""
        rm = RiskManager(initial_capital=50000)

        # Add some trades
        trades = [
            {'pnl': 500, 'result': 'WIN'},
            {'pnl': -300, 'result': 'LOSS'},
            {'pnl': 400, 'result': 'WIN'},
            {'pnl': -250, 'result': 'LOSS'},
            {'pnl': 600, 'result': 'WIN'},
        ]

        for trade in trades:
            rm.update_after_trade(trade)

        metrics = rm.calculate_metrics()

        assert 'sharpe_ratio' in metrics
        assert 'sortino_ratio' in metrics
        assert 'calmar_ratio' in metrics
        assert 'max_drawdown' in metrics
        assert 'win_rate' in metrics
        assert 'profit_factor' in metrics
        assert metrics['total_trades'] == 5
        assert metrics['win_rate'] == 0.6  # 3/5

    def test_reset(self):
        """Test risk manager reset"""
        rm = RiskManager(initial_capital=50000)

        rm.update_after_trade({'pnl': 500, 'result': 'WIN'})
        rm.update_after_trade({'pnl': -300, 'result': 'LOSS'})

        rm.reset()

        assert rm.current_capital == 50000
        assert len(rm.equity_curve) == 1
        assert len(rm.trades_history) == 0
        assert rm.trading_enabled is True
        assert rm.risk_reduction_active is False

    def test_repr(self):
        """Test string representation"""
        rm = RiskManager(initial_capital=50000)

        repr_str = repr(rm)

        assert 'RiskManager' in repr_str
        assert '50000' in repr_str


class TestPositionSizer:
    """Test suite for PositionSizer helper"""

    def test_fixed_risk(self):
        """Test fixed risk calculation"""
        position_size, contracts = PositionSizer.fixed_risk(
            capital=50000,
            risk_pct=0.02,
            entry=4800,
            sl=4815
        )

        assert contracts == 66  # int(1000 / 15) = 66
        assert position_size == pytest.approx(320000, rel=1e-3)  # (1000/15) * 4800 = 320000

    def test_atr_based(self):
        """Test ATR-based calculation"""
        position_size, contracts = PositionSizer.atr_based(
            capital=50000,
            risk_pct=0.02,
            entry=4800,
            atr=12
        )

        assert contracts == 83  # int(1000 / 12) = 83
        assert position_size == pytest.approx(400000, rel=1e-3)  # (1000/12) * 4800 = 400000

    def test_kelly_criterion(self):
        """Test Kelly Criterion calculation"""
        position_size = PositionSizer.kelly_criterion(
            capital=50000,
            win_rate=0.6,
            avg_win=500,
            avg_loss=300,
            fraction=0.5
        )

        # Kelly = (p*b - q) / b = (0.6*(500/300) - 0.4) / (500/300)
        # Kelly ≈ 0.36
        # Half-Kelly = 0.18
        # Position = 50000 * 0.18 = 9000
        assert position_size > 0
        assert position_size < 50000 * 0.5  # Should be less than half capital

    def test_zero_sl_distance(self):
        """Test handling of zero SL distance"""
        position_size, contracts = PositionSizer.fixed_risk(
            capital=50000,
            risk_pct=0.02,
            entry=4800,
            sl=4800  # Same as entry
        )

        assert position_size == 0
        assert contracts == 0

    def test_zero_atr(self):
        """Test handling of zero ATR"""
        position_size, contracts = PositionSizer.atr_based(
            capital=50000,
            risk_pct=0.02,
            entry=4800,
            atr=0
        )

        assert position_size == 0
        assert contracts == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
