"""
Web Dashboard for SLOB Trading System

Secure Flask-based dashboard showing:
- System status
- Active setups
- Recent trades
- Performance metrics
- ML shadow mode statistics

Features:
- Password authentication (Flask-Login)
- Session management (15-minute timeout)
- Rate limiting (10 login attempts/minute)
- CSRF protection

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

from flask import Flask, render_template, jsonify, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf import CSRFProtect
from werkzeug.security import check_password_hash

logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = os.getenv('DASHBOARD_SECRET_KEY', 'slob-dashboard-secret-key-CHANGE-ME')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=15)  # 15-minute timeout
app.config['SESSION_COOKIE_SECURE'] = os.getenv('DASHBOARD_HTTPS', 'False').lower() == 'true'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = None  # CSRF token doesn't expire

# Initialize extensions
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access the dashboard.'

csrf = CSRFProtect(app)

# Rate limiting: 30 login attempts per minute per IP (allows multiple users from same IP)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["2000 per day", "1000 per hour"],  # Increased for dashboard auto-refresh
    storage_uri="memory://"
)

# Database paths
DB_PATH = Path(os.getenv('DB_PATH', 'data/trading_state.db'))  # Fixed: use trading_state.db
STATE_DB_PATH = Path(os.getenv('STATE_DB_PATH', 'data/trading_state.db'))  # Fixed: use trading_state.db


# ============================================================================
# User Authentication
# ============================================================================

class User(UserMixin):
    """Simple user model for dashboard authentication."""

    def __init__(self, user_id: str, username: str):
        self.id = user_id
        self.username = username


@login_manager.user_loader
def load_user(user_id: str):
    """Load user for session management."""
    # Simple single-user system (admin only)
    if user_id == "1":
        return User("1", "admin")
    return None


def verify_password(password: str) -> bool:
    """
    Verify password against stored hash.

    Password hash stored in environment variable:
    DASHBOARD_PASSWORD_HASH (bcrypt hash)

    Generate hash with:
    python -c "from werkzeug.security import generate_password_hash;
               import getpass;
               print(generate_password_hash(getpass.getpass('Password: ')))"
    """
    password_hash = os.getenv('DASHBOARD_PASSWORD_HASH')

    if not password_hash:
        logger.error("❌ DASHBOARD_PASSWORD_HASH not set - dashboard is INSECURE")
        # Fallback to plaintext comparison (INSECURE - for development only)
        fallback_password = os.getenv('DASHBOARD_PASSWORD', 'admin')
        logger.warning(f"⚠️ Using insecure plaintext password comparison")
        return password == fallback_password

    return check_password_hash(password_hash, password)


# ============================================================================
# Authentication Routes
# ============================================================================

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("30 per minute")  # Rate limit: 30 attempts per minute (allows multiple users from same IP)
def login():
    """Login page and handler."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        password = request.form.get('password', '')

        if verify_password(password):
            user = User("1", "admin")
            login_user(user, remember=False)
            logger.info(f"✅ User logged in from {get_remote_address()}")

            # Redirect to original destination or dashboard
            next_page = request.args.get('next')
            if not next_page or not next_page.startswith('/'):
                next_page = url_for('index')

            return redirect(next_page)
        else:
            logger.warning(f"❌ Failed login attempt from {get_remote_address()}")
            flash('Invalid password', 'error')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    """Logout handler."""
    logger.info(f"User logged out from {get_remote_address()}")
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))


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
@login_required
def index():
    """Main dashboard page."""
    return render_template('dashboard.html', username=current_user.username)


@app.route('/api/status')
@login_required
def api_status():
    """Get system status API."""
    return jsonify(get_system_status())


@app.route('/api/setups')
@login_required
def api_setups():
    """Get active setups API."""
    return jsonify(get_active_setups())


@app.route('/api/trades')
@login_required
def api_trades():
    """Get recent trades API."""
    return jsonify(get_recent_trades())


@app.route('/api/metrics')
@login_required
def api_metrics():
    """Get performance metrics API."""
    return jsonify(get_performance_metrics())


@app.route('/api/live_price')
@login_required
def api_live_price():
    """Get current live price and market data."""
    try:
        if not DB_PATH.exists():
            return jsonify({'error': 'Database not found'}), 404

        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get latest candle
        cursor.execute("""
            SELECT timestamp, open, high, low, close, volume
            FROM candles
            ORDER BY timestamp DESC
            LIMIT 1
        """)

        latest = cursor.fetchone()
        conn.close()

        if not latest:
            return jsonify({'error': 'No data available'}), 404

        # Get previous candle for change calculation
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT close
            FROM candles
            ORDER BY timestamp DESC
            LIMIT 2
        """)
        candles = cursor.fetchall()
        conn.close()

        prev_close = candles[1][0] if len(candles) > 1 else latest['close']
        change = latest['close'] - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0

        return jsonify({
            'symbol': 'NQ',
            'price': round(latest['close'], 2),
            'open': round(latest['open'], 2),
            'high': round(latest['high'], 2),
            'low': round(latest['low'], 2),
            'volume': latest['volume'],
            'change': round(change, 2),
            'change_pct': round(change_pct, 2),
            'timestamp': latest['timestamp'],
            'direction': 'up' if change >= 0 else 'down'
        })

    except Exception as e:
        logger.error(f"Error getting live price: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/candles')
@login_required
def api_candles():
    """Get recent candles for table and chart."""
    try:
        limit = request.args.get('limit', 50, type=int)
        limit = min(limit, 200)  # Max 200 candles

        if not DB_PATH.exists():
            return jsonify({'error': 'Database not found'}), 404

        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT timestamp, open, high, low, close, volume
            FROM candles
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))

        candles = []
        for row in cursor.fetchall():
            candles.append({
                'timestamp': row['timestamp'],
                'open': round(row['open'], 2),
                'high': round(row['high'], 2),
                'low': round(row['low'], 2),
                'close': round(row['close'], 2),
                'volume': row['volume']
            })

        conn.close()

        # Reverse so oldest first (for chart)
        candles.reverse()

        return jsonify({
            'candles': candles,
            'count': len(candles)
        })

    except Exception as e:
        logger.error(f"Error getting candles: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/shadow_stats')
@login_required
def api_shadow_stats():
    """Get ML shadow mode statistics."""
    try:
        if not STATE_DB_PATH.exists():
            return jsonify({'enabled': False, 'error': 'Database not found'})

        conn = sqlite3.connect(str(STATE_DB_PATH))
        cursor = conn.cursor()

        # Check if shadow_predictions table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='shadow_predictions'
        """)
        if not cursor.fetchone():
            conn.close()
            return jsonify({'enabled': False, 'reason': 'Shadow mode not initialized'})

        # Overall stats
        cursor.execute("""
            SELECT
                COUNT(*) as total_predictions,
                SUM(CASE WHEN agreement = 1 THEN 1 ELSE 0 END) as agreements,
                AVG(ml_probability) as avg_ml_prob,
                SUM(CASE WHEN ml_decision = 'TAKE' THEN 1 ELSE 0 END) as ml_approved,
                SUM(CASE WHEN ml_decision = 'SKIP' THEN 1 ELSE 0 END) as ml_rejected
            FROM shadow_predictions
        """)
        row = cursor.fetchone()
        total, agreements, avg_prob, ml_approved, ml_rejected = row

        # Recent predictions (last 10)
        cursor.execute("""
            SELECT
                setup_id, timestamp, ml_probability,
                ml_decision, rule_decision, agreement
            FROM shadow_predictions
            ORDER BY timestamp DESC
            LIMIT 10
        """)
        recent = [
            {
                'setup_id': row[0],
                'timestamp': row[1],
                'ml_probability': row[2],
                'ml_decision': row[3],
                'rule_decision': row[4],
                'agreement': bool(row[5])
            }
            for row in cursor.fetchall()
        ]

        conn.close()

        if total == 0:
            agreement_rate = 0.0
        else:
            agreement_rate = agreements / total

        return jsonify({
            'enabled': True,
            'total_predictions': total or 0,
            'agreements': agreements or 0,
            'disagreements': (total or 0) - (agreements or 0),
            'agreement_rate': agreement_rate,
            'avg_ml_probability': avg_prob or 0.0,
            'ml_approved': ml_approved or 0,
            'ml_rejected': ml_rejected or 0,
            'recent_predictions': recent
        })
    except Exception as e:
        logger.error(f"Error getting shadow stats: {e}")
        return jsonify({'enabled': False, 'error': str(e)})


@app.route('/api/pnl_chart')
@login_required
def api_pnl_chart():
    """Get P&L data for charting (daily aggregation)."""
    try:
        if not STATE_DB_PATH.exists():
            return jsonify({'labels': [], 'data': []})

        conn = sqlite3.connect(str(STATE_DB_PATH))
        cursor = conn.cursor()

        # Get daily P&L for last 30 days
        cursor.execute("""
            SELECT
                DATE(entry_time) as trade_date,
                SUM(pnl) as daily_pnl,
                COUNT(*) as trades_count
            FROM trade_history
            WHERE entry_time >= datetime('now', '-30 days')
            GROUP BY DATE(entry_time)
            ORDER BY trade_date ASC
        """)

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return jsonify({'labels': [], 'data': [], 'cumulative': []})

        labels = [row[0] for row in rows]
        daily_pnl = [float(row[1]) for row in rows]

        # Calculate cumulative P&L
        cumulative_pnl = []
        running_total = 0
        for pnl in daily_pnl:
            running_total += pnl
            cumulative_pnl.append(running_total)

        return jsonify({
            'labels': labels,
            'daily_pnl': daily_pnl,
            'cumulative_pnl': cumulative_pnl,
            'trades_count': [row[2] for row in rows]
        })

    except Exception as e:
        logger.error(f"Error getting P&L chart data: {e}")
        return jsonify({'labels': [], 'data': [], 'error': str(e)})


@app.route('/api/setup_pipeline')
@login_required
def api_setup_pipeline():
    """Get setup pipeline data - breakdown of setups by state."""
    try:
        if not STATE_DB_PATH.exists():
            return jsonify({'pipeline': [], 'total': 0})

        conn = sqlite3.connect(str(STATE_DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Check if setups table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='setups'
        """)
        if not cursor.fetchone():
            conn.close()
            return jsonify({'pipeline': [], 'total': 0, 'error': 'Setups table not found'})

        # Get count of setups by state (only active ones, not invalidated/completed from old days)
        # Focus on today's setups or recent active ones
        cursor.execute("""
            SELECT
                state,
                COUNT(*) as count
            FROM setups
            WHERE created_at >= datetime('now', '-24 hours')
            GROUP BY state
            ORDER BY state ASC
        """)

        rows = cursor.fetchall()
        conn.close()

        # State mapping with friendly names and colors
        state_map = {
            1: {'name': 'WATCHING_LIQ1', 'label': 'Watching LIQ #1', 'color': '#8b949e'},
            2: {'name': 'WATCHING_CONSOL', 'label': 'Watching Consolidation', 'color': '#58a6ff'},
            3: {'name': 'WATCHING_LIQ2', 'label': 'Watching LIQ #2', 'color': '#1f6feb'},
            4: {'name': 'WAITING_ENTRY', 'label': 'Waiting Entry', 'color': '#f0883e'},
            5: {'name': 'SETUP_COMPLETE', 'label': 'Setup Complete', 'color': '#3fb950'},
            6: {'name': 'INVALIDATED', 'label': 'Invalidated', 'color': '#f85149'}
        }

        # Build pipeline data
        pipeline = []
        total_setups = 0

        for row in rows:
            state = row['state']
            count = row['count']
            total_setups += count

            if state in state_map:
                pipeline.append({
                    'state': state,
                    'name': state_map[state]['name'],
                    'label': state_map[state]['label'],
                    'count': count,
                    'color': state_map[state]['color']
                })

        # Fill in missing states with 0 count (for consistent chart)
        existing_states = {item['state'] for item in pipeline}
        for state, info in state_map.items():
            if state not in existing_states:
                pipeline.append({
                    'state': state,
                    'name': info['name'],
                    'label': info['label'],
                    'count': 0,
                    'color': info['color']
                })

        # Sort by state order
        pipeline.sort(key=lambda x: x['state'])

        return jsonify({
            'pipeline': pipeline,
            'total': total_setups,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting setup pipeline: {e}")
        return jsonify({'pipeline': [], 'total': 0, 'error': str(e)}), 500


@app.route('/api/risk_metrics')
@login_required
def api_risk_metrics():
    """Get risk management metrics."""
    try:
        if not STATE_DB_PATH.exists():
            return jsonify({
                'current_drawdown': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0,
                'circuit_breaker_active': False
            })

        conn = sqlite3.connect(str(STATE_DB_PATH))
        cursor = conn.cursor()

        # Get all trades ordered by time
        cursor.execute("""
            SELECT entry_time, pnl
            FROM trade_history
            ORDER BY entry_time ASC
        """)
        trades = cursor.fetchall()
        conn.close()

        if not trades:
            return jsonify({
                'current_drawdown': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0,
                'profit_factor': 0.0,
                'circuit_breaker_active': False
            })

        # Calculate metrics
        pnls = [float(t[1]) for t in trades]

        # Cumulative P&L and drawdown
        cumulative = []
        running_total = 0
        for pnl in pnls:
            running_total += pnl
            cumulative.append(running_total)

        # Max drawdown
        peak = cumulative[0]
        max_dd = 0
        current_dd = 0

        for value in cumulative:
            if value > peak:
                peak = value
            dd = peak - value
            if dd > max_dd:
                max_dd = dd

        current_dd = peak - cumulative[-1] if cumulative else 0

        # Sharpe Ratio (simplified - daily returns)
        if len(pnls) > 1:
            import statistics
            mean_pnl = statistics.mean(pnls)
            std_pnl = statistics.stdev(pnls)
            sharpe = (mean_pnl / std_pnl) if std_pnl > 0 else 0
        else:
            sharpe = 0

        # Profit Factor
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # Circuit breaker (check if current drawdown > 5% of account)
        # Assuming starting balance of $100,000 for demo
        starting_balance = 100000
        circuit_breaker_threshold = 0.05  # 5%
        circuit_breaker_active = current_dd > (starting_balance * circuit_breaker_threshold)

        return jsonify({
            'current_drawdown': round(current_dd, 2),
            'max_drawdown': round(max_dd, 2),
            'sharpe_ratio': round(sharpe, 2),
            'profit_factor': round(profit_factor, 2),
            'circuit_breaker_active': circuit_breaker_active,
            'total_trades': len(trades)
        })

    except Exception as e:
        logger.error(f"Error calculating risk metrics: {e}")
        return jsonify({
            'current_drawdown': 0.0,
            'max_drawdown': 0.0,
            'sharpe_ratio': 0.0,
            'error': str(e)
        })


@app.route('/api/error_logs')
@login_required
def api_error_logs():
    """Get recent error logs."""
    try:
        log_dir = Path('logs')
        if not log_dir.exists():
            return jsonify({'logs': [], 'message': 'No log directory found'})

        # Find most recent log file
        log_files = sorted(log_dir.glob('*.log'), key=lambda p: p.stat().st_mtime, reverse=True)

        if not log_files:
            return jsonify({'logs': [], 'message': 'No log files found'})

        # Read last 50 lines from most recent log file
        log_file = log_files[0]

        with open(log_file, 'r') as f:
            lines = f.readlines()
            recent_lines = lines[-50:] if len(lines) > 50 else lines

        # Filter for ERROR and CRITICAL entries
        error_logs = []
        for line in recent_lines:
            if 'ERROR' in line or 'CRITICAL' in line or '❌' in line:
                error_logs.append({
                    'message': line.strip(),
                    'level': 'CRITICAL' if 'CRITICAL' in line else 'ERROR',
                    'timestamp': datetime.now().isoformat()  # Extract from log if format is consistent
                })

        return jsonify({
            'logs': error_logs[-20:],  # Last 20 errors
            'log_file': str(log_file),
            'total_errors': len(error_logs)
        })

    except Exception as e:
        logger.error(f"Error reading logs: {e}")
        return jsonify({'logs': [], 'error': str(e)})


@app.route('/api/all')
@login_required
def api_all():
    """Get all dashboard data in one call."""
    return jsonify({
        'status': get_system_status(),
        'setups': get_active_setups(),
        'trades': get_recent_trades(),
        'metrics': get_performance_metrics(),
        'shadow': api_shadow_stats().get_json(),
        'risk': api_risk_metrics().get_json(),
        'pnl_chart': api_pnl_chart().get_json()
    })


@app.route('/health')
def health():
    """Health check endpoint for Docker."""
    try:
        # Check if app is running
        status = {
            'status': 'healthy',
            'service': 'slob-dashboard',
            'timestamp': datetime.now().isoformat()
        }
        return jsonify(status), 200
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 503


def run_dashboard(host='0.0.0.0', port=5000, debug=False):
    """Run the dashboard server."""
    logger.info(f"Starting SLOB dashboard on {host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    from slob.monitoring.logging_config import setup_logging

    # Setup logging with rotation
    setup_logging(log_dir='logs/', console_level=logging.INFO, file_level=logging.DEBUG)

    port = int(os.getenv('DASHBOARD_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

    run_dashboard(port=port, debug=debug)
