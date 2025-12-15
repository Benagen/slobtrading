"""
Tests for ReportGenerator.

Run with: pytest tests/test_report_generator.py -v
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import tempfile
from pathlib import Path

from slob.visualization import ReportGenerator


@pytest.fixture
def sample_trades():
    """Create sample trade data"""
    trades = []
    base_time = datetime(2024, 1, 15, 16, 0)

    np.random.seed(42)

    for i in range(30):
        entry_time = base_time + timedelta(hours=i * 2)
        exit_time = entry_time + timedelta(minutes=np.random.randint(30, 180))

        is_win = np.random.rand() > 0.4
        pnl = np.random.randint(100, 500) if is_win else -np.random.randint(50, 250)

        entry_price = 16000 + np.random.randn() * 50
        exit_price = entry_price - pnl / 10

        trades.append({
            'entry_time': entry_time,
            'exit_time': exit_time,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl': pnl,
            'result': 'WIN' if is_win else 'LOSS',
            'direction': 'SHORT',
            'sl_price': entry_price + 60,
            'tp_price': entry_price - 100
        })

    return trades


@pytest.fixture
def sample_strategy_params():
    """Create sample strategy parameters"""
    return {
        'Symbol': 'NQ=F',
        'Interval': '1m',
        'Position Size': '17,500 SEK',
        'Risk per Trade': '2%',
        'ATR Period': 14,
        'Consolidation Duration': '15-30 min'
    }


class TestReportGenerator:
    """Test suite for ReportGenerator"""

    def test_initialization(self, sample_trades, sample_strategy_params):
        """Test report generator initialization"""
        report = ReportGenerator(
            sample_trades,
            initial_capital=50000,
            strategy_params=sample_strategy_params
        )

        assert report.initial_capital == 50000
        assert len(report.trades) == 30
        assert len(report.df_trades) == 30
        assert report.strategy_params == sample_strategy_params

    def test_initialization_empty(self):
        """Test initialization with no trades"""
        report = ReportGenerator([])

        assert len(report.trades) == 0
        assert report.df_trades.empty

    def test_generate_report(self, sample_trades):
        """Test generating basic report"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.html"

            report = ReportGenerator(sample_trades)
            generated_path = report.generate_report(str(output_path))

            assert Path(generated_path).exists()
            assert Path(generated_path).stat().st_size > 0

            # Read content
            with open(generated_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Check key sections
            assert '5/1 SLOB Backtest Report' in content
            assert 'Executive Summary' in content
            assert 'Performance Metrics' in content
            assert 'Risk Metrics' in content
            assert 'Trade Log' in content

    def test_generate_report_with_dashboard(self, sample_trades):
        """Test generating report with embedded dashboard"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fake dashboard
            dashboard_path = Path(tmpdir) / "dashboard.html"
            dashboard_path.write_text("<html><body>Dashboard</body></html>")

            output_path = Path(tmpdir) / "report.html"

            report = ReportGenerator(sample_trades)
            generated_path = report.generate_report(
                str(output_path),
                dashboard_path=str(dashboard_path)
            )

            with open(generated_path, 'r', encoding='utf-8') as f:
                content = f.read()

            assert 'Interactive Dashboard' in content
            assert '<iframe' in content

    def test_generate_report_with_charts(self, sample_trades):
        """Test generating report with setup charts"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fake charts directory
            charts_dir = Path(tmpdir) / "charts"
            charts_dir.mkdir()

            for i in range(5):
                chart_file = charts_dir / f"setup_{i}.html"
                chart_file.write_text(f"<html><body>Setup {i}</body></html>")

            output_path = Path(tmpdir) / "report.html"

            report = ReportGenerator(sample_trades)
            generated_path = report.generate_report(
                str(output_path),
                setup_charts_dir=str(charts_dir)
            )

            with open(generated_path, 'r', encoding='utf-8') as f:
                content = f.read()

            assert 'Individual Setup Charts' in content
            assert 'Setup #1' in content

    def test_executive_summary_content(self, sample_trades):
        """Test executive summary section"""
        report = ReportGenerator(sample_trades, initial_capital=50000)
        summary_html = report._generate_executive_summary()

        assert 'Executive Summary' in summary_html
        assert 'Total Trades' in summary_html
        assert 'Win Rate' in summary_html
        assert 'Total P&L' in summary_html
        assert 'Sharpe Ratio' in summary_html
        assert '50,000' in summary_html  # Initial capital

    def test_strategy_params_section(self, sample_strategy_params):
        """Test strategy parameters section"""
        report = ReportGenerator([], strategy_params=sample_strategy_params)
        params_html = report._generate_strategy_params()

        assert 'Strategy Parameters' in params_html
        assert 'NQ=F' in params_html
        assert '1m' in params_html
        assert 'ATR Period' in params_html

    def test_strategy_params_empty(self):
        """Test strategy params with no params"""
        report = ReportGenerator([])
        params_html = report._generate_strategy_params()

        assert params_html == ""

    def test_performance_metrics_section(self, sample_trades):
        """Test performance metrics section"""
        report = ReportGenerator(sample_trades)
        metrics_html = report._generate_performance_metrics()

        assert 'Performance Metrics' in metrics_html
        assert 'Total Trades' in metrics_html
        assert 'Winning Trades' in metrics_html
        assert 'Losing Trades' in metrics_html
        assert 'Average Win' in metrics_html
        assert 'Average Loss' in metrics_html
        assert 'Profit Factor' in metrics_html

    def test_risk_metrics_section(self, sample_trades):
        """Test risk metrics section"""
        report = ReportGenerator(sample_trades)
        risk_html = report._generate_risk_metrics()

        assert 'Risk Metrics' in risk_html
        assert 'Sharpe Ratio' in risk_html
        assert 'Sortino Ratio' in risk_html
        assert 'Max Drawdown' in risk_html
        assert 'Calmar Ratio' in risk_html
        assert 'Risk Warning' in risk_html

    def test_trade_log_section(self, sample_trades):
        """Test trade log table"""
        report = ReportGenerator(sample_trades)
        log_html = report._generate_trade_log()

        assert 'Trade Log' in log_html
        assert 'Entry Time' in log_html
        assert 'Exit Time' in log_html
        assert 'Entry Price' in log_html
        assert 'Exit Price' in log_html
        assert 'WIN' in log_html or 'LOSS' in log_html

        # Should have 30 rows (one per trade)
        assert log_html.count('<tr>') >= 30

    def test_html_header(self):
        """Test HTML header generation"""
        report = ReportGenerator([])
        header = report._get_html_header()

        assert '<!DOCTYPE html>' in header
        assert '<html' in header
        assert '<head>' in header
        assert '<style>' in header
        assert 'body {' in header  # CSS present

    def test_html_footer(self):
        """Test HTML footer generation"""
        report = ReportGenerator([])
        footer = report._get_html_footer()

        assert '</div>' in footer
        assert '</body>' in footer
        assert '</html>' in footer
        assert 'Generated by' in footer
        assert 'Claude Code' in footer

    def test_calculate_metrics(self, sample_trades):
        """Test metrics calculation"""
        report = ReportGenerator(sample_trades, initial_capital=50000)
        metrics = report._calculate_metrics()

        assert 'total_trades' in metrics
        assert 'win_rate' in metrics
        assert 'total_pnl' in metrics
        assert 'sharpe_ratio' in metrics

        assert metrics['total_trades'] == 30
        assert 0 <= metrics['win_rate'] <= 100

    def test_calculate_metrics_empty(self):
        """Test metrics with no trades"""
        report = ReportGenerator([])
        metrics = report._calculate_metrics()

        assert metrics['total_trades'] == 0
        assert metrics['win_rate'] == 0
        assert metrics['total_pnl'] == 0
        assert metrics['sharpe_ratio'] == 0

    def test_positive_pnl_styling(self, sample_trades):
        """Test that positive P&L gets positive styling"""
        # Create trades with guaranteed positive P&L
        winning_trades = [
            {
                'entry_time': datetime(2024, 1, 15, 16, 0),
                'exit_time': datetime(2024, 1, 15, 17, 0),
                'pnl': 500,
                'result': 'WIN',
                'entry_price': 16000,
                'exit_price': 15950,
                'direction': 'SHORT',
                'sl_price': 16060,
                'tp_price': 15900
            }
        ]

        report = ReportGenerator(winning_trades)
        summary = report._generate_executive_summary()

        assert 'positive' in summary or 'win' in summary.lower()
        assert '+500' in summary or '+500' in summary

    def test_negative_pnl_styling(self):
        """Test that negative P&L gets negative styling"""
        # Create trades with guaranteed negative P&L
        losing_trades = [
            {
                'entry_time': datetime(2024, 1, 15, 16, 0),
                'exit_time': datetime(2024, 1, 15, 17, 0),
                'pnl': -200,
                'result': 'LOSS',
                'entry_price': 16000,
                'exit_price': 16020,
                'direction': 'SHORT',
                'sl_price': 16060,
                'tp_price': 15900
            }
        ]

        report = ReportGenerator(losing_trades)
        summary = report._generate_executive_summary()

        assert 'negative' in summary or 'loss' in summary.lower()

    def test_report_file_structure(self, sample_trades):
        """Test that generated report has valid HTML structure"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "reports" / "test.html"

            report = ReportGenerator(sample_trades)
            generated_path = report.generate_report(str(output_path))

            with open(generated_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Check HTML structure
            assert content.count('<!DOCTYPE html>') == 1
            assert content.count('<html') == 1
            assert content.count('</html>') == 1
            assert content.count('<body>') == 1
            assert content.count('</body>') == 1

    def test_embed_dashboard_missing(self, sample_trades):
        """Test embedding dashboard when file doesn't exist"""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_dashboard = Path(tmpdir) / "missing_dashboard.html"
            output_path = Path(tmpdir) / "report.html"

            report = ReportGenerator(sample_trades)
            generated_path = report.generate_report(
                str(output_path),
                dashboard_path=str(fake_dashboard)
            )

            # Should still generate report without dashboard
            assert Path(generated_path).exists()

    def test_charts_gallery_missing_dir(self, sample_trades):
        """Test charts gallery when directory doesn't exist"""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_charts_dir = Path(tmpdir) / "missing_charts"
            output_path = Path(tmpdir) / "report.html"

            report = ReportGenerator(sample_trades)
            generated_path = report.generate_report(
                str(output_path),
                setup_charts_dir=str(fake_charts_dir)
            )

            # Should still generate report without charts
            assert Path(generated_path).exists()

    def test_roi_calculation(self, sample_trades):
        """Test ROI calculation in executive summary"""
        report = ReportGenerator(sample_trades, initial_capital=50000)
        summary = report._generate_executive_summary()

        # Should contain ROI percentage
        assert 'ROI:' in summary
        assert '%' in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
