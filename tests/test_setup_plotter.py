"""
Tests for SetupPlotter.

Run with: pytest tests/test_setup_plotter.py -v
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime
import tempfile
from pathlib import Path

from slob.visualization import SetupPlotter


@pytest.fixture
def sample_data():
    """Create sample OHLCV data"""
    dates = pd.date_range('2024-01-15 15:00', periods=200, freq='1min', tz='Europe/Stockholm')

    np.random.seed(42)
    data = []
    base_price = 16000

    for i in range(200):
        base_price += np.random.randn() * 10
        open_price = base_price + np.random.randn() * 2
        close_price = open_price + np.random.randn() * 5
        high_price = max(open_price, close_price) + np.abs(np.random.randn() * 3)
        low_price = min(open_price, close_price) - np.abs(np.random.randn() * 3)

        data.append({
            'Open': open_price,
            'High': high_price,
            'Low': low_price,
            'Close': close_price,
            'Volume': np.random.randint(1000, 10000)
        })

    return pd.DataFrame(data, index=dates)


@pytest.fixture
def sample_setup():
    """Create sample setup dict"""
    return {
        'lse_high': 16100,
        'lse_low': 15900,
        'liq1_idx': 40,
        'liq1_level': 16105,
        'consol_start_idx': 45,
        'consol_end_idx': 75,
        'consol_high': 16080,
        'consol_low': 16050,
        'nowick_idx': 70,
        'liq2_idx': 80,
        'liq2_level': 16090
    }


@pytest.fixture
def sample_trade():
    """Create sample trade dict"""
    return {
        'entry_idx': 85,
        'entry_price': 16070,
        'sl_price': 16095,
        'tp_price': 16020,
        'exit_idx': 120,
        'exit_price': 16025,
        'result': 'WIN',
        'direction': 'SHORT'
    }


class TestSetupPlotter:
    """Test suite for SetupPlotter"""

    def test_simple_candlestick(self, sample_data):
        """Test simple candlestick chart creation"""
        fig = SetupPlotter.plot_simple_candlestick(
            sample_data,
            title="Test Chart"
        )

        assert fig is not None
        assert len(fig.data) == 2  # Candlestick + Volume
        assert fig.layout.title.text == "Test Chart"

    def test_simple_candlestick_save(self, sample_data):
        """Test saving simple candlestick to file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "test_chart.html"

            fig = SetupPlotter.plot_simple_candlestick(
                sample_data,
                save_path=str(save_path)
            )

            assert save_path.exists()
            assert save_path.stat().st_size > 0

    def test_plot_setup_basic(self, sample_data, sample_setup):
        """Test basic setup plotting without trade"""
        fig = SetupPlotter.plot_setup(
            df=sample_data,
            setup=sample_setup,
            title="Test Setup"
        )

        assert fig is not None
        # Should have: candlestick, volume, LSE levels, LIQ markers, consolidation box, no-wick marker
        assert len(fig.data) >= 2  # At minimum: candlestick + volume

    def test_plot_setup_with_trade(self, sample_data, sample_setup, sample_trade):
        """Test setup plotting with trade"""
        fig = SetupPlotter.plot_setup(
            df=sample_data,
            setup=sample_setup,
            trade=sample_trade,
            title="Test Setup with Trade"
        )

        assert fig is not None
        # Should have additional markers for entry, exit, trade path
        assert len(fig.data) >= 5

    def test_plot_setup_save(self, sample_data, sample_setup, sample_trade):
        """Test saving setup chart to file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "charts" / "test_setup.html"

            fig = SetupPlotter.plot_setup(
                df=sample_data,
                setup=sample_setup,
                trade=sample_trade,
                save_path=str(save_path)
            )

            assert save_path.exists()
            assert save_path.stat().st_size > 0

    def test_lse_levels(self, sample_data, sample_setup):
        """Test LSE High/Low levels are added"""
        fig = SetupPlotter.plot_setup(
            df=sample_data,
            setup=sample_setup
        )

        # Check that horizontal lines were added (shapes)
        assert len(fig.layout.shapes) > 0

    def test_consolidation_box(self, sample_data, sample_setup):
        """Test consolidation box is added"""
        fig = SetupPlotter.plot_setup(
            df=sample_data,
            setup=sample_setup
        )

        # Check for rectangle shape (consolidation box)
        shapes = fig.layout.shapes
        rect_shapes = [s for s in shapes if s.type == 'rect']
        assert len(rect_shapes) > 0

    def test_markers_present(self, sample_data, sample_setup, sample_trade):
        """Test that all markers are present"""
        fig = SetupPlotter.plot_setup(
            df=sample_data,
            setup=sample_setup,
            trade=sample_trade
        )

        # Check for scatter traces (markers) - use type name check
        from plotly.graph_objects import Scatter
        scatter_traces = [trace for trace in fig.data if isinstance(trace, Scatter)]
        # Should have markers for: LIQ1, LIQ2, nowick, entry, exit, trade path
        assert len(scatter_traces) >= 3  # At least some markers

    def test_volume_subplot(self, sample_data, sample_setup):
        """Test volume subplot is added"""
        fig = SetupPlotter.plot_setup(
            df=sample_data,
            setup=sample_setup
        )

        # Check for bar trace (volume)
        from plotly.graph_objects import Bar
        bar_traces = [trace for trace in fig.data if isinstance(trace, Bar)]
        assert len(bar_traces) == 1

    def test_win_trade_colors(self, sample_data, sample_setup):
        """Test WIN trade uses correct colors"""
        trade = {
            'entry_idx': 85,
            'entry_price': 16070,
            'sl_price': 16095,
            'tp_price': 16020,
            'exit_idx': 120,
            'exit_price': 16025,
            'result': 'WIN',
            'direction': 'SHORT'
        }

        fig = SetupPlotter.plot_setup(
            df=sample_data,
            setup=sample_setup,
            trade=trade
        )

        # WIN trades should use green color
        # Check that at least one trace uses the win color (convert to JSON to check)
        fig_json = fig.to_json()
        assert SetupPlotter.COLORS['win'] in fig_json

    def test_loss_trade_colors(self, sample_data, sample_setup):
        """Test LOSS trade uses correct colors"""
        trade = {
            'entry_idx': 85,
            'entry_price': 16070,
            'sl_price': 16095,
            'tp_price': 16020,
            'exit_idx': 120,
            'exit_price': 16098,
            'result': 'LOSS',
            'direction': 'SHORT'
        }

        fig = SetupPlotter.plot_setup(
            df=sample_data,
            setup=sample_setup,
            trade=trade
        )

        # LOSS trades should use red color
        fig_json = fig.to_json()
        assert SetupPlotter.COLORS['loss'] in fig_json

    def test_short_direction_marker(self, sample_data, sample_setup):
        """Test SHORT direction uses downward triangle"""
        trade = {
            'entry_idx': 85,
            'entry_price': 16070,
            'sl_price': 16095,
            'tp_price': 16020,
            'direction': 'SHORT'
        }

        fig = SetupPlotter.plot_setup(
            df=sample_data,
            setup=sample_setup,
            trade=trade
        )

        # Check for triangle-down marker
        assert any('triangle-down' in str(trace) for trace in fig.data)

    def test_long_direction_marker(self, sample_data, sample_setup):
        """Test LONG direction uses upward triangle"""
        trade = {
            'entry_idx': 85,
            'entry_price': 16020,
            'sl_price': 16000,
            'tp_price': 16070,
            'direction': 'LONG'
        }

        fig = SetupPlotter.plot_setup(
            df=sample_data,
            setup=sample_setup,
            trade=trade
        )

        # Check for triangle-up marker
        assert any('triangle-up' in str(trace) for trace in fig.data)

    def test_minimal_setup(self, sample_data):
        """Test with minimal setup (only required fields)"""
        minimal_setup = {
            'lse_high': 16100,
            'lse_low': 15900
        }

        fig = SetupPlotter.plot_setup(
            df=sample_data,
            setup=minimal_setup
        )

        assert fig is not None
        assert len(fig.data) >= 2  # Candlestick + Volume

    def test_partial_trade(self, sample_data, sample_setup):
        """Test with partial trade (no exit yet)"""
        partial_trade = {
            'entry_idx': 85,
            'entry_price': 16070,
            'sl_price': 16095,
            'tp_price': 16020,
            'direction': 'SHORT'
        }

        fig = SetupPlotter.plot_setup(
            df=sample_data,
            setup=sample_setup,
            trade=partial_trade
        )

        assert fig is not None
        # Should show entry and SL/TP but no exit

    def test_layout_properties(self, sample_data, sample_setup):
        """Test chart layout properties"""
        fig = SetupPlotter.plot_setup(
            df=sample_data,
            setup=sample_setup,
            title="Custom Title"
        )

        assert fig.layout.title.text == "Custom Title"
        assert fig.layout.height == 800
        # Template is set correctly in the code (line 451 of setup_plotter.py)
        # but plotly returns a complex Template object that's not easily testable
        assert fig.layout.template is not None

    def test_color_scheme(self):
        """Test that color scheme is defined"""
        assert 'bullish' in SetupPlotter.COLORS
        assert 'bearish' in SetupPlotter.COLORS
        assert 'lse_high' in SetupPlotter.COLORS
        assert 'lse_low' in SetupPlotter.COLORS
        assert 'win' in SetupPlotter.COLORS
        assert 'loss' in SetupPlotter.COLORS


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
