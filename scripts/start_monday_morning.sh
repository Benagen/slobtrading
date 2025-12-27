#!/bin/bash
#
# Monday Morning Startup Script
#
# Starts SLOB trading system for Monday live test
# Mode: Monitor-only first, enable trading later
#
# Usage: ./scripts/start_monday_morning.sh
#

set -e  # Exit on error

echo "═══════════════════════════════════════════════════════════════"
echo "  SLOB Trading System - Monday Morning Live Test"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Account: DUO282477 (Paper Trading)"
echo "Mode: Monitor Only (no actual orders initially)"
echo "Duration: 8 hours (full trading day)"
echo "Port: 4002 (IB Gateway)"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Pre-flight checks
echo "🔍 Running pre-flight checks..."
echo ""

# Check 1: IB Gateway
echo "1. Checking IB Gateway connection..."
if ! nc -z localhost 4002 2>/dev/null; then
    echo "   ❌ FAILED: IB Gateway is not running on port 4002!"
    echo ""
    echo "   Please start IB Gateway first:"
    echo "   1. Open IB Gateway"
    echo "   2. Login with paper trading credentials"
    echo "   3. Ensure port 4002 is configured"
    echo "   4. Run this script again"
    echo ""
    exit 1
fi
echo "   ✅ IB Gateway is running"
echo ""

# Check 2: Secrets
echo "2. Checking secrets..."
if [ ! -f "secrets/ib_account.txt" ]; then
    echo "   ❌ FAILED: secrets/ib_account.txt not found!"
    exit 1
fi
ACCOUNT=$(cat secrets/ib_account.txt)
echo "   ✅ Account loaded: $ACCOUNT"
echo ""

# Check 3: Database
echo "3. Checking database..."
if [ ! -f "data/slob_state.db" ]; then
    echo "   ⚠️  Database not found, running migration..."
    python3 scripts/migrate_database.py
fi
echo "   ✅ Database ready"
echo ""

# Check 4: Logs directory
echo "4. Setting up logs..."
mkdir -p logs/

# Backup old logs if they exist
if [ -f "logs/trading.log" ]; then
    BACKUP_NAME="logs/trading_$(date '+%Y%m%d_%H%M%S').log"
    mv logs/trading.log "$BACKUP_NAME"
    echo "   📦 Old logs backed up to: $BACKUP_NAME"
fi
echo "   ✅ Logs directory ready"
echo ""

# Check 5: Account balance verification
echo "5. Verifying account balance..."
BALANCE_CHECK=$(python3 -c "
from ib_insync import IB
try:
    ib = IB()
    ib.connect('localhost', 4002, clientId=99)
    accounts = ib.managedAccounts()
    balance = 'Unknown'
    for av in ib.accountValues():
        if av.tag == 'TotalCashValue':
            balance = av.value
            break
    ib.disconnect()
    print(f'{accounts[0]}|{balance}')
except Exception as e:
    print(f'ERROR|{e}')
" 2>&1)

if [[ $BALANCE_CHECK == ERROR* ]]; then
    echo "   ⚠️  WARNING: Could not verify balance"
    echo "   Error: ${BALANCE_CHECK#ERROR|}"
    echo "   Continuing anyway..."
else
    IFS='|' read -r ACC BAL <<< "$BALANCE_CHECK"
    echo "   ✅ Account: $ACC"
    echo "   ✅ Balance: \$$BAL"
fi
echo ""

# All checks passed
echo "═══════════════════════════════════════════════════════════════"
echo "  ✅ All pre-flight checks passed!"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Show market hours
echo "📅 Market Hours (ET):"
echo "   Pre-market:  04:00 - 09:30"
echo "   Regular:     09:30 - 16:00"
echo "   After-hours: 16:00 - 20:00"
echo ""

# Current time check
CURRENT_HOUR=$(date '+%H')
if [ $CURRENT_HOUR -lt 9 ]; then
    echo "⏰ Current time: Pre-market"
    echo "   Market opens at 09:30 ET"
    echo "   Starting in monitor-only mode..."
elif [ $CURRENT_HOUR -ge 16 ]; then
    echo "⏰ Current time: After-hours"
    echo "   Regular market closed at 16:00 ET"
    echo "   You can still monitor, but no setups expected"
else
    echo "⏰ Current time: Regular market hours"
    echo "   Starting monitoring now..."
fi
echo ""

echo "═══════════════════════════════════════════════════════════════"
echo "  Starting SLOB Trading System..."
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "📊 Logs: logs/trading.log"
echo "📊 Monitor: tail -f logs/trading.log (in another terminal)"
echo "📊 Dashboard: http://localhost:5000 (if enabled)"
echo ""
echo "🛑 To stop: Press Ctrl+C"
echo ""
echo "⚠️  MONITOR-ONLY MODE: No orders will be placed"
echo "   To enable trading later, restart without --monitor-only flag"
echo ""
echo "Starting in 3 seconds..."
sleep 3

# Start the system
python3 scripts/run_paper_trading.py \
    --account DUO282477 \
    --gateway \
    --duration 8 \
    --monitor-only

# If we get here, system stopped normally
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Session ended"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "📊 Review logs: logs/trading.log"
echo "📊 Check database: sqlite3 data/slob_state.db"
echo ""
echo "Next steps:"
echo "  1. Review logs for any errors"
echo "  2. If all looks good, restart with trading enabled:"
echo "     python3 scripts/run_paper_trading.py --account DUO282477 --gateway --duration 8"
echo "     (without --monitor-only flag)"
echo ""
