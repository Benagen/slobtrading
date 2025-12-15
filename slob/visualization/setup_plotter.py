"""
Setup Plotter - Visualize individual trade setups.

Creates interactive charts with all setup components:
- Candlestick chart
- LSE High/Low levels
- LIQ #1 and LIQ #2 markers
- Consolidation box
- No-wick candle marker
- Entry/Exit points
- SL/TP levels
- Trade path
- Volume subplot
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
from typing import Dict, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class SetupPlotter:
    """Create interactive charts for trade setups"""

    # Color scheme
    COLORS = {
        'bullish': '#26a69a',
        'bearish': '#ef5350',
        'lse_high': '#e53935',
        'lse_low': '#43a047',
        'liq1': '#ff6f00',
        'liq2': '#ff9800',
        'consolidation': 'rgba(255, 235, 59, 0.2)',
        'consolidation_border': '#fbc02d',
        'nowick': '#9c27b0',
        'entry_short': '#1976d2',
        'entry_long': '#388e3c',
        'sl': '#d32f2f',
        'tp': '#388e3c',
        'win': '#4caf50',
        'loss': '#f44336',
        'volume': 'rgba(100, 100, 100, 0.3)'
    }

    @staticmethod
    def plot_setup(
        df: pd.DataFrame,
        setup: Dict,
        trade: Optional[Dict] = None,
        save_path: Optional[str] = None,
        title: Optional[str] = None
    ) -> go.Figure:
        """
        Plot a complete trade setup with all components.

        Args:
            df: OHLCV DataFrame
            setup: Setup dict with keys:
                - lse_high: LSE session high
                - lse_low: LSE session low
                - liq1_idx: Index of LIQ #1 candle
                - liq1_level: LIQ #1 level
                - consol_start_idx: Consolidation start index
                - consol_end_idx: Consolidation end index
                - consol_high: Consolidation high
                - consol_low: Consolidation low
                - nowick_idx: No-wick candle index
                - liq2_idx: LIQ #2 candle index
                - liq2_level: LIQ #2 level
            trade: Optional trade dict with keys:
                - entry_idx: Entry candle index
                - entry_price: Entry price
                - sl_price: Stop loss price
                - tp_price: Take profit price
                - exit_idx: Exit candle index (if completed)
                - exit_price: Exit price (if completed)
                - result: 'WIN' or 'LOSS' (if completed)
            save_path: Optional path to save HTML file
            title: Optional chart title

        Returns:
            Plotly Figure object
        """
        # Create subplots: candlestick + volume
        fig = make_subplots(
            rows=2, cols=1,
            row_heights=[0.7, 0.3],
            shared_xaxes=True,
            vertical_spacing=0.03,
            subplot_titles=('Price Action', 'Volume')
        )

        # 1. Candlestick chart
        SetupPlotter._add_candlestick(fig, df, row=1, col=1)

        # 2. LSE High/Low levels
        if 'lse_high' in setup and 'lse_low' in setup:
            SetupPlotter._add_lse_levels(fig, df, setup, row=1, col=1)

        # 3. LIQ #1 marker
        if 'liq1_idx' in setup:
            SetupPlotter._add_liq1_marker(fig, df, setup, row=1, col=1)

        # 4. Consolidation box
        if 'consol_start_idx' in setup and 'consol_end_idx' in setup:
            SetupPlotter._add_consolidation_box(fig, df, setup, row=1, col=1)

        # 5. No-wick candle marker
        if 'nowick_idx' in setup:
            SetupPlotter._add_nowick_marker(fig, df, setup, row=1, col=1)

        # 6. LIQ #2 marker
        if 'liq2_idx' in setup:
            SetupPlotter._add_liq2_marker(fig, df, setup, row=1, col=1)

        # 7. Entry point
        if trade and 'entry_idx' in trade:
            SetupPlotter._add_entry_marker(fig, df, trade, row=1, col=1)

        # 8. SL/TP levels
        if trade and 'sl_price' in trade and 'tp_price' in trade:
            SetupPlotter._add_sl_tp_levels(fig, df, trade, row=1, col=1)

        # 9. Exit point and trade path
        if trade and 'exit_idx' in trade:
            SetupPlotter._add_exit_marker(fig, df, trade, row=1, col=1)
            SetupPlotter._add_trade_path(fig, df, trade, row=1, col=1)

        # 10. Volume subplot
        SetupPlotter._add_volume(fig, df, row=2, col=1)

        # Update layout
        SetupPlotter._update_layout(fig, title, df)

        # Save if path provided
        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            fig.write_html(save_path)
            logger.info(f"Chart saved to {save_path}")

        return fig

    @staticmethod
    def _add_candlestick(fig: go.Figure, df: pd.DataFrame, row: int, col: int):
        """Add candlestick chart"""
        fig.add_trace(
            go.Candlestick(
                x=df.index,
                open=df['Open'],
                high=df['High'],
                low=df['Low'],
                close=df['Close'],
                name='Price',
                increasing_line_color=SetupPlotter.COLORS['bullish'],
                decreasing_line_color=SetupPlotter.COLORS['bearish'],
                showlegend=False
            ),
            row=row, col=col
        )

    @staticmethod
    def _add_lse_levels(fig: go.Figure, df: pd.DataFrame, setup: Dict, row: int, col: int):
        """Add LSE High and Low levels"""
        # LSE High
        fig.add_hline(
            y=setup['lse_high'],
            line_dash="dash",
            line_color=SetupPlotter.COLORS['lse_high'],
            line_width=2,
            annotation_text="LSE High",
            annotation_position="right",
            row=row, col=col
        )

        # LSE Low
        fig.add_hline(
            y=setup['lse_low'],
            line_dash="dash",
            line_color=SetupPlotter.COLORS['lse_low'],
            line_width=2,
            annotation_text="LSE Low",
            annotation_position="right",
            row=row, col=col
        )

    @staticmethod
    def _add_liq1_marker(fig: go.Figure, df: pd.DataFrame, setup: Dict, row: int, col: int):
        """Add LIQ #1 marker (upward arrow for liquidity grab)"""
        liq1_time = df.index[setup['liq1_idx']]
        liq1_price = setup.get('liq1_level', df.iloc[setup['liq1_idx']]['High'])

        fig.add_trace(
            go.Scatter(
                x=[liq1_time],
                y=[liq1_price],
                mode='markers+text',
                marker=dict(
                    symbol='triangle-up',
                    size=15,
                    color=SetupPlotter.COLORS['liq1'],
                    line=dict(width=2, color='white')
                ),
                text=['LIQ #1'],
                textposition='top center',
                textfont=dict(size=10, color=SetupPlotter.COLORS['liq1']),
                name='LIQ #1',
                showlegend=False
            ),
            row=row, col=col
        )

    @staticmethod
    def _add_consolidation_box(fig: go.Figure, df: pd.DataFrame, setup: Dict, row: int, col: int):
        """Add consolidation box"""
        consol_start = df.index[setup['consol_start_idx']]
        consol_end = df.index[setup['consol_end_idx']]

        fig.add_shape(
            type="rect",
            x0=consol_start,
            x1=consol_end,
            y0=setup['consol_low'],
            y1=setup['consol_high'],
            fillcolor=SetupPlotter.COLORS['consolidation'],
            line=dict(
                color=SetupPlotter.COLORS['consolidation_border'],
                width=2,
                dash='dot'
            ),
            row=row, col=col
        )

        # Add annotation
        mid_time = consol_start + (consol_end - consol_start) / 2
        mid_price = (setup['consol_high'] + setup['consol_low']) / 2

        fig.add_annotation(
            x=mid_time,
            y=mid_price,
            text="CONSOLIDATION",
            showarrow=False,
            font=dict(size=10, color=SetupPlotter.COLORS['consolidation_border']),
            bgcolor='rgba(255, 255, 255, 0.8)',
            row=row, col=col
        )

    @staticmethod
    def _add_nowick_marker(fig: go.Figure, df: pd.DataFrame, setup: Dict, row: int, col: int):
        """Add no-wick candle marker"""
        nowick_time = df.index[setup['nowick_idx']]
        nowick_price = df.iloc[setup['nowick_idx']]['High']

        fig.add_trace(
            go.Scatter(
                x=[nowick_time],
                y=[nowick_price],
                mode='markers+text',
                marker=dict(
                    symbol='star',
                    size=15,
                    color=SetupPlotter.COLORS['nowick'],
                    line=dict(width=2, color='white')
                ),
                text=['NO-WICK'],
                textposition='top center',
                textfont=dict(size=10, color=SetupPlotter.COLORS['nowick']),
                name='No-Wick',
                showlegend=False
            ),
            row=row, col=col
        )

    @staticmethod
    def _add_liq2_marker(fig: go.Figure, df: pd.DataFrame, setup: Dict, row: int, col: int):
        """Add LIQ #2 marker"""
        liq2_time = df.index[setup['liq2_idx']]
        liq2_price = setup.get('liq2_level', df.iloc[setup['liq2_idx']]['High'])

        fig.add_trace(
            go.Scatter(
                x=[liq2_time],
                y=[liq2_price],
                mode='markers+text',
                marker=dict(
                    symbol='triangle-up',
                    size=15,
                    color=SetupPlotter.COLORS['liq2'],
                    line=dict(width=2, color='white')
                ),
                text=['LIQ #2'],
                textposition='top center',
                textfont=dict(size=10, color=SetupPlotter.COLORS['liq2']),
                name='LIQ #2',
                showlegend=False
            ),
            row=row, col=col
        )

    @staticmethod
    def _add_entry_marker(fig: go.Figure, df: pd.DataFrame, trade: Dict, row: int, col: int):
        """Add entry point marker"""
        entry_time = df.index[trade['entry_idx']]
        entry_price = trade['entry_price']

        # Determine direction (SHORT = triangle down, LONG = triangle up)
        direction = trade.get('direction', 'SHORT')
        symbol = 'triangle-down' if direction == 'SHORT' else 'triangle-up'
        color = SetupPlotter.COLORS['entry_short'] if direction == 'SHORT' else SetupPlotter.COLORS['entry_long']

        fig.add_trace(
            go.Scatter(
                x=[entry_time],
                y=[entry_price],
                mode='markers+text',
                marker=dict(
                    symbol=symbol,
                    size=18,
                    color=color,
                    line=dict(width=2, color='white')
                ),
                text=['ENTRY'],
                textposition='bottom center' if direction == 'SHORT' else 'top center',
                textfont=dict(size=11, color=color, family='Arial Black'),
                name='Entry',
                showlegend=False
            ),
            row=row, col=col
        )

    @staticmethod
    def _add_sl_tp_levels(fig: go.Figure, df: pd.DataFrame, trade: Dict, row: int, col: int):
        """Add SL and TP levels"""
        # Stop Loss
        fig.add_hline(
            y=trade['sl_price'],
            line_dash="dot",
            line_color=SetupPlotter.COLORS['sl'],
            line_width=2,
            annotation_text=f"SL ({trade['sl_price']:.2f})",
            annotation_position="right",
            row=row, col=col
        )

        # Take Profit
        fig.add_hline(
            y=trade['tp_price'],
            line_dash="dot",
            line_color=SetupPlotter.COLORS['tp'],
            line_width=2,
            annotation_text=f"TP ({trade['tp_price']:.2f})",
            annotation_position="right",
            row=row, col=col
        )

    @staticmethod
    def _add_exit_marker(fig: go.Figure, df: pd.DataFrame, trade: Dict, row: int, col: int):
        """Add exit point marker"""
        exit_time = df.index[trade['exit_idx']]
        exit_price = trade['exit_price']
        result = trade.get('result', 'UNKNOWN')

        color = SetupPlotter.COLORS['win'] if result == 'WIN' else SetupPlotter.COLORS['loss']

        fig.add_trace(
            go.Scatter(
                x=[exit_time],
                y=[exit_price],
                mode='markers+text',
                marker=dict(
                    symbol='x',
                    size=18,
                    color=color,
                    line=dict(width=3)
                ),
                text=[result],
                textposition='top center',
                textfont=dict(size=11, color=color, family='Arial Black'),
                name='Exit',
                showlegend=False
            ),
            row=row, col=col
        )

    @staticmethod
    def _add_trade_path(fig: go.Figure, df: pd.DataFrame, trade: Dict, row: int, col: int):
        """Add line from entry to exit"""
        entry_time = df.index[trade['entry_idx']]
        exit_time = df.index[trade['exit_idx']]
        entry_price = trade['entry_price']
        exit_price = trade['exit_price']

        result = trade.get('result', 'UNKNOWN')
        color = SetupPlotter.COLORS['win'] if result == 'WIN' else SetupPlotter.COLORS['loss']

        fig.add_trace(
            go.Scatter(
                x=[entry_time, exit_time],
                y=[entry_price, exit_price],
                mode='lines',
                line=dict(
                    color=color,
                    width=2,
                    dash='dash'
                ),
                name='Trade Path',
                showlegend=False
            ),
            row=row, col=col
        )

    @staticmethod
    def _add_volume(fig: go.Figure, df: pd.DataFrame, row: int, col: int):
        """Add volume bars"""
        colors = [
            SetupPlotter.COLORS['bullish'] if close >= open_price
            else SetupPlotter.COLORS['bearish']
            for close, open_price in zip(df['Close'], df['Open'])
        ]

        fig.add_trace(
            go.Bar(
                x=df.index,
                y=df['Volume'],
                marker_color=colors,
                name='Volume',
                showlegend=False,
                opacity=0.5
            ),
            row=row, col=col
        )

    @staticmethod
    def _update_layout(fig: go.Figure, title: Optional[str], df: pd.DataFrame):
        """Update figure layout"""
        if title is None:
            title = "5/1 SLOB Setup Analysis"

        fig.update_layout(
            title=dict(
                text=title,
                font=dict(size=18, family='Arial')
            ),
            xaxis_rangeslider_visible=False,
            hovermode='x unified',
            height=800,
            template='plotly_white',
            font=dict(family='Arial', size=12)
        )

        # Update y-axis labels
        fig.update_yaxes(title_text="Price", row=1, col=1)
        fig.update_yaxes(title_text="Volume", row=2, col=1)

        # Update x-axis
        fig.update_xaxes(title_text="Time", row=2, col=1)

    @staticmethod
    def plot_simple_candlestick(
        df: pd.DataFrame,
        title: str = "OHLCV Chart",
        save_path: Optional[str] = None
    ) -> go.Figure:
        """
        Create simple candlestick chart without setup markers.

        Args:
            df: OHLCV DataFrame
            title: Chart title
            save_path: Optional path to save HTML file

        Returns:
            Plotly Figure object
        """
        fig = make_subplots(
            rows=2, cols=1,
            row_heights=[0.7, 0.3],
            shared_xaxes=True,
            vertical_spacing=0.03
        )

        # Candlestick
        SetupPlotter._add_candlestick(fig, df, row=1, col=1)

        # Volume
        SetupPlotter._add_volume(fig, df, row=2, col=1)

        # Layout
        SetupPlotter._update_layout(fig, title, df)

        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            fig.write_html(save_path)
            logger.info(f"Chart saved to {save_path}")

        return fig
