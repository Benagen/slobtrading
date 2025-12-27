#!/bin/bash
#
# Weekend 24-Hour Validation Run
#
# This script starts a 24-hour paper trading validation run
# to test system stability before Monday live trading.
#
# Usage: ./scripts/start_weekend_validation.sh
#

set -e  # Exit on error

echo "═══════════════════════════════════════════════════════════════"
echo "  SLOB Trading System - 24 Hour Validation Run"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Account: DUO282477"
echo "Mode: Monitor Only (no actual orders)"
echo "Duration: 24 hours"
echo "Port: 4002 (IB Gateway)"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Check if IB Gateway is running
echo "🔍 Checking IB Gateway connection..."
if ! nc -z localhost 4002 2>/dev/null; then
    echo "❌ ERROR: IB Gateway is not running on port 4002!"
    echo ""
    echo "Please start IB Gateway first:"
    echo "  1. Open IB Gateway"
    echo "  2. Login with paper trading credentials"
    echo "  3. Ensure port 4002 is configured"
    echo "  4. Run this script again"
    echo ""
    exit 1
fi
echo "✅ IB Gateway is running"
echo ""

# Check secrets
echo "🔍 Checking secrets..."
if [ ! -f "secrets/ib_account.txt" ]; then
    echo "❌ ERROR: secrets/ib_account.txt not found!"
    exit 1
fi
echo "✅ Secrets configured"
echo ""

# Check database
echo "🔍 Checking database..."
if [ ! -f "data/slob_state.db" ]; then
    echo "⚠️  Database not found, running migration..."
    python3 scripts/migrate_database.py
fi
echo "✅ Database ready"
echo ""

# Create logs directory
mkdir -p logs/

echo "═══════════════════════════════════════════════════════════════"
echo "  Starting 24-hour validation..."
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "📊 Logs will be written to: logs/trading.log"
echo "📊 To monitor in real-time: tail -f logs/trading.log"
echo ""
echo "🛑 To stop: Press Ctrl+C"
echo ""
echo "Starting in 3 seconds..."
sleep 3

# Start paper trading validation
python3 scripts/run_paper_trading.py \
    --account DUO282477 \
    --gateway \
    --duration 24 \
    --monitor-only

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Validation run completed!"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "  1. Review logs/trading.log for any errors"
echo "  2. Check setup detection accuracy"
echo "  3. If all looks good, ready for Monday live test!"
echo ""
