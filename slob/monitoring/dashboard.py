"""
Web Dashboard for SLOB Trading System

Simple Flask-based dashboard showing:
- System status
- Active setups
- Recent trades
- Performance metrics

Usage:
    python -m slob.monitoring.dashboard

Access at: http://localhost:5000
"""

import os
import sys
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any

from flask import Flask, render_template, jsonify

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('DASHBOARD_SECRET_KEY', 'slob-dashboard-secret-key')

# Database paths
DB_PATH = Path(os.getenv('DB_PATH', 'data/candles.db'))
STATE_DB_PATH = Path(os.getenv('STATE_DB_PATH', 'data/slob_state.db'))


def get_system_status() -> Dict[str, Any]:
    """Get current system status."""
    try:
        status = {
            'status': 'running',
            'uptime': 'Unknown',
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        # Check if databases exist
        status['db_exists'] = STATE_DB_PATH.exists()
        status['candle_db_exists'] = DB_PATH.exists()

        # Get uptime from candle data if available
        if DB_PATH.exists():
            try:
                conn = sqlite3.connect(str(DB_PATH))
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT MIN(timestamp), MAX(timestamp), COUNT(*)
                    FROM candles
                """)
                first_candle, last_candle, total_candles = cursor.fetchone()
                conn.close()

                if last_candle:
                    status['last_candle'] = last_candle
                    status['total_candles'] = total_candles
            except:
                pass

        return status

    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        return {'status': 'error', 'error': str(e)}


def get_active_setups() -> List[Dict[str, Any]]:
    """Get active setups from state database."""
    try:
        if not STATE_DB_PATH.exists():
            return []

        conn = sqlite3.connect(str(STATE_DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM active_setups
            WHERE state != 'SETUP_COMPLETE'
            ORDER BY created_at DESC
            LIMIT 10
        """)

        setups = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return setups

    except Exception as e:
        logger.error(f"Error getting active setups: {e}")
        return []


def get_recent_trades() -> List[Dict[str, Any]]:
    """Get recent completed trades."""
    try:
        if not STATE_DB_PATH.exists():
            return []

        conn = sqlite3.connect(str(STATE_DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM trade_history
            ORDER BY entry_time DESC
            LIMIT 20
        """)

        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return trades

    except Exception as e:
        logger.error(f"Error getting recent trades: {e}")
        return []


def get_performance_metrics() -> Dict[str, Any]:
    """Calculate performance metrics."""
    try:
        if not STATE_DB_PATH.exists():
            return {
                'total_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0
            }

        conn = sqlite3.connect(str(STATE_DB_PATH))
        cursor = conn.cursor()

        # Total trades
        cursor.execute("SELECT COUNT(*) FROM trade_history")
        total_trades = cursor.fetchone()[0]

        # Win/Loss stats
        cursor.execute("""
            SELECT
                COUNT(CASE WHEN pnl > 0 THEN 1 END) as wins,
                COUNT(CASE WHEN pnl < 0 THEN 1 END) as losses,
                SUM(pnl) as total_pnl,
                AVG(CASE WHEN pnl > 0 THEN pnl END) as avg_win,
                AVG(CASE WHEN pnl < 0 THEN pnl END) as avg_loss
            FROM trade_history
        """)

        row = cursor.fetchone()
        wins, losses, total_pnl, avg_win, avg_loss = row

        conn.close()

        win_rate = wins / max(total_trades, 1)

        return {
            'total_trades': total_trades,
            'wins': wins or 0,
            'losses': losses or 0,
            'win_rate': win_rate,
            'total_pnl': total_pnl or 0.0,
            'avg_win': avg_win or 0.0,
            'avg_loss': avg_loss or 0.0
        }

    except Exception as e:
        logger.error(f"Error calculating performance metrics: {e}")
        return {
            'total_trades': 0,
            'win_rate': 0.0,
            'total_pnl': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0
        }


@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('dashboard.html')


@app.route('/api/status')
def api_status():
    """Get system status API."""
    return jsonify(get_system_status())


@app.route('/api/setups')
def api_setups():
    """Get active setups API."""
    return jsonify(get_active_setups())


@app.route('/api/trades')
def api_trades():
    """Get recent trades API."""
    return jsonify(get_recent_trades())


@app.route('/api/metrics')
def api_metrics():
    """Get performance metrics API."""
    return jsonify(get_performance_metrics())


@app.route('/api/all')
def api_all():
    """Get all dashboard data in one call."""
    return jsonify({
        'status': get_system_status(),
        'setups': get_active_setups(),
        'trades': get_recent_trades(),
        'metrics': get_performance_metrics()
    })


def run_dashboard(host='0.0.0.0', port=5000, debug=False):
    """Run the dashboard server."""
    logger.info(f"Starting SLOB dashboard on {host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    port = int(os.getenv('DASHBOARD_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

    run_dashboard(port=port, debug=debug)
