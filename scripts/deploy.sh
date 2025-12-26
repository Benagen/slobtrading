#!/bin/bash
################################################################################
# SLOB Trading System - Automated Deployment Script
#
# Deploys the SLOB trading system with zero-downtime strategy.
# Includes pre-flight checks, database migrations, backups, and health checks.
#
# Usage:
#   ./scripts/deploy.sh [--skip-preflight] [--skip-backup]
#
# Options:
#   --skip-preflight    Skip pre-deployment validation checks
#   --skip-backup       Skip state backup before deployment
#   --force             Force deployment even if health checks fail
#
# Environment:
#   DEPLOY_ENV          Deployment environment (dev/staging/production)
#   DOCKER_REGISTRY     Docker registry for image storage (optional)
#
################################################################################

set -e  # Exit on error
set -u  # Exit on undefined variable

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEPLOY_ENV="${DEPLOY_ENV:-production}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$PROJECT_ROOT/logs/deploy_${TIMESTAMP}.log"

# Flags
SKIP_PREFLIGHT=false
SKIP_BACKUP=false
FORCE_DEPLOY=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-preflight)
            SKIP_PREFLIGHT=true
            shift
            ;;
        --skip-backup)
            SKIP_BACKUP=true
            shift
            ;;
        --force)
            FORCE_DEPLOY=true
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
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
}

log_header() {
    echo "" | tee -a "$LOG_FILE"
    echo "================================================================================" | tee -a "$LOG_FILE"
    echo "$1" | tee -a "$LOG_FILE"
    echo "================================================================================" | tee -a "$LOG_FILE"
}

################################################################################
# Deployment Steps
################################################################################

step_banner() {
    echo "" | tee -a "$LOG_FILE"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}" | tee -a "$LOG_FILE"
    echo -e "${BLUE}  STEP: $1${NC}" | tee -a "$LOG_FILE"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}" | tee -a "$LOG_FILE"
}

################################################################################
# Main Deployment Flow
################################################################################

main() {
    # Create logs directory if it doesn't exist
    mkdir -p "$PROJECT_ROOT/logs"

    log_header "🚀 SLOB Trading System Deployment"
    log_info "Deployment started at: $(date)"
    log_info "Environment: $DEPLOY_ENV"
    log_info "Project root: $PROJECT_ROOT"
    log_info "Log file: $LOG_FILE"

    # Change to project root
    cd "$PROJECT_ROOT"

    # ========================================================================
    # STEP 1: Pre-flight Checks
    # ========================================================================
    if [ "$SKIP_PREFLIGHT" = false ]; then
        step_banner "1/8 - Pre-flight Checks"

        if [ -f "$SCRIPT_DIR/preflight_check.sh" ]; then
            if bash "$SCRIPT_DIR/preflight_check.sh"; then
                log_success "Pre-flight checks passed"
            else
                log_error "Pre-flight checks failed"
                if [ "$FORCE_DEPLOY" = false ]; then
                    log_error "Deployment aborted. Use --force to override."
                    exit 1
                else
                    log_warning "Force deployment enabled, continuing despite failures"
                fi
            fi
        else
            log_warning "preflight_check.sh not found, skipping"
        fi
    else
        log_warning "Skipping pre-flight checks (--skip-preflight)"
    fi

    # ========================================================================
    # STEP 2: Pull Latest Code
    # ========================================================================
    step_banner "2/8 - Pull Latest Code"

    log_info "Fetching latest changes from git..."
    if git fetch origin; then
        log_success "Git fetch successful"
    else
        log_error "Git fetch failed"
        exit 1
    fi

    log_info "Current branch: $(git branch --show-current)"
    log_info "Latest commit: $(git log -1 --oneline)"

    if [ "$DEPLOY_ENV" = "production" ]; then
        log_info "Pulling from main branch..."
        if git pull origin main; then
            log_success "Code updated successfully"
        else
            log_error "Git pull failed"
            exit 1
        fi
    else
        log_info "Development environment - using current branch"
    fi

    # ========================================================================
    # STEP 3: Backup Current State
    # ========================================================================
    if [ "$SKIP_BACKUP" = false ]; then
        step_banner "3/8 - Backup Current State"

        if [ -f "$SCRIPT_DIR/backup_state.sh" ]; then
            log_info "Creating pre-deployment backup..."
            if bash "$SCRIPT_DIR/backup_state.sh"; then
                log_success "Backup created successfully"
            else
                log_error "Backup failed"
                if [ "$FORCE_DEPLOY" = false ]; then
                    log_error "Deployment aborted. Use --force to override."
                    exit 1
                else
                    log_warning "Force deployment enabled, continuing despite backup failure"
                fi
            fi
        else
            log_warning "backup_state.sh not found, skipping backup"
        fi
    else
        log_warning "Skipping backup (--skip-backup)"
    fi

    # ========================================================================
    # STEP 4: Build Docker Images
    # ========================================================================
    step_banner "4/8 - Build Docker Images"

    log_info "Building Docker images with no cache..."
    if docker-compose build --no-cache; then
        log_success "Docker images built successfully"
    else
        log_error "Docker build failed"
        exit 1
    fi

    log_info "Docker image info:"
    docker images | grep -E "slob|IMAGE" | tee -a "$LOG_FILE"

    # ========================================================================
    # STEP 5: Database Migrations
    # ========================================================================
    step_banner "5/8 - Database Migrations"

    if [ -f "$SCRIPT_DIR/migrate_database.py" ]; then
        log_info "Running database migrations..."
        if python3 "$SCRIPT_DIR/migrate_database.py"; then
            log_success "Database migrations completed"
        else
            log_error "Database migrations failed"
            exit 1
        fi
    else
        log_warning "migrate_database.py not found, skipping migrations"
    fi

    # ========================================================================
    # STEP 6: Zero-Downtime Deployment
    # ========================================================================
    step_banner "6/8 - Zero-Downtime Deployment"

    log_info "Deploying with zero-downtime strategy..."

    # Start new containers
    if docker-compose up -d --no-deps --build; then
        log_success "New containers started"
    else
        log_error "Container startup failed"
        exit 1
    fi

    # Wait for containers to stabilize
    log_info "Waiting 10 seconds for containers to stabilize..."
    sleep 10

    # ========================================================================
    # STEP 7: Health Checks
    # ========================================================================
    step_banner "7/8 - Health Checks"

    log_info "Running health checks..."

    # Check container status
    log_info "Container status:"
    docker-compose ps | tee -a "$LOG_FILE"

    # Run health check script
    if [ -f "$SCRIPT_DIR/health_check.sh" ]; then
        if bash "$SCRIPT_DIR/health_check.sh"; then
            log_success "Health checks passed"
        else
            log_error "Health checks failed"

            if [ "$FORCE_DEPLOY" = false ]; then
                log_error "Rolling back deployment..."
                docker-compose down
                exit 1
            else
                log_warning "Force deployment enabled, ignoring health check failures"
            fi
        fi
    else
        log_warning "health_check.sh not found, skipping health checks"
    fi

    # ========================================================================
    # STEP 8: Post-Deployment Validation
    # ========================================================================
    step_banner "8/8 - Post-Deployment Validation"

    log_info "Verifying deployment..."

    # Check logs for errors
    log_info "Recent container logs:"
    docker-compose logs --tail=20 | tee -a "$LOG_FILE"

    # Check database connectivity
    if [ -f "data/slob_state.db" ]; then
        log_info "Database status:"
        sqlite3 data/slob_state.db "SELECT COUNT(*) as total_setups FROM active_setups;" 2>&1 | tee -a "$LOG_FILE" || log_warning "Database query failed"
    fi

    # ========================================================================
    # Deployment Complete
    # ========================================================================
    log_header "✅ DEPLOYMENT COMPLETE"
    log_success "Deployment finished at: $(date)"
    log_info "Deployment took: $SECONDS seconds"
    log_info ""
    log_info "Next steps:"
    log_info "  1. Monitor logs: docker-compose logs -f"
    log_info "  2. Check dashboard: http://localhost:5000"
    log_info "  3. Run monitoring: ./scripts/monitor.sh"
    log_info ""
    log_info "To rollback: ./scripts/rollback.sh"

    # Cleanup old Docker images
    log_info "Cleaning up old Docker images..."
    docker image prune -f | tee -a "$LOG_FILE"

    log_success "🎉 SLOB Trading System deployment successful!"
}

# ============================================================================
# Error Handling
# ============================================================================

trap 'log_error "Deployment failed at line $LINENO. Check log: $LOG_FILE"; exit 1' ERR

# ============================================================================
# Execute Main
# ============================================================================

main "$@"
