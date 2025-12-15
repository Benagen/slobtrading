"""
Interactive Dashboard for trade analysis.

Creates comprehensive dashboard with:
- Metrics cards (Total trades, Win rate, P&L, Sharpe)
- Equity curve with drawdown shading
- Win rate heatmaps (weekday, hour, combined)
- Trade distribution (P&L histogram, R:R scatter, duration)
- Drawdown chart (underwater equity)
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import List, Dict, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class Dashboard:
    """Create interactive dashboard for backtest results"""

    def __init__(self, trades: List[Dict], initial_capital: float = 50000):
        """
        Initialize dashboard with trade data.

        Args:
            trades: List of trade dicts with keys:
                - entry_time: datetime
                - exit_time: datetime
                - result: 'WIN' or 'LOSS'
                - pnl: P&L in SEK
                - entry_price: Entry price
                - exit_price: Exit price
                - sl_price: Stop loss price
                - tp_price: Take profit price
                - direction: 'LONG' or 'SHORT'
            initial_capital: Starting capital in SEK
        """
        self.trades = trades
        self.initial_capital = initial_capital
        self.df_trades = pd.DataFrame(trades) if trades else pd.DataFrame()

        if not self.df_trades.empty:
            # Ensure datetime columns
            if 'entry_time' in self.df_trades.columns:
                self.df_trades['entry_time'] = pd.to_datetime(self.df_trades['entry_time'])
            if 'exit_time' in self.df_trades.columns:
                self.df_trades['exit_time'] = pd.to_datetime(self.df_trades['exit_time'])

    def create_dashboard(self, save_path: Optional[str] = None) -> go.Figure:
        """
        Create complete dashboard with all components.

        Args:
            save_path: Optional path to save HTML file

        Returns:
            Plotly Figure object
        """
        if self.df_trades.empty:
            logger.warning("No trades to visualize")
            return self._create_empty_dashboard()

        # Create subplots layout
        fig = make_subplots(
            rows=4, cols=2,
            row_heights=[0.15, 0.25, 0.3, 0.3],
            column_widths=[0.5, 0.5],
            specs=[
                [{"type": "indicator"}, {"type": "indicator"}],
                [{"colspan": 2, "type": "scatter"}, None],
                [{"type": "scatter"}, {"type": "heatmap"}],
                [{"type": "bar"}, {"type": "scatter"}]
            ],
            subplot_titles=(
                'Total Trades', 'Win Rate',
                'Equity Curve',
                'P&L Distribution', 'Win Rate by Weekday & Hour',
                'Trade Duration', 'Risk:Reward Scatter'
            ),
            vertical_spacing=0.08,
            horizontal_spacing=0.10
        )

        # Row 1: Metrics Cards
        self._add_metrics_cards(fig)

        # Row 2: Equity Curve (full width)
        self._add_equity_curve(fig, row=2, col=1)

        # Row 3: P&L Distribution + Win Rate Heatmap
        self._add_pnl_distribution(fig, row=3, col=1)
        self._add_win_rate_heatmap(fig, row=3, col=2)

        # Row 4: Duration + R:R Scatter
        self._add_duration_histogram(fig, row=4, col=1)
        self._add_rr_scatter(fig, row=4, col=2)

        # Update layout
        self._update_layout(fig)

        # Save if path provided
        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            fig.write_html(save_path)
            logger.info(f"Dashboard saved to {save_path}")

        return fig

    def _add_metrics_cards(self, fig: go.Figure):
        """Add metrics indicator cards"""
        metrics = self._calculate_metrics()

        # Total Trades
        fig.add_trace(
            go.Indicator(
                mode="number",
                value=metrics['total_trades'],
                title={'text': "Total Trades"},
                domain={'x': [0, 0.45], 'y': [0.85, 1.0]}
            ),
            row=1, col=1
        )

        # Win Rate
        fig.add_trace(
            go.Indicator(
                mode="number+delta",
                value=metrics['win_rate'],
                number={'suffix': "%"},
                title={'text': "Win Rate"},
                delta={'reference': 50, 'relative': False, 'suffix': "%"},
                domain={'x': [0.55, 1.0], 'y': [0.85, 1.0]}
            ),
            row=1, col=2
        )

    def _add_equity_curve(self, fig: go.Figure, row: int, col: int):
        """Add equity curve with drawdown shading"""
        equity = self._calculate_equity_curve()

        # Equity line
        fig.add_trace(
            go.Scatter(
                x=equity.index,
                y=equity['equity'],
                mode='lines',
                name='Equity',
                line=dict(color='#1f77b4', width=2),
                hovertemplate='<b>%{x}</b><br>Equity: %{y:,.0f} SEK<extra></extra>'
            ),
            row=row, col=col
        )

        # Drawdown shading
        drawdown = equity['drawdown']
        fig.add_trace(
            go.Scatter(
                x=equity.index,
                y=drawdown,
                mode='lines',
                name='Drawdown',
                fill='tozeroy',
                fillcolor='rgba(255, 0, 0, 0.2)',
                line=dict(color='rgba(255, 0, 0, 0.5)', width=1),
                hovertemplate='<b>%{x}</b><br>Drawdown: %{y:.1f}%<extra></extra>'
            ),
            row=row, col=col
        )

    def _add_pnl_distribution(self, fig: go.Figure, row: int, col: int):
        """Add P&L histogram"""
        pnl = self.df_trades['pnl'].values

        # Separate wins and losses
        wins = pnl[pnl > 0]
        losses = pnl[pnl <= 0]

        # Histogram for wins
        fig.add_trace(
            go.Histogram(
                x=wins,
                name='Wins',
                marker_color='#4caf50',
                opacity=0.7,
                nbinsx=20
            ),
            row=row, col=col
        )

        # Histogram for losses
        fig.add_trace(
            go.Histogram(
                x=losses,
                name='Losses',
                marker_color='#f44336',
                opacity=0.7,
                nbinsx=20
            ),
            row=row, col=col
        )

    def _add_win_rate_heatmap(self, fig: go.Figure, row: int, col: int):
        """Add combined weekday × hour win rate heatmap"""
        heatmap_data, weekdays, hours = self._calculate_win_rate_heatmap()

        fig.add_trace(
            go.Heatmap(
                z=heatmap_data,
                x=hours,
                y=weekdays,
                colorscale='RdYlGn',
                zmid=50,
                text=heatmap_data,
                texttemplate='%{text:.0f}%',
                textfont={"size": 10},
                colorbar=dict(title="Win Rate %"),
                hovertemplate='<b>%{y}, %{x}</b><br>Win Rate: %{z:.1f}%<extra></extra>'
            ),
            row=row, col=col
        )

    def _add_duration_histogram(self, fig: go.Figure, row: int, col: int):
        """Add trade duration histogram"""
        if 'entry_time' in self.df_trades.columns and 'exit_time' in self.df_trades.columns:
            duration = (self.df_trades['exit_time'] - self.df_trades['entry_time']).dt.total_seconds() / 60

            fig.add_trace(
                go.Bar(
                    x=duration,
                    name='Duration',
                    marker_color='#ff9800',
                    opacity=0.7
                ),
                row=row, col=col
            )

    def _add_rr_scatter(self, fig: go.Figure, row: int, col: int):
        """Add Risk:Reward scatter plot"""
        if all(k in self.df_trades.columns for k in ['entry_price', 'sl_price', 'tp_price', 'pnl']):
            # Calculate risk and reward for each trade
            risk = abs(self.df_trades['entry_price'] - self.df_trades['sl_price'])
            reward = abs(self.df_trades['entry_price'] - self.df_trades['tp_price'])
            rr_ratio = reward / risk

            # Color by result
            colors = ['#4caf50' if r == 'WIN' else '#f44336'
                     for r in self.df_trades['result']]

            fig.add_trace(
                go.Scatter(
                    x=rr_ratio,
                    y=self.df_trades['pnl'],
                    mode='markers',
                    marker=dict(
                        color=colors,
                        size=8,
                        line=dict(width=1, color='white')
                    ),
                    text=self.df_trades['result'],
                    hovertemplate='<b>R:R: %{x:.2f}</b><br>P&L: %{y:,.0f} SEK<br>Result: %{text}<extra></extra>',
                    showlegend=False
                ),
                row=row, col=col
            )

    def _calculate_metrics(self) -> Dict:
        """Calculate summary metrics"""
        total_trades = len(self.df_trades)
        wins = (self.df_trades['result'] == 'WIN').sum()
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

        total_pnl = self.df_trades['pnl'].sum() if 'pnl' in self.df_trades.columns else 0

        # Calculate Sharpe ratio
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

    def _calculate_equity_curve(self) -> pd.DataFrame:
        """Calculate equity curve and drawdown"""
        if 'exit_time' not in self.df_trades.columns or 'pnl' not in self.df_trades.columns:
            # Return empty DataFrame with required structure
            return pd.DataFrame({
                'equity': [self.initial_capital],
                'drawdown': [0]
            })

        # Sort by exit time
        df_sorted = self.df_trades.sort_values('exit_time').copy()

        # Calculate cumulative equity
        df_sorted['cumulative_pnl'] = df_sorted['pnl'].cumsum()
        df_sorted['equity'] = self.initial_capital + df_sorted['cumulative_pnl']

        # Calculate running maximum
        df_sorted['running_max'] = df_sorted['equity'].cummax()

        # Calculate drawdown percentage
        df_sorted['drawdown'] = ((df_sorted['equity'] - df_sorted['running_max']) /
                                 df_sorted['running_max'] * 100)

        equity = df_sorted.set_index('exit_time')[['equity', 'drawdown']]

        # Add initial point
        if len(equity) > 0:
            initial_row = pd.DataFrame({
                'equity': [self.initial_capital],
                'drawdown': [0]
            }, index=[equity.index[0] - pd.Timedelta(hours=1)])
            equity = pd.concat([initial_row, equity])

        return equity

    def _calculate_win_rate_heatmap(self) -> tuple:
        """Calculate win rate by weekday and hour"""
        if 'entry_time' not in self.df_trades.columns:
            return np.zeros((5, 14)), ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'], []

        # Extract weekday and hour
        df = self.df_trades.copy()
        df['weekday'] = df['entry_time'].dt.weekday
        df['hour'] = df['entry_time'].dt.hour

        # Create 30-minute bins (15:30-22:00 = 13 bins + 1)
        df['time_slot'] = df['entry_time'].dt.floor('30min').dt.time

        # Weekday names
        weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

        # Time slots (15:30, 16:00, 16:30, ..., 22:00)
        time_slots = pd.date_range('15:30', '22:00', freq='30min').time
        time_slot_labels = [t.strftime('%H:%M') for t in time_slots]

        # Initialize heatmap
        heatmap = np.full((5, len(time_slots)), np.nan)

        # Calculate win rate for each cell
        for wd_idx, weekday in enumerate(range(5)):  # Mon=0 to Fri=4
            for ts_idx, time_slot in enumerate(time_slots):
                mask = (df['weekday'] == weekday) & (df['time_slot'] == time_slot)
                trades_in_cell = df[mask]

                if len(trades_in_cell) > 0:
                    wins = (trades_in_cell['result'] == 'WIN').sum()
                    win_rate = (wins / len(trades_in_cell)) * 100
                    heatmap[wd_idx, ts_idx] = win_rate

        return heatmap, weekdays, time_slot_labels

    def _update_layout(self, fig: go.Figure):
        """Update figure layout"""
        fig.update_layout(
            title=dict(
                text="5/1 SLOB Backtest Dashboard",
                font=dict(size=24, family='Arial', color='#333')
            ),
            height=1400,
            showlegend=True,
            template='plotly_white',
            font=dict(family='Arial', size=12),
            hovermode='closest'
        )

        # Update axes
        fig.update_xaxes(title_text="Date", row=2, col=1)
        fig.update_yaxes(title_text="Equity (SEK)", row=2, col=1)

        fig.update_xaxes(title_text="P&L (SEK)", row=3, col=1)
        fig.update_yaxes(title_text="Frequency", row=3, col=1)

        fig.update_xaxes(title_text="Time Slot", row=3, col=2)
        fig.update_yaxes(title_text="Weekday", row=3, col=2)

        fig.update_xaxes(title_text="Duration (minutes)", row=4, col=1)
        fig.update_yaxes(title_text="Frequency", row=4, col=1)

        fig.update_xaxes(title_text="Risk:Reward Ratio", row=4, col=2)
        fig.update_yaxes(title_text="P&L (SEK)", row=4, col=2)

    def _create_empty_dashboard(self) -> go.Figure:
        """Create empty dashboard when no trades available"""
        fig = go.Figure()

        fig.add_annotation(
            text="No trades to display",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=20)
        )

        fig.update_layout(
            title="5/1 SLOB Backtest Dashboard",
            height=800,
            template='plotly_white'
        )

        return fig

    def export_metrics_table(self) -> pd.DataFrame:
        """Export metrics as DataFrame for reporting"""
        metrics = self._calculate_metrics()

        if 'pnl' in self.df_trades.columns:
            wins = self.df_trades[self.df_trades['result'] == 'WIN']['pnl']
            losses = self.df_trades[self.df_trades['result'] == 'LOSS']['pnl']

            avg_win = wins.mean() if len(wins) > 0 else 0
            avg_loss = losses.mean() if len(losses) > 0 else 0
            max_win = wins.max() if len(wins) > 0 else 0
            max_loss = losses.min() if len(losses) > 0 else 0
        else:
            avg_win = avg_loss = max_win = max_loss = 0

        return pd.DataFrame({
            'Metric': [
                'Total Trades',
                'Win Rate (%)',
                'Total P&L (SEK)',
                'Sharpe Ratio',
                'Avg Win (SEK)',
                'Avg Loss (SEK)',
                'Max Win (SEK)',
                'Max Loss (SEK)'
            ],
            'Value': [
                metrics['total_trades'],
                f"{metrics['win_rate']:.1f}",
                f"{metrics['total_pnl']:,.0f}",
                f"{metrics['sharpe_ratio']:.2f}",
                f"{avg_win:,.0f}",
                f"{avg_loss:,.0f}",
                f"{max_win:,.0f}",
                f"{max_loss:,.0f}"
            ]
        })
