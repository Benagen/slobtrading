#!/bin/bash
################################################################################
# SLOB Trading System - Production Monitoring Script
#
# Displays comprehensive system status including:
# - Docker container health
# - Database statistics
# - Recent logs
# - System resources
# - Trading metrics
# - Connection status
#
# Usage:
#   ./scripts/monitor.sh [--full] [--tail N] [--watch]
#
# Options:
#   --full      Show extended information (all logs, detailed stats)
#   --tail N    Show last N log lines (default: 50)
#   --watch     Continuous monitoring (refresh every 30s)
#   --json      Output in JSON format
#
################################################################################

set -u  # Exit on undefined variable

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DB_PATH="$PROJECT_ROOT/data/slob_state.db"
LOG_TAIL=50
FULL_MODE=false
JSON_MODE=false
WATCH_MODE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --full)
            FULL_MODE=true
            LOG_TAIL=200
            shift
            ;;
        --tail)
            LOG_TAIL="$2"
            shift 2
            ;;
        --watch)
            WATCH_MODE=true
            shift
            ;;
        --json)
            JSON_MODE=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

################################################################################
# Display Functions
################################################################################

print_header() {
    if [ "$JSON_MODE" = false ]; then
        echo ""
        echo -e "${BLUE}${BOLD}════════════════════════════════════════════════════════════════════════${NC}"
        echo -e "${BLUE}${BOLD}  $1${NC}"
        echo -e "${BLUE}${BOLD}════════════════════════════════════════════════════════════════════════${NC}"
    fi
}

print_section() {
    if [ "$JSON_MODE" = false ]; then
        echo ""
        echo -e "${CYAN}━━━ $1 ━━━${NC}"
    fi
}

print_metric() {
    if [ "$JSON_MODE" = false ]; then
        printf "  ${BOLD}%-30s${NC} %s\n" "$1:" "$2"
    fi
}

print_status() {
    local status=$1
    local message=$2

    if [ "$JSON_MODE" = false ]; then
        case $status in
            ok|running|healthy)
                echo -e "  ${GREEN}✓${NC} $message"
                ;;
            warning|degraded)
                echo -e "  ${YELLOW}⚠${NC} $message"
                ;;
            error|stopped|unhealthy)
                echo -e "  ${RED}✗${NC} $message"
                ;;
            *)
                echo -e "  ${BLUE}•${NC} $message"
                ;;
        esac
    fi
}

################################################################################
# Monitoring Functions
################################################################################

monitor_containers() {
    print_section "Docker Container Status"

    cd "$PROJECT_ROOT"

    if command -v docker-compose &> /dev/null; then
        # Get container status
        local container_output=$(docker-compose ps 2>&1)

        if [ $? -eq 0 ]; then
            if [ "$JSON_MODE" = false ]; then
                echo "$container_output"
            fi

            # Check if containers are running
            if echo "$container_output" | grep -q "Up"; then
                print_status "ok" "Containers are running"
            else
                print_status "error" "Containers are not running"
            fi
        else
            print_status "error" "Failed to get container status"
        fi
    else
        print_status "error" "docker-compose not found"
    fi
}

monitor_database() {
    print_section "Database Status"

    if [ -f "$DB_PATH" ]; then
        print_status "ok" "Database file exists: $DB_PATH"

        # Get database statistics
        if command -v sqlite3 &> /dev/null; then
            # Active setups
            local active_setups=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM active_setups WHERE state != 'SETUP_COMPLETE';" 2>/dev/null || echo "N/A")
            print_metric "Active Setups" "$active_setups"

            # Total trades
            local total_trades=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM trade_history;" 2>/dev/null || echo "N/A")
            print_metric "Total Trades" "$total_trades"

            # Total P&L
            local total_pnl=$(sqlite3 "$DB_PATH" "SELECT ROUND(SUM(pnl), 2) FROM trade_history;" 2>/dev/null || echo "N/A")
            print_metric "Total P&L" "\$$total_pnl"

            # Win rate
            local wins=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM trade_history WHERE outcome='WIN';" 2>/dev/null || echo "0")
            local total=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM trade_history WHERE outcome IS NOT NULL;" 2>/dev/null || echo "1")
            if [ "$total" -gt 0 ]; then
                local win_rate=$(echo "scale=1; $wins * 100 / $total" | bc 2>/dev/null || echo "N/A")
                print_metric "Win Rate" "$win_rate%"
            else
                print_metric "Win Rate" "N/A (no trades)"
            fi

            # Recent activity
            local recent_trades=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM trade_history WHERE entry_time > datetime('now', '-24 hours');" 2>/dev/null || echo "0")
            print_metric "Trades (Last 24h)" "$recent_trades"

            # Database size
            local db_size=$(du -h "$DB_PATH" | cut -f1)
            print_metric "Database Size" "$db_size"
        else
            print_status "warning" "sqlite3 not found - cannot query database"
        fi
    else
        print_status "error" "Database file not found: $DB_PATH"
    fi
}

monitor_logs() {
    print_section "Recent Logs (Last $LOG_TAIL lines)"

    cd "$PROJECT_ROOT"

    if command -v docker-compose &> /dev/null; then
        if [ "$FULL_MODE" = true ]; then
            docker-compose logs --tail="$LOG_TAIL" 2>&1
        else
            docker-compose logs --tail="$LOG_TAIL" 2>&1 | grep -E "(ERROR|CRITICAL|WARNING|SETUP|ORDER|✅|❌|⚠️)" || echo "No recent errors or warnings"
        fi
    else
        print_status "error" "docker-compose not found"
    fi
}

monitor_system_resources() {
    print_section "System Resources"

    # Disk usage
    if [ "$JSON_MODE" = false ]; then
        echo ""
        echo "Disk Usage:"
        df -h | grep -E "Filesystem|/$|/data" || df -h | head -2
    fi

    # Memory usage
    if [ "$JSON_MODE" = false ]; then
        echo ""
        echo "Memory Usage:"
        if command -v free &> /dev/null; then
            free -h
        else
            # macOS fallback
            vm_stat | grep -E "Pages (free|active|inactive|speculative|wired)" || echo "Memory stats unavailable"
        fi
    fi

    # Docker stats (if containers running)
    if command -v docker &> /dev/null; then
        local running_containers=$(docker ps -q 2>/dev/null)
        if [ -n "$running_containers" ]; then
            if [ "$JSON_MODE" = false ]; then
                echo ""
                echo "Docker Container Resources:"
                docker stats --no-stream 2>/dev/null || echo "Docker stats unavailable"
            fi
        fi
    fi
}

monitor_connection_status() {
    print_section "Connection Status"

    # Check if IB Gateway is reachable
    if command -v nc &> /dev/null; then
        if nc -z localhost 4002 2>/dev/null; then
            print_status "ok" "IB Gateway port 4002 is open"
        elif nc -z localhost 7497 2>/dev/null; then
            print_status "ok" "TWS port 7497 is open"
        else
            print_status "warning" "IB Gateway/TWS not reachable on localhost:4002 or :7497"
        fi
    fi

    # Check dashboard
    if command -v curl &> /dev/null; then
        if curl -s -o /dev/null -w "%{http_code}" http://localhost:5000 2>/dev/null | grep -q "200\|302"; then
            print_status "ok" "Dashboard accessible at http://localhost:5000"
        else
            print_status "warning" "Dashboard not accessible at http://localhost:5000"
        fi
    fi

    # Check Redis (if used)
    if command -v redis-cli &> /dev/null; then
        if redis-cli ping &>/dev/null; then
            print_status "ok" "Redis is running"
        else
            print_status "warning" "Redis not responding"
        fi
    fi
}

monitor_trading_metrics() {
    print_section "Trading Metrics (Last 7 Days)"

    if [ -f "$DB_PATH" ] && command -v sqlite3 &> /dev/null; then
        # Daily P&L
        local daily_pnl=$(sqlite3 "$DB_PATH" "
            SELECT
                DATE(entry_time) as date,
                ROUND(SUM(pnl), 2) as daily_pnl,
                COUNT(*) as trades
            FROM trade_history
            WHERE entry_time > datetime('now', '-7 days')
            GROUP BY DATE(entry_time)
            ORDER BY date DESC
            LIMIT 7;
        " 2>/dev/null)

        if [ -n "$daily_pnl" ]; then
            if [ "$JSON_MODE" = false ]; then
                echo ""
                printf "  %-12s %-15s %-10s\n" "Date" "Daily P&L" "Trades"
                echo "  ────────────────────────────────────────"
                echo "$daily_pnl" | while IFS='|' read -r date pnl trades; do
                    if (( $(echo "$pnl >= 0" | bc -l 2>/dev/null || echo 0) )); then
                        printf "  %-12s ${GREEN}%+14.2f${NC} %-10s\n" "$date" "$pnl" "$trades"
                    else
                        printf "  %-12s ${RED}%+14.2f${NC} %-10s\n" "$date" "$pnl" "$trades"
                    fi
                done
            fi
        else
            print_status "info" "No trades in the last 7 days"
        fi

        # Current drawdown
        local current_dd=$(sqlite3 "$DB_PATH" "
            SELECT ROUND(MIN(running_total), 2)
            FROM (
                SELECT SUM(pnl) OVER (ORDER BY entry_time) as running_total
                FROM trade_history
            );
        " 2>/dev/null || echo "N/A")

        if [ "$current_dd" != "N/A" ] && [ "$JSON_MODE" = false ]; then
            echo ""
            if (( $(echo "$current_dd < 0" | bc -l 2>/dev/null || echo 0) )); then
                print_metric "Current Drawdown" "${RED}\$$current_dd${NC}"
            else
                print_metric "Current Drawdown" "\$0.00"
            fi
        fi
    fi
}

monitor_error_summary() {
    print_section "Error Summary (Last 24h)"

    local log_dir="$PROJECT_ROOT/logs"
    if [ -d "$log_dir" ]; then
        local error_count=$(find "$log_dir" -name "*.log" -type f -mtime -1 -exec grep -c "ERROR\|CRITICAL" {} + 2>/dev/null | awk '{s+=$1} END {print s}')
        error_count=${error_count:-0}

        if [ "$error_count" -eq 0 ]; then
            print_status "ok" "No errors in the last 24 hours"
        elif [ "$error_count" -lt 10 ]; then
            print_status "warning" "$error_count errors found (check logs)"
        else
            print_status "error" "$error_count errors found (investigate immediately)"
        fi

        # Show recent critical errors
        if [ "$FULL_MODE" = true ]; then
            echo ""
            echo "Recent Critical Errors:"
            find "$log_dir" -name "*.log" -type f -mtime -1 -exec grep -h "CRITICAL" {} + 2>/dev/null | tail -5 || echo "  None"
        fi
    else
        print_status "warning" "Log directory not found: $log_dir"
    fi
}

################################################################################
# Main Monitoring Function
################################################################################

run_monitor() {
    if [ "$JSON_MODE" = false ]; then
        clear
        print_header "📊 SLOB Trading System Monitor"
        echo -e "${CYAN}Monitoring at: $(date)${NC}"
    fi

    # Run all monitoring checks
    monitor_containers
    monitor_database
    monitor_connection_status
    monitor_trading_metrics
    monitor_system_resources
    monitor_error_summary

    if [ "$FULL_MODE" = true ]; then
        monitor_logs
    fi

    if [ "$JSON_MODE" = false ]; then
        echo ""
        print_header "🔄 Monitoring Complete"
        echo "  Run with --watch for continuous monitoring"
        echo "  Run with --full for detailed logs"
        echo ""
    fi
}

################################################################################
# Watch Mode
################################################################################

if [ "$WATCH_MODE" = true ]; then
    while true; do
        run_monitor
        sleep 30
    done
else
    run_monitor
fi
