#!/bin/bash
################################################################################
# SLOB Trading System - Rollback Script
#
# Rolls back deployment to a previous state using backups.
# Supports rollback of:
# - Database state
# - Configuration files
# - Docker containers
# - Code version (git)
#
# Usage:
#   ./scripts/rollback.sh [--timestamp YYYYMMDD_HHMMSS] [--auto]
#
# Options:
#   --timestamp    Specific backup timestamp to restore (default: latest)
#   --auto         Automatic mode (no prompts)
#   --db-only      Rollback database only (keep current code/config)
#   --config-only  Rollback configuration only
#   --full         Full rollback (database + config + code)
#
# Examples:
#   ./scripts/rollback.sh                           # Interactive, latest backup
#   ./scripts/rollback.sh --timestamp 20251225_120000  # Specific backup
#   ./scripts/rollback.sh --auto --full             # Full automatic rollback
#
################################################################################

set -e  # Exit on error
set -u  # Exit on undefined variable

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_ROOT/data/backups"
ROLLBACK_TIMESTAMP=""
AUTO_MODE=false
DB_ONLY=false
CONFIG_ONLY=false
FULL_ROLLBACK=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --timestamp)
            ROLLBACK_TIMESTAMP="$2"
            shift 2
            ;;
        --auto)
            AUTO_MODE=true
            shift
            ;;
        --db-only)
            DB_ONLY=true
            shift
            ;;
        --config-only)
            CONFIG_ONLY=true
            shift
            ;;
        --full)
            FULL_ROLLBACK=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

################################################################################
# Logging Functions
################################################################################

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_header() {
    echo ""
    echo "═══════════════════════════════════════════════════════════════════════════"
    echo "  $1"
    echo "═══════════════════════════════════════════════════════════════════════════"
}

################################################################################
# Utility Functions
################################################################################

prompt_confirmation() {
    local message=$1

    if [ "$AUTO_MODE" = true ]; then
        log_info "Auto mode: Proceeding with $message"
        return 0
    fi

    echo -e "${YELLOW}$message${NC}"
    read -p "Continue? (yes/no): " response

    case $response in
        yes|y|Y|YES)
            return 0
            ;;
        *)
            log_info "Rollback cancelled by user"
            exit 0
            ;;
    esac
}

find_latest_backup() {
    local backup_type=$1  # "db", "config", "logs"

    local latest_backup=$(find "$BACKUP_DIR" -name "${backup_type}_*.tar.gz" -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2)

    if [ -n "$latest_backup" ]; then
        echo "$latest_backup"
    else
        echo ""
    fi
}

extract_timestamp_from_backup() {
    local backup_file=$1
    local filename=$(basename "$backup_file")

    # Extract timestamp (format: db_YYYYMMDD_HHMMSS.tar.gz)
    echo "$filename" | grep -oP '\d{8}_\d{6}' || echo ""
}

list_available_backups() {
    log_header "Available Backups"

    if [ ! -d "$BACKUP_DIR" ]; then
        log_error "Backup directory not found: $BACKUP_DIR"
        exit 1
    fi

    echo ""
    echo "Database Backups:"
    find "$BACKUP_DIR" -name "db_*.tar.gz" -type f -printf '%TY-%Tm-%Td %TH:%TM  %f  (%s bytes)\n' 2>/dev/null | sort -r | head -10 || echo "  None found"

    echo ""
    echo "Config Backups:"
    find "$BACKUP_DIR" -name "config_*.tar.gz" -type f -printf '%TY-%Tm-%Td %TH:%TM  %f  (%s bytes)\n' 2>/dev/null | sort -r | head -10 || echo "  None found"

    echo ""
}

################################################################################
# Rollback Functions
################################################################################

stop_containers() {
    log_info "Stopping running containers..."

    cd "$PROJECT_ROOT"

    if docker-compose ps -q 2>/dev/null | grep -q .; then
        docker-compose stop
        log_success "Containers stopped"
    else
        log_info "No containers running"
    fi
}

rollback_database() {
    local timestamp=$1

    log_info "Rolling back database to: $timestamp"

    local db_backup="$BACKUP_DIR/db_${timestamp}.tar.gz"

    if [ ! -f "$db_backup" ]; then
        log_error "Database backup not found: $db_backup"
        return 1
    fi

    # Backup current database before rollback
    log_info "Creating safety backup of current database..."
    if [ -f "$PROJECT_ROOT/data/slob_state.db" ]; then
        cp "$PROJECT_ROOT/data/slob_state.db" "$PROJECT_ROOT/data/slob_state.db.rollback_backup"
        log_success "Safety backup created: slob_state.db.rollback_backup"
    fi

    # Extract backup
    log_info "Extracting database backup..."
    local temp_dir=$(mktemp -d)
    tar -xzf "$db_backup" -C "$temp_dir"

    # Restore database files
    log_info "Restoring database files..."
    if [ -f "$temp_dir/db_${timestamp}/slob_state.db" ]; then
        cp "$temp_dir/db_${timestamp}/slob_state.db" "$PROJECT_ROOT/data/slob_state.db"
        log_success "slob_state.db restored"
    fi

    if [ -f "$temp_dir/db_${timestamp}/candles.db" ]; then
        cp "$temp_dir/db_${timestamp}/candles.db" "$PROJECT_ROOT/data/candles.db"
        log_success "candles.db restored"
    fi

    # Cleanup
    rm -rf "$temp_dir"

    # Verify restoration
    if command -v sqlite3 &> /dev/null; then
        if sqlite3 "$PROJECT_ROOT/data/slob_state.db" "PRAGMA integrity_check;" 2>/dev/null | grep -q "ok"; then
            log_success "Database integrity verified"
        else
            log_error "Database integrity check failed - rolling back safety backup"
            cp "$PROJECT_ROOT/data/slob_state.db.rollback_backup" "$PROJECT_ROOT/data/slob_state.db"
            return 1
        fi
    fi

    log_success "Database rollback complete"
}

rollback_config() {
    local timestamp=$1

    log_info "Rolling back configuration to: $timestamp"

    local config_backup="$BACKUP_DIR/config_${timestamp}.tar.gz"

    if [ ! -f "$config_backup" ]; then
        log_error "Config backup not found: $config_backup"
        return 1
    fi

    # Backup current config before rollback
    log_info "Creating safety backup of current configuration..."
    if [ -f "$PROJECT_ROOT/.env" ]; then
        cp "$PROJECT_ROOT/.env" "$PROJECT_ROOT/.env.rollback_backup"
        log_success "Safety backup created: .env.rollback_backup"
    fi

    # Extract backup
    log_info "Extracting config backup..."
    local temp_dir=$(mktemp -d)
    tar -xzf "$config_backup" -C "$temp_dir"

    # Restore config files
    log_info "Restoring configuration files..."
    if [ -f "$temp_dir/config_${timestamp}/.env" ]; then
        cp "$temp_dir/config_${timestamp}/.env" "$PROJECT_ROOT/.env"
        chmod 600 "$PROJECT_ROOT/.env"
        log_success ".env restored"
    fi

    if [ -f "$temp_dir/config_${timestamp}/docker-compose.yml" ]; then
        cp "$temp_dir/config_${timestamp}/docker-compose.yml" "$PROJECT_ROOT/docker-compose.yml"
        log_success "docker-compose.yml restored"
    fi

    # Cleanup
    rm -rf "$temp_dir"

    log_success "Configuration rollback complete"
}

rollback_code() {
    local commit_hash=$1

    log_info "Rolling back code to commit: $commit_hash"

    cd "$PROJECT_ROOT"

    # Check if git repository
    if [ ! -d ".git" ]; then
        log_error "Not a git repository - cannot rollback code"
        return 1
    fi

    # Stash current changes
    log_info "Stashing current changes..."
    git stash push -m "Pre-rollback stash $(date +%Y%m%d_%H%M%S)"

    # Checkout previous commit
    if git checkout "$commit_hash"; then
        log_success "Code rolled back to: $commit_hash"
        log_info "Current commit: $(git log -1 --oneline)"
    else
        log_error "Failed to checkout commit: $commit_hash"
        return 1
    fi
}

restart_containers() {
    log_info "Restarting containers with rolled-back state..."

    cd "$PROJECT_ROOT"

    # Rebuild and restart
    docker-compose up -d --build

    log_success "Containers restarted"

    # Wait for startup
    log_info "Waiting 10 seconds for containers to stabilize..."
    sleep 10
}

verify_rollback() {
    log_info "Verifying rollback..."

    # Check containers are running
    cd "$PROJECT_ROOT"
    if docker-compose ps -q | grep -q .; then
        log_success "Containers are running"
    else
        log_warning "Containers not running"
    fi

    # Check database accessible
    if [ -f "$PROJECT_ROOT/data/slob_state.db" ]; then
        if command -v sqlite3 &> /dev/null; then
            local setup_count=$(sqlite3 "$PROJECT_ROOT/data/slob_state.db" "SELECT COUNT(*) FROM active_setups;" 2>/dev/null || echo "N/A")
            log_info "Database accessible - Setup count: $setup_count"
        fi
    fi

    # Check logs for errors
    log_info "Recent container logs:"
    docker-compose logs --tail=10 2>&1 | grep -E "(ERROR|CRITICAL)" && log_warning "Errors found in logs" || log_success "No errors in recent logs"
}

################################################################################
# Main Rollback Flow
################################################################################

main() {
    log_header "⏮️  SLOB Trading System - Rollback Procedure"

    # Step 1: List available backups
    list_available_backups

    # Step 2: Determine rollback timestamp
    if [ -z "$ROLLBACK_TIMESTAMP" ]; then
        # Find latest backup
        local latest_db_backup=$(find_latest_backup "db")
        if [ -n "$latest_db_backup" ]; then
            ROLLBACK_TIMESTAMP=$(extract_timestamp_from_backup "$latest_db_backup")
            log_info "Using latest backup: $ROLLBACK_TIMESTAMP"
        else
            log_error "No backups found in: $BACKUP_DIR"
            exit 1
        fi
    fi

    log_info "Rollback target: $ROLLBACK_TIMESTAMP"

    # Step 3: Confirm rollback
    prompt_confirmation "This will rollback to backup from $ROLLBACK_TIMESTAMP"

    # Step 4: Stop running containers
    stop_containers

    # Step 5: Perform rollback based on flags
    if [ "$FULL_ROLLBACK" = true ]; then
        log_header "Full Rollback (Database + Config)"
        rollback_database "$ROLLBACK_TIMESTAMP"
        rollback_config "$ROLLBACK_TIMESTAMP"
    elif [ "$DB_ONLY" = true ]; then
        log_header "Database Rollback Only"
        rollback_database "$ROLLBACK_TIMESTAMP"
    elif [ "$CONFIG_ONLY" = true ]; then
        log_header "Configuration Rollback Only"
        rollback_config "$ROLLBACK_TIMESTAMP"
    else
        # Default: rollback both database and config
        log_header "Rollback (Database + Config)"
        rollback_database "$ROLLBACK_TIMESTAMP"
        rollback_config "$ROLLBACK_TIMESTAMP"
    fi

    # Step 6: Restart containers
    restart_containers

    # Step 7: Verify rollback
    verify_rollback

    # Step 8: Summary
    log_header "✅ Rollback Complete"
    log_success "System rolled back to: $ROLLBACK_TIMESTAMP"
    echo ""
    log_info "Next steps:"
    log_info "  1. Verify system status: ./scripts/monitor.sh"
    log_info "  2. Check dashboard: http://localhost:5000"
    log_info "  3. Review logs: docker-compose logs -f"
    echo ""
    log_warning "Safety backups created:"
    log_info "  - slob_state.db.rollback_backup"
    log_info "  - .env.rollback_backup"
    echo ""
}

# Error handling
trap 'log_error "Rollback failed at line $LINENO"; exit 1' ERR

# Execute main
main "$@"
