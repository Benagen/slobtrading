#!/usr/bin/env python3
"""
Health check script for SLOB trading system.

Checks:
- Database accessibility
- IB Gateway connection
- Recent activity

Exit codes:
- 0: All checks passed
- 1: One or more checks failed
"""

import sys
import sqlite3
import socket
from pathlib import Path
from datetime import datetime, timedelta

def check_database():
    """Check if state database is accessible."""
    try:
        db_path = Path("/app/data/slob_state.db")
        if not db_path.exists():
            # Database might not exist yet on first run
            return True, "Database not created yet (normal on first run)"

        conn = sqlite3.connect(str(db_path))
        conn.execute("SELECT 1")
        conn.close()
        return True, "Database accessible"
    except Exception as e:
        return False, f"Database error: {e}"

def check_ib_connection():
    """Check if IB Gateway is reachable."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex(('ib-gateway', 4002))
        sock.close()

        if result == 0:
            return True, "IB Gateway reachable"
        else:
            return False, f"IB Gateway not reachable (error code: {result})"
    except Exception as e:
        return False, f"IB connection check failed: {e}"

def check_candle_store():
    """Check if candle data is being stored."""
    try:
        db_path = Path("/app/data/candles.db")
        if not db_path.exists():
            return True, "Candle DB not created yet (normal on first run)"

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Check if we have recent data (within last 10 minutes)
        cursor.execute("""
            SELECT COUNT(*) FROM candles
            WHERE timestamp > datetime('now', '-10 minutes')
        """)
        recent_count = cursor.fetchone()[0]
        conn.close()

        if recent_count > 0:
            return True, f"Recent candles: {recent_count} in last 10 min"
        else:
            return True, "No recent candles (might be market closed)"
    except Exception as e:
        return False, f"Candle store check failed: {e}"

def main():
    """Run all health checks."""
    print("=" * 60)
    print("SLOB Trading System Health Check")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    checks = {
        "Database": check_database(),
        "IB Gateway": check_ib_connection(),
        "Candle Store": check_candle_store(),
    }

    all_passed = True
    for name, (passed, message) in checks.items():
        status = "✓" if passed else "✗"
        print(f"{status} {name:15s}: {message}")
        if not passed:
            all_passed = False

    print("=" * 60)

    if all_passed:
        print("Status: HEALTHY")
        sys.exit(0)
    else:
        print("Status: UNHEALTHY")
        sys.exit(1)

if __name__ == "__main__":
    main()
