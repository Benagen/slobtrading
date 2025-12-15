"""
Tests for Dashboard.

Run with: pytest tests/test_dashboard.py -v
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import tempfile
from pathlib import Path

from slob.visualization import Dashboard


@pytest.fixture
def sample_trades():
    """Create sample trade data"""
    trades = []
    base_time = datetime(2024, 1, 15, 16, 0)

    np.random.seed(42)

    for i in range(50):
        entry_time = base_time + timedelta(hours=i * 2)
        exit_time = entry_time + timedelta(minutes=np.random.randint(30, 180))

        # Simulate realistic P&L
        is_win = np.random.rand() > 0.4  # 60% win rate
        pnl = np.random.randint(100, 500) if is_win else -np.random.randint(50, 250)

        entry_price = 16000 + np.random.randn() * 50
        sl_price = entry_price + 60 if pnl < 0 else entry_price + 60
        tp_price = entry_price - 100 if pnl > 0 else entry_price - 100
        exit_price = entry_price - pnl / 10

        trades.append({
            'entry_time': entry_time,
            'exit_time': exit_time,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'sl_price': sl_price,
            'tp_price': tp_price,
            'pnl': pnl,
            'result': 'WIN' if is_win else 'LOSS',
            'direction': 'SHORT'
        })

    return trades


@pytest.fixture
def empty_trades():
    """Empty trade list"""
    return []


class TestDashboard:
    """Test suite for Dashboard"""

    def test_initialization(self, sample_trades):
        """Test dashboard initialization with trades"""
        dashboard = Dashboard(sample_trades, initial_capital=50000)

        assert dashboard.initial_capital == 50000
        assert len(dashboard.trades) == 50
        assert len(dashboard.df_trades) == 50
        assert 'entry_time' in dashboard.df_trades.columns
        assert 'pnl' in dashboard.df_trades.columns

    def test_initialization_empty(self, empty_trades):
        """Test dashboard initialization with empty trades"""
        dashboard = Dashboard(empty_trades)

        assert len(dashboard.trades) == 0
        assert dashboard.df_trades.empty

    def test_create_dashboard(self, sample_trades):
        """Test creating full dashboard"""
        dashboard = Dashboard(sample_trades)
        fig = dashboard.create_dashboard()

        assert fig is not None
        # Should have multiple traces
        assert len(fig.data) > 0
        assert fig.layout.title.text == "5/1 SLOB Backtest Dashboard"

    def test_create_dashboard_empty(self, empty_trades):
        """Test creating dashboard with no trades"""
        dashboard = Dashboard(empty_trades)
        fig = dashboard.create_dashboard()

        assert fig is not None
        # Should show "no trades" message
        assert len(fig.layout.annotations) > 0

    def test_save_dashboard(self, sample_trades):
        """Test saving dashboard to HTML"""
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "reports" / "dashboard.html"

            dashboard = Dashboard(sample_trades)
            fig = dashboard.create_dashboard(save_path=str(save_path))

            assert save_path.exists()
            assert save_path.stat().st_size > 0

    def test_calculate_metrics(self, sample_trades):
        """Test metrics calculation"""
        dashboard = Dashboard(sample_trades, initial_capital=50000)
        metrics = dashboard._calculate_metrics()

        assert 'total_trades' in metrics
        assert 'win_rate' in metrics
        assert 'total_pnl' in metrics
        assert 'sharpe_ratio' in metrics

        assert metrics['total_trades'] == 50
        assert 0 <= metrics['win_rate'] <= 100
        # Accept numpy types as well
        assert isinstance(metrics['total_pnl'], (int, float, np.integer, np.floating))
        assert isinstance(metrics['sharpe_ratio'], (int, float, np.integer, np.floating))

    def test_calculate_equity_curve(self, sample_trades):
        """Test equity curve calculation"""
        dashboard = Dashboard(sample_trades, initial_capital=50000)
        equity = dashboard._calculate_equity_curve()

        assert len(equity) > 0
        assert 'equity' in equity.columns
        assert 'drawdown' in equity.columns

        # Equity should start near initial capital
        assert equity['equity'].iloc[0] == 50000

        # Drawdown should be <= 0
        assert all(equity['drawdown'] <= 0)

    def test_calculate_equity_curve_empty(self, empty_trades):
        """Test equity curve with no trades"""
        dashboard = Dashboard(empty_trades, initial_capital=50000)
        equity = dashboard._calculate_equity_curve()

        assert len(equity) == 1
        assert equity['equity'].iloc[0] == 50000
        assert equity['drawdown'].iloc[0] == 0

    def test_calculate_win_rate_heatmap(self, sample_trades):
        """Test win rate heatmap calculation"""
        dashboard = Dashboard(sample_trades)
        heatmap, weekdays, hours = dashboard._calculate_win_rate_heatmap()

        assert heatmap.shape[0] == 5  # 5 weekdays
        assert heatmap.shape[1] > 0  # Multiple time slots
        assert len(weekdays) == 5
        assert weekdays == ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
        assert len(hours) > 0

        # All non-NaN values should be 0-100
        valid_values = heatmap[~np.isnan(heatmap)]
        if len(valid_values) > 0:
            assert all((valid_values >= 0) & (valid_values <= 100))

    def test_export_metrics_table(self, sample_trades):
        """Test exporting metrics as DataFrame"""
        dashboard = Dashboard(sample_trades)
        metrics_df = dashboard.export_metrics_table()

        assert isinstance(metrics_df, pd.DataFrame)
        assert 'Metric' in metrics_df.columns
        assert 'Value' in metrics_df.columns
        assert len(metrics_df) == 8  # 8 metrics

        # Check expected metrics
        metrics_list = metrics_df['Metric'].tolist()
        assert 'Total Trades' in metrics_list
        assert 'Win Rate (%)' in metrics_list
        assert 'Total P&L (SEK)' in metrics_list
        assert 'Sharpe Ratio' in metrics_list

    def test_metrics_cards(self, sample_trades):
        """Test that metrics cards are added"""
        dashboard = Dashboard(sample_trades)
        fig = dashboard.create_dashboard()

        # Check for indicator traces (metrics cards)
        from plotly.graph_objects import Indicator
        indicator_traces = [trace for trace in fig.data if isinstance(trace, Indicator)]

        # Should have at least 2 indicator cards
        assert len(indicator_traces) >= 2

    def test_equity_curve_trace(self, sample_trades):
        """Test that equity curve is added"""
        dashboard = Dashboard(sample_trades)
        fig = dashboard.create_dashboard()

        # Check for scatter traces (equity curve)
        from plotly.graph_objects import Scatter
        scatter_traces = [trace for trace in fig.data if isinstance(trace, Scatter)]

        # Should have scatter traces for equity
        assert len(scatter_traces) > 0

    def test_pnl_distribution(self, sample_trades):
        """Test P&L histogram"""
        dashboard = Dashboard(sample_trades)
        fig = dashboard.create_dashboard()

        # Check for histogram traces
        from plotly.graph_objects import Histogram
        hist_traces = [trace for trace in fig.data if isinstance(trace, Histogram)]

        # Should have histograms for wins/losses
        assert len(hist_traces) >= 2

    def test_win_rate_heatmap_trace(self, sample_trades):
        """Test win rate heatmap"""
        dashboard = Dashboard(sample_trades)
        fig = dashboard.create_dashboard()

        # Check for heatmap trace
        from plotly.graph_objects import Heatmap
        heatmap_traces = [trace for trace in fig.data if isinstance(trace, Heatmap)]

        # Should have heatmap
        assert len(heatmap_traces) >= 1

    def test_rr_scatter(self, sample_trades):
        """Test Risk:Reward scatter plot"""
        dashboard = Dashboard(sample_trades)
        fig = dashboard.create_dashboard()

        # All scatter traces should be present
        from plotly.graph_objects import Scatter
        scatter_traces = [trace for trace in fig.data if isinstance(trace, Scatter)]

        assert len(scatter_traces) > 0

    def test_duration_histogram(self, sample_trades):
        """Test duration histogram"""
        dashboard = Dashboard(sample_trades)
        fig = dashboard.create_dashboard()

        # Check for bar traces (duration)
        from plotly.graph_objects import Bar
        bar_traces = [trace for trace in fig.data if isinstance(trace, Bar)]

        # Should have bar chart for duration
        assert len(bar_traces) >= 1

    def test_layout_properties(self, sample_trades):
        """Test dashboard layout"""
        dashboard = Dashboard(sample_trades)
        fig = dashboard.create_dashboard()

        assert fig.layout.title.text == "5/1 SLOB Backtest Dashboard"
        assert fig.layout.height == 1400
        # Template is set correctly but is a complex object
        assert fig.layout.template is not None

    def test_different_capital(self, sample_trades):
        """Test dashboard with different initial capital"""
        dashboard1 = Dashboard(sample_trades, initial_capital=50000)
        dashboard2 = Dashboard(sample_trades, initial_capital=100000)

        equity1 = dashboard1._calculate_equity_curve()
        equity2 = dashboard2._calculate_equity_curve()

        # Initial equity should be different
        assert equity1['equity'].iloc[0] == 50000
        assert equity2['equity'].iloc[0] == 100000

    def test_sharpe_calculation(self, sample_trades):
        """Test Sharpe ratio calculation"""
        dashboard = Dashboard(sample_trades, initial_capital=50000)
        metrics = dashboard._calculate_metrics()

        # Sharpe should be a reasonable number
        assert -5 < metrics['sharpe_ratio'] < 10  # Realistic bounds

    def test_win_rate_calculation(self, sample_trades):
        """Test win rate calculation accuracy"""
        # Create known trades
        known_trades = [
            {
                'entry_time': datetime(2024, 1, 15, 16, 0),
                'exit_time': datetime(2024, 1, 15, 17, 0),
                'pnl': 100,
                'result': 'WIN',
                'entry_price': 16000,
                'sl_price': 16060,
                'tp_price': 15900,
                'direction': 'SHORT'
            },
            {
                'entry_time': datetime(2024, 1, 15, 18, 0),
                'exit_time': datetime(2024, 1, 15, 19, 0),
                'pnl': -50,
                'result': 'LOSS',
                'entry_price': 16000,
                'sl_price': 16060,
                'tp_price': 15900,
                'direction': 'SHORT'
            },
            {
                'entry_time': datetime(2024, 1, 15, 20, 0),
                'exit_time': datetime(2024, 1, 15, 21, 0),
                'pnl': 150,
                'result': 'WIN',
                'entry_price': 16000,
                'sl_price': 16060,
                'tp_price': 15900,
                'direction': 'SHORT'
            }
        ]

        dashboard = Dashboard(known_trades)
        metrics = dashboard._calculate_metrics()

        # 2 wins out of 3 = 66.67%
        assert abs(metrics['win_rate'] - 66.67) < 0.1

    def test_total_pnl_calculation(self, sample_trades):
        """Test total P&L calculation"""
        dashboard = Dashboard(sample_trades)
        metrics = dashboard._calculate_metrics()

        # Calculate expected P&L
        expected_pnl = sum(t['pnl'] for t in sample_trades)

        assert abs(metrics['total_pnl'] - expected_pnl) < 0.01

    def test_drawdown_calculation(self, sample_trades):
        """Test drawdown calculation"""
        dashboard = Dashboard(sample_trades, initial_capital=50000)
        equity = dashboard._calculate_equity_curve()

        # Max drawdown should be the minimum drawdown value
        max_dd = equity['drawdown'].min()

        # Should be negative or zero
        assert max_dd <= 0

        # Drawdown at peak should be 0
        peak_idx = equity['equity'].idxmax()
        assert abs(equity.loc[peak_idx, 'drawdown']) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
