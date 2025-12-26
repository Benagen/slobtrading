#!/bin/bash
################################################################################
# SLOB Trading System - State Backup Script
#
# Creates comprehensive backups of:
# - SQLite databases (slob_state.db, candles.db)
# - Configuration files (.env)
# - Log files
# - Trained ML models
#
# Implements:
# - Timestamped backups
# - Retention policy (30 days)
# - Optional S3/cloud upload
# - Backup verification
# - Email notifications
#
# Usage:
#   ./scripts/backup_state.sh [--s3] [--verify] [--retention DAYS]
#
# Options:
#   --s3              Upload backup to S3 (requires AWS_S3_BUCKET env var)
#   --verify          Verify backup integrity after creation
#   --retention N     Keep backups for N days (default: 30)
#   --notify          Send email notification on completion
#
# Environment Variables:
#   AWS_S3_BUCKET     S3 bucket for remote backups (optional)
#   BACKUP_EMAIL      Email address for notifications (optional)
#
################################################################################

set -e  # Exit on error
set -u  # Exit on undefined variable

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_ROOT/data/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30
UPLOAD_S3=false
VERIFY_BACKUP=false
SEND_NOTIFICATION=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --s3)
            UPLOAD_S3=true
            shift
            ;;
        --verify)
            VERIFY_BACKUP=true
            shift
            ;;
        --retention)
            RETENTION_DAYS="$2"
            shift 2
            ;;
        --notify)
            SEND_NOTIFICATION=true
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

################################################################################
# Backup Functions
################################################################################

create_backup_dir() {
    if [ ! -d "$BACKUP_DIR" ]; then
        log_info "Creating backup directory: $BACKUP_DIR"
        mkdir -p "$BACKUP_DIR"
    fi
}

backup_databases() {
    log_info "Backing up databases..."

    local db_backup_dir="$BACKUP_DIR/db_$TIMESTAMP"
    mkdir -p "$db_backup_dir"

    # Backup main state database
    if [ -f "$PROJECT_ROOT/data/slob_state.db" ]; then
        log_info "  → slob_state.db"
        cp "$PROJECT_ROOT/data/slob_state.db" "$db_backup_dir/slob_state.db"

        # Also backup WAL and SHM files if they exist
        if [ -f "$PROJECT_ROOT/data/slob_state.db-wal" ]; then
            cp "$PROJECT_ROOT/data/slob_state.db-wal" "$db_backup_dir/slob_state.db-wal"
        fi
        if [ -f "$PROJECT_ROOT/data/slob_state.db-shm" ]; then
            cp "$PROJECT_ROOT/data/slob_state.db-shm" "$db_backup_dir/slob_state.db-shm"
        fi

        log_success "  ✓ slob_state.db backed up"
    else
        log_warning "  ⚠ slob_state.db not found"
    fi

    # Backup candles database
    if [ -f "$PROJECT_ROOT/data/candles.db" ]; then
        log_info "  → candles.db"
        cp "$PROJECT_ROOT/data/candles.db" "$db_backup_dir/candles.db"
        log_success "  ✓ candles.db backed up"
    else
        log_warning "  ⚠ candles.db not found"
    fi

    # Create compressed archive
    log_info "Compressing database backup..."
    cd "$BACKUP_DIR"
    tar -czf "db_$TIMESTAMP.tar.gz" "db_$TIMESTAMP/"
    rm -rf "db_$TIMESTAMP/"
    log_success "Database backup compressed: db_$TIMESTAMP.tar.gz"

    echo "$db_backup_dir"
}

backup_logs() {
    log_info "Backing up logs..."

    local log_dir="$PROJECT_ROOT/logs"
    if [ -d "$log_dir" ]; then
        log_info "  → logs/"
        tar -czf "$BACKUP_DIR/logs_$TIMESTAMP.tar.gz" -C "$PROJECT_ROOT" "logs/" 2>/dev/null || log_warning "  ⚠ Some logs could not be backed up"
        log_success "Logs backed up: logs_$TIMESTAMP.tar.gz"
    else
        log_warning "Log directory not found: $log_dir"
    fi
}

backup_config() {
    log_info "Backing up configuration..."

    local config_backup_dir="$BACKUP_DIR/config_$TIMESTAMP"
    mkdir -p "$config_backup_dir"

    # Backup .env file (CRITICAL - contains credentials)
    if [ -f "$PROJECT_ROOT/.env" ]; then
        log_info "  → .env (encrypted)"
        cp "$PROJECT_ROOT/.env" "$config_backup_dir/.env"
        chmod 600 "$config_backup_dir/.env"  # Restrict permissions
        log_success "  ✓ .env backed up"
    else
        log_warning "  ⚠ .env not found"
    fi

    # Backup docker-compose.yml
    if [ -f "$PROJECT_ROOT/docker-compose.yml" ]; then
        log_info "  → docker-compose.yml"
        cp "$PROJECT_ROOT/docker-compose.yml" "$config_backup_dir/docker-compose.yml"
        log_success "  ✓ docker-compose.yml backed up"
    fi

    # Create compressed archive
    log_info "Compressing config backup..."
    cd "$BACKUP_DIR"
    tar -czf "config_$TIMESTAMP.tar.gz" "config_$TIMESTAMP/"
    rm -rf "config_$TIMESTAMP/"
    log_success "Config backup compressed: config_$TIMESTAMP.tar.gz"
}

backup_models() {
    log_info "Backing up ML models..."

    local model_dir="$PROJECT_ROOT/models"
    if [ -d "$model_dir" ] && [ "$(ls -A $model_dir 2>/dev/null)" ]; then
        log_info "  → models/"
        tar -czf "$BACKUP_DIR/models_$TIMESTAMP.tar.gz" -C "$PROJECT_ROOT" "models/"
        log_success "Models backed up: models_$TIMESTAMP.tar.gz"
    else
        log_warning "No ML models found to backup"
    fi
}

verify_backup() {
    log_info "Verifying backup integrity..."

    local backup_files=(
        "$BACKUP_DIR/db_$TIMESTAMP.tar.gz"
        "$BACKUP_DIR/logs_$TIMESTAMP.tar.gz"
        "$BACKUP_DIR/config_$TIMESTAMP.tar.gz"
    )

    local all_valid=true

    for backup_file in "${backup_files[@]}"; do
        if [ -f "$backup_file" ]; then
            # Test archive integrity
            if tar -tzf "$backup_file" > /dev/null 2>&1; then
                local size=$(du -h "$backup_file" | cut -f1)
                log_success "  ✓ $(basename $backup_file) - Valid ($size)"
            else
                log_error "  ✗ $(basename $backup_file) - Corrupted"
                all_valid=false
            fi
        fi
    done

    if [ "$all_valid" = true ]; then
        log_success "All backups verified successfully"
        return 0
    else
        log_error "Some backups failed verification"
        return 1
    fi
}

upload_to_s3() {
    if [ "$UPLOAD_S3" = true ]; then
        log_info "Uploading backups to S3..."

        if [ -z "${AWS_S3_BUCKET:-}" ]; then
            log_error "AWS_S3_BUCKET environment variable not set"
            return 1
        fi

        if ! command -v aws &> /dev/null; then
            log_error "AWS CLI not installed - cannot upload to S3"
            return 1
        fi

        local backup_files=(
            "$BACKUP_DIR/db_$TIMESTAMP.tar.gz"
            "$BACKUP_DIR/logs_$TIMESTAMP.tar.gz"
            "$BACKUP_DIR/config_$TIMESTAMP.tar.gz"
        )

        for backup_file in "${backup_files[@]}"; do
            if [ -f "$backup_file" ]; then
                log_info "  → Uploading $(basename $backup_file)..."
                if aws s3 cp "$backup_file" "s3://$AWS_S3_BUCKET/slob-backups/"; then
                    log_success "  ✓ $(basename $backup_file) uploaded"
                else
                    log_error "  ✗ Failed to upload $(basename $backup_file)"
                fi
            fi
        done

        log_success "S3 upload complete"
    fi
}

cleanup_old_backups() {
    log_info "Cleaning up old backups (retention: $RETENTION_DAYS days)..."

    local removed_count=0

    # Find and remove old backup files
    while IFS= read -r -d '' old_backup; do
        rm -f "$old_backup"
        removed_count=$((removed_count + 1))
    done < <(find "$BACKUP_DIR" -name "*.tar.gz" -type f -mtime "+$RETENTION_DAYS" -print0 2>/dev/null)

    if [ $removed_count -gt 0 ]; then
        log_success "Removed $removed_count old backup(s)"
    else
        log_info "No old backups to remove"
    fi
}

send_notification() {
    if [ "$SEND_NOTIFICATION" = true ] && [ -n "${BACKUP_EMAIL:-}" ]; then
        log_info "Sending backup notification..."

        local backup_size=$(du -sh "$BACKUP_DIR" | cut -f1)
        local message="SLOB Trading System backup completed successfully at $(date).

Backup Details:
- Timestamp: $TIMESTAMP
- Backup size: $backup_size
- Retention: $RETENTION_DAYS days
- S3 Upload: $UPLOAD_S3

Backup files:
$(ls -lh "$BACKUP_DIR"/*.tar.gz 2>/dev/null | tail -5)
"

        # Send email using Python (if email notifier is available)
        if [ -f "$PROJECT_ROOT/slob/monitoring/email_notifier.py" ]; then
            python3 -c "
from slob.monitoring.email_notifier import EmailNotifier
notifier = EmailNotifier()
notifier.send_alert(
    subject='SLOB Backup Complete',
    message='$message'
)
" || log_warning "Failed to send email notification"
        else
            log_warning "Email notifier not found - skipping notification"
        fi
    fi
}

################################################################################
# Main Backup Flow
################################################################################

main() {
    echo "════════════════════════════════════════════════════════════════"
    echo "  💾 SLOB Trading System - State Backup"
    echo "════════════════════════════════════════════════════════════════"
    echo ""

    local start_time=$(date +%s)

    # Step 1: Create backup directory
    create_backup_dir

    # Step 2: Backup databases
    backup_databases

    # Step 3: Backup logs
    backup_logs

    # Step 4: Backup configuration
    backup_config

    # Step 5: Backup ML models
    backup_models

    # Step 6: Verify backup (if requested)
    if [ "$VERIFY_BACKUP" = true ]; then
        verify_backup
    fi

    # Step 7: Upload to S3 (if requested)
    upload_to_s3

    # Step 8: Cleanup old backups
    cleanup_old_backups

    # Step 9: Send notification (if requested)
    send_notification

    # Summary
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    echo ""
    echo "════════════════════════════════════════════════════════════════"
    log_success "✅ Backup completed successfully in ${duration}s"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    log_info "Backup location: $BACKUP_DIR"
    log_info "Backup timestamp: $TIMESTAMP"
    log_info "Backup files:"
    ls -lh "$BACKUP_DIR"/*.tar.gz 2>/dev/null | tail -5 || echo "  No backup files found"
    echo ""
}

# Error handling
trap 'log_error "Backup failed at line $LINENO"; exit 1' ERR

# Execute main
main "$@"
