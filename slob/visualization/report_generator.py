"""
HTML Report Generator for backtest results.

Creates comprehensive HTML reports with:
- Executive summary
- Strategy parameters
- Performance metrics
- Embedded dashboard
- Individual setup charts
- Trade log
- Risk metrics
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate comprehensive HTML reports for backtest results"""

    def __init__(
        self,
        trades: List[Dict],
        initial_capital: float = 50000,
        strategy_params: Optional[Dict] = None
    ):
        """
        Initialize report generator.

        Args:
            trades: List of trade dicts
            initial_capital: Starting capital in SEK
            strategy_params: Optional dict of strategy parameters
        """
        self.trades = trades
        self.initial_capital = initial_capital
        self.strategy_params = strategy_params or {}
        self.df_trades = pd.DataFrame(trades) if trades else pd.DataFrame()

        if not self.df_trades.empty:
            if 'entry_time' in self.df_trades.columns:
                self.df_trades['entry_time'] = pd.to_datetime(self.df_trades['entry_time'])
            if 'exit_time' in self.df_trades.columns:
                self.df_trades['exit_time'] = pd.to_datetime(self.df_trades['exit_time'])

    def generate_report(
        self,
        output_path: str,
        dashboard_path: Optional[str] = None,
        setup_charts_dir: Optional[str] = None
    ) -> str:
        """
        Generate complete HTML report.

        Args:
            output_path: Path to save HTML report
            dashboard_path: Optional path to dashboard HTML (for embedding)
            setup_charts_dir: Optional directory with individual setup charts

        Returns:
            Path to generated report
        """
        html_parts = []

        # HTML header
        html_parts.append(self._get_html_header())

        # Executive summary
        html_parts.append(self._generate_executive_summary())

        # Strategy parameters
        html_parts.append(self._generate_strategy_params())

        # Performance metrics
        html_parts.append(self._generate_performance_metrics())

        # Risk metrics
        html_parts.append(self._generate_risk_metrics())

        # Dashboard embed (if provided)
        if dashboard_path:
            html_parts.append(self._embed_dashboard(dashboard_path))

        # Trade log
        html_parts.append(self._generate_trade_log())

        # Setup charts thumbnails (if provided)
        if setup_charts_dir:
            html_parts.append(self._generate_setup_charts_gallery(setup_charts_dir))

        # Footer
        html_parts.append(self._get_html_footer())

        # Combine and save
        html_content = '\n'.join(html_parts)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"Report generated: {output_path}")
        return str(output_path)

    def _get_html_header(self) -> str:
        """Generate HTML header with CSS"""
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>5/1 SLOB Backtest Report</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }

        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 20px;
            margin-bottom: 30px;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }

        header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }

        header p {
            font-size: 1.1em;
            opacity: 0.9;
        }

        .section {
            background: white;
            border-radius: 8px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }

        .section h2 {
            color: #667eea;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
            margin-bottom: 20px;
            font-size: 1.8em;
        }

        .section h3 {
            color: #764ba2;
            margin-top: 20px;
            margin-bottom: 15px;
            font-size: 1.3em;
        }

        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }

        .metric-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }

        .metric-card .label {
            font-size: 0.9em;
            opacity: 0.9;
            margin-bottom: 10px;
        }

        .metric-card .value {
            font-size: 2em;
            font-weight: bold;
        }

        .metric-card.positive {
            background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
        }

        .metric-card.negative {
            background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%);
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }

        table th {
            background: #667eea;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
        }

        table td {
            padding: 10px 12px;
            border-bottom: 1px solid #eee;
        }

        table tr:hover {
            background: #f8f9fa;
        }

        .win {
            color: #38ef7d;
            font-weight: bold;
        }

        .loss {
            color: #f45c43;
            font-weight: bold;
        }

        .dashboard-embed {
            width: 100%;
            height: 1200px;
            border: none;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }

        .charts-gallery {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }

        .chart-thumbnail {
            border: 2px solid #eee;
            border-radius: 8px;
            padding: 10px;
            text-align: center;
            transition: transform 0.2s, box-shadow 0.2s;
            cursor: pointer;
        }

        .chart-thumbnail:hover {
            transform: translateY(-5px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            border-color: #667eea;
        }

        .chart-thumbnail img {
            width: 100%;
            border-radius: 4px;
        }

        .timestamp {
            color: #888;
            font-size: 0.9em;
            margin-top: 10px;
        }

        footer {
            text-align: center;
            padding: 20px;
            color: #888;
            font-size: 0.9em;
        }

        .warning {
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin: 20px 0;
            border-radius: 4px;
        }

        .info {
            background: #d1ecf1;
            border-left: 4px solid #17a2b8;
            padding: 15px;
            margin: 20px 0;
            border-radius: 4px;
        }
    </style>
</head>
<body>
    <div class="container">
"""

    def _get_html_footer(self) -> str:
        """Generate HTML footer"""
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"""
    </div>
    <footer>
        <p>Generated by 5/1 SLOB Backtester | {generated_at}</p>
        <p>🤖 Powered by Claude Code</p>
    </footer>
</body>
</html>
"""

    def _generate_executive_summary(self) -> str:
        """Generate executive summary section"""
        metrics = self._calculate_metrics()

        total_pnl = metrics['total_pnl']
        win_rate = metrics['win_rate']
        total_trades = metrics['total_trades']

        summary_class = 'positive' if total_pnl > 0 else 'negative'
        pnl_symbol = '+' if total_pnl > 0 else ''

        return f"""
<header>
    <h1>5/1 SLOB Backtest Report</h1>
    <p>Comprehensive analysis of {total_trades} trades | Win Rate: {win_rate:.1f}% | Total P&L: {pnl_symbol}{total_pnl:,.0f} SEK</p>
</header>

<div class="section">
    <h2>📊 Executive Summary</h2>

    <div class="metrics-grid">
        <div class="metric-card">
            <div class="label">Total Trades</div>
            <div class="value">{total_trades}</div>
        </div>

        <div class="metric-card">
            <div class="label">Win Rate</div>
            <div class="value">{win_rate:.1f}%</div>
        </div>

        <div class="metric-card {summary_class}">
            <div class="label">Total P&L</div>
            <div class="value">{pnl_symbol}{total_pnl:,.0f} SEK</div>
        </div>

        <div class="metric-card">
            <div class="label">Sharpe Ratio</div>
            <div class="value">{metrics['sharpe_ratio']:.2f}</div>
        </div>
    </div>

    <div class="info">
        <strong>Strategy:</strong> 5/1 SLOB (Liquidity) Setup<br>
        <strong>Initial Capital:</strong> {self.initial_capital:,.0f} SEK<br>
        <strong>Final Capital:</strong> {self.initial_capital + total_pnl:,.0f} SEK<br>
        <strong>ROI:</strong> {(total_pnl / self.initial_capital * 100):.2f}%
    </div>
</div>
"""

    def _generate_strategy_params(self) -> str:
        """Generate strategy parameters section"""
        if not self.strategy_params:
            return ""

        params_html = "<table><tr><th>Parameter</th><th>Value</th></tr>"
        for key, value in self.strategy_params.items():
            params_html += f"<tr><td>{key}</td><td>{value}</td></tr>"
        params_html += "</table>"

        return f"""
<div class="section">
    <h2>⚙️ Strategy Parameters</h2>
    {params_html}
</div>
"""

    def _generate_performance_metrics(self) -> str:
        """Generate performance metrics section"""
        if self.df_trades.empty:
            return ""

        wins = self.df_trades[self.df_trades['result'] == 'WIN']
        losses = self.df_trades[self.df_trades['result'] == 'LOSS']

        avg_win = wins['pnl'].mean() if len(wins) > 0 else 0
        avg_loss = losses['pnl'].mean() if len(losses) > 0 else 0
        max_win = wins['pnl'].max() if len(wins) > 0 else 0
        max_loss = losses['pnl'].min() if len(losses) > 0 else 0

        profit_factor = abs(wins['pnl'].sum() / losses['pnl'].sum()) if len(losses) > 0 and losses['pnl'].sum() != 0 else 0

        return f"""
<div class="section">
    <h2>📈 Performance Metrics</h2>

    <table>
        <tr><th>Metric</th><th>Value</th></tr>
        <tr><td>Total Trades</td><td>{len(self.df_trades)}</td></tr>
        <tr><td>Winning Trades</td><td class="win">{len(wins)}</td></tr>
        <tr><td>Losing Trades</td><td class="loss">{len(losses)}</td></tr>
        <tr><td>Win Rate</td><td>{len(wins) / len(self.df_trades) * 100:.1f}%</td></tr>
        <tr><td>Average Win</td><td class="win">+{avg_win:,.0f} SEK</td></tr>
        <tr><td>Average Loss</td><td class="loss">{avg_loss:,.0f} SEK</td></tr>
        <tr><td>Max Win</td><td class="win">+{max_win:,.0f} SEK</td></tr>
        <tr><td>Max Loss</td><td class="loss">{max_loss:,.0f} SEK</td></tr>
        <tr><td>Profit Factor</td><td>{profit_factor:.2f}</td></tr>
    </table>
</div>
"""

    def _generate_risk_metrics(self) -> str:
        """Generate risk metrics section"""
        if self.df_trades.empty or 'pnl' not in self.df_trades.columns:
            return ""

        returns = self.df_trades['pnl'] / self.initial_capital

        # Sharpe Ratio
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0

        # Sortino Ratio (downside deviation)
        downside_returns = returns[returns < 0]
        downside_std = downside_returns.std() if len(downside_returns) > 0 else 0
        sortino = (returns.mean() / downside_std) * np.sqrt(252) if downside_std > 0 else 0

        # Max Drawdown
        equity = self.initial_capital + self.df_trades.sort_values('exit_time')['pnl'].cumsum()
        running_max = equity.cummax()
        drawdown = ((equity - running_max) / running_max * 100)
        max_dd = drawdown.min()

        # Calmar Ratio (return / max drawdown)
        annual_return = (returns.mean() * 252)
        calmar = abs(annual_return / (max_dd / 100)) if max_dd != 0 else 0

        return f"""
<div class="section">
    <h2>⚠️ Risk Metrics</h2>

    <table>
        <tr><th>Metric</th><th>Value</th><th>Description</th></tr>
        <tr>
            <td>Sharpe Ratio</td>
            <td>{sharpe:.2f}</td>
            <td>Risk-adjusted return (>1.0 is good, >2.0 is excellent)</td>
        </tr>
        <tr>
            <td>Sortino Ratio</td>
            <td>{sortino:.2f}</td>
            <td>Return vs downside risk (>1.5 is good)</td>
        </tr>
        <tr>
            <td>Max Drawdown</td>
            <td class="loss">{max_dd:.2f}%</td>
            <td>Maximum peak-to-trough decline</td>
        </tr>
        <tr>
            <td>Calmar Ratio</td>
            <td>{calmar:.2f}</td>
            <td>Annual return / Max DD (>3.0 is good)</td>
        </tr>
    </table>

    <div class="warning">
        <strong>⚠️ Risk Warning:</strong> Past performance is not indicative of future results.
        Backtest results do not account for slippage, commissions, or real-world execution challenges.
    </div>
</div>
"""

    def _embed_dashboard(self, dashboard_path: str) -> str:
        """Embed dashboard HTML via iframe"""
        dashboard_path = Path(dashboard_path)
        if not dashboard_path.exists():
            logger.warning(f"Dashboard not found: {dashboard_path}")
            return ""

        # Use relative path if possible
        rel_path = dashboard_path.name

        return f"""
<div class="section">
    <h2>📊 Interactive Dashboard</h2>
    <iframe class="dashboard-embed" src="{rel_path}"></iframe>
</div>
"""

    def _generate_trade_log(self) -> str:
        """Generate sortable trade log table"""
        if self.df_trades.empty:
            return ""

        rows_html = ""
        for idx, trade in self.df_trades.iterrows():
            result_class = 'win' if trade.get('result') == 'WIN' else 'loss'
            pnl = trade.get('pnl', 0)
            pnl_str = f"+{pnl:,.0f}" if pnl > 0 else f"{pnl:,.0f}"

            entry_time = trade.get('entry_time', 'N/A')
            exit_time = trade.get('exit_time', 'N/A')

            if isinstance(entry_time, pd.Timestamp):
                entry_time = entry_time.strftime("%Y-%m-%d %H:%M")
            if isinstance(exit_time, pd.Timestamp):
                exit_time = exit_time.strftime("%Y-%m-%d %H:%M")

            rows_html += f"""
<tr>
    <td>{idx + 1}</td>
    <td>{entry_time}</td>
    <td>{exit_time}</td>
    <td>{trade.get('entry_price', 0):.2f}</td>
    <td>{trade.get('exit_price', 0):.2f}</td>
    <td class="{result_class}">{trade.get('result', 'N/A')}</td>
    <td class="{result_class}">{pnl_str} SEK</td>
    <td>{trade.get('direction', 'SHORT')}</td>
</tr>
"""

        return f"""
<div class="section">
    <h2>📝 Trade Log</h2>

    <table id="tradeLog">
        <tr>
            <th>#</th>
            <th>Entry Time</th>
            <th>Exit Time</th>
            <th>Entry Price</th>
            <th>Exit Price</th>
            <th>Result</th>
            <th>P&L</th>
            <th>Direction</th>
        </tr>
        {rows_html}
    </table>
</div>
"""

    def _generate_setup_charts_gallery(self, charts_dir: str) -> str:
        """Generate thumbnail gallery of setup charts"""
        charts_path = Path(charts_dir)
        if not charts_path.exists():
            logger.warning(f"Charts directory not found: {charts_path}")
            return ""

        # Find all HTML charts
        chart_files = sorted(charts_path.glob("*.html"))

        if not chart_files:
            return ""

        thumbnails_html = ""
        for i, chart_file in enumerate(chart_files[:20], 1):  # Limit to 20
            rel_path = chart_file.name
            thumbnails_html += f"""
<div class="chart-thumbnail">
    <a href="{rel_path}" target="_blank">
        <strong>Setup #{i}</strong>
        <p class="timestamp">{chart_file.stem}</p>
    </a>
</div>
"""

        return f"""
<div class="section">
    <h2>🎯 Individual Setup Charts</h2>
    <p>Click on any setup to view detailed chart (opens in new tab)</p>

    <div class="charts-gallery">
        {thumbnails_html}
    </div>
</div>
"""

    def _calculate_metrics(self) -> Dict:
        """Calculate summary metrics"""
        if self.df_trades.empty:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'sharpe_ratio': 0
            }

        total_trades = len(self.df_trades)
        wins = (self.df_trades['result'] == 'WIN').sum()
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

        total_pnl = self.df_trades['pnl'].sum() if 'pnl' in self.df_trades.columns else 0

        # Sharpe ratio
        if 'pnl' in self.df_trades.columns and len(self.df_trades) > 1:
            returns = self.df_trades['pnl'] / self.initial_capital
            sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
        else:
            sharpe = 0

        return {
            'total_trades': total_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'sharpe_ratio': sharpe
        }
