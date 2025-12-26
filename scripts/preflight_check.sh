#!/bin/bash
################################################################################
# SLOB Trading System - Pre-flight Check Script
#
# Validates system readiness before deployment:
# - Docker and docker-compose installed
# - Required environment variables set
# - Database files accessible
# - Configuration files valid
# - Network connectivity (IB Gateway, APIs)
# - File permissions correct
# - Disk space available
# - Dependencies installed
#
# Usage:
#   ./scripts/preflight_check.sh [--strict]
#
# Options:
#   --strict    Fail on warnings (not just errors)
#
# Exit Codes:
#   0 - All checks passed
#   1 - Critical errors found
#   2 - Warnings found (only with --strict)
#
################################################################################

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
STRICT_MODE=false
ERROR_COUNT=0
WARNING_COUNT=0

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --strict)
            STRICT_MODE=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

################################################################################
# Check Functions
################################################################################

check_pass() {
    echo -e "  ${GREEN}✓${NC} $1"
}

check_fail() {
    echo -e "  ${RED}✗${NC} $1"
    ERROR_COUNT=$((ERROR_COUNT + 1))
}

check_warn() {
    echo -e "  ${YELLOW}⚠${NC} $1"
    WARNING_COUNT=$((WARNING_COUNT + 1))
}

check_info() {
    echo -e "  ${BLUE}•${NC} $1"
}

section_header() {
    echo ""
    echo -e "${BLUE}${BOLD}━━━ $1 ━━━${NC}"
}

################################################################################
# Pre-flight Checks
################################################################################

check_docker() {
    section_header "Docker Environment"

    # Check Docker installed
    if command -v docker &> /dev/null; then
        local docker_version=$(docker --version | cut -d' ' -f3 | tr -d ',')
        check_pass "Docker installed: $docker_version"
    else
        check_fail "Docker not installed"
        return 1
    fi

    # Check Docker daemon running
    if docker info &> /dev/null; then
        check_pass "Docker daemon is running"
    else
        check_fail "Docker daemon not running"
        return 1
    fi

    # Check docker-compose installed
    if command -v docker-compose &> /dev/null; then
        local compose_version=$(docker-compose --version | cut -d' ' -f3 | tr -d ',')
        check_pass "docker-compose installed: $compose_version"
    else
        check_fail "docker-compose not installed"
        return 1
    fi

    # Check Docker disk space
    local docker_disk=$(docker system df --format "{{.Size}}" 2>/dev/null | head -1)
    if [ -n "$docker_disk" ]; then
        check_info "Docker disk usage: $docker_disk"
    fi
}

check_environment_variables() {
    section_header "Environment Variables"

    cd "$PROJECT_ROOT"

    # Check .env file exists
    if [ -f ".env" ]; then
        check_pass ".env file exists"

        # Check critical variables (without exposing values)
        local required_vars=(
            "IB_ACCOUNT"
            "IB_HOST"
            "IB_PORT"
        )

        for var in "${required_vars[@]}"; do
            if grep -q "^$var=" .env 2>/dev/null; then
                check_pass "$var is set"
            else
                check_warn "$var not set in .env"
            fi
        done

        # Check optional variables
        local optional_vars=(
            "TELEGRAM_BOT_TOKEN"
            "SMTP_SERVER"
            "ML_SHADOW_MODE_ENABLED"
        )

        for var in "${optional_vars[@]}"; do
            if grep -q "^$var=" .env 2>/dev/null; then
                check_info "$var is configured"
            fi
        done

        # Check .env permissions (should be 600 or 400)
        local env_perms=$(stat -f "%A" .env 2>/dev/null || stat -c "%a" .env 2>/dev/null)
        if [ "$env_perms" = "600" ] || [ "$env_perms" = "400" ]; then
            check_pass ".env permissions: $env_perms (secure)"
        else
            check_warn ".env permissions: $env_perms (should be 600 or 400)"
        fi
    else
        check_fail ".env file not found"
    fi
}

check_database() {
    section_header "Database Files"

    cd "$PROJECT_ROOT"

    # Check data directory exists
    if [ -d "data" ]; then
        check_pass "data/ directory exists"

        # Check main database
        if [ -f "data/slob_state.db" ]; then
            local db_size=$(du -h data/slob_state.db | cut -f1)
            check_pass "slob_state.db exists ($db_size)"

            # Check database is not corrupted
            if command -v sqlite3 &> /dev/null; then
                if sqlite3 data/slob_state.db "PRAGMA integrity_check;" 2>/dev/null | grep -q "ok"; then
                    check_pass "slob_state.db integrity check passed"
                else
                    check_fail "slob_state.db integrity check failed"
                fi
            fi
        else
            check_warn "slob_state.db not found (will be created on first run)"
        fi

        # Check candles database
        if [ -f "data/candles.db" ]; then
            local candles_size=$(du -h data/candles.db | cut -f1)
            check_pass "candles.db exists ($candles_size)"
        else
            check_warn "candles.db not found (will be created on first run)"
        fi

        # Check backup directory
        if [ -d "data/backups" ]; then
            local backup_count=$(find data/backups -name "*.tar.gz" | wc -l)
            check_info "Backups directory exists ($backup_count backups)"
        else
            check_warn "data/backups/ not found (will be created)"
        fi
    else
        check_fail "data/ directory not found"
    fi
}

check_configuration_files() {
    section_header "Configuration Files"

    cd "$PROJECT_ROOT"

    # Check docker-compose.yml
    if [ -f "docker-compose.yml" ]; then
        check_pass "docker-compose.yml exists"

        # Validate YAML syntax
        if command -v docker-compose &> /dev/null; then
            if docker-compose config &> /dev/null; then
                check_pass "docker-compose.yml is valid"
            else
                check_fail "docker-compose.yml has syntax errors"
            fi
        fi
    else
        check_fail "docker-compose.yml not found"
    fi

    # Check Dockerfile
    if [ -f "Dockerfile" ]; then
        check_pass "Dockerfile exists"
    else
        check_warn "Dockerfile not found"
    fi

    # Check requirements.txt
    if [ -f "requirements.txt" ]; then
        check_pass "requirements.txt exists"
    else
        check_fail "requirements.txt not found"
    fi
}

check_network_connectivity() {
    section_header "Network Connectivity"

    # Check IB Gateway connectivity
    if command -v nc &> /dev/null; then
        if nc -z localhost 4002 2>/dev/null; then
            check_pass "IB Gateway reachable on localhost:4002"
        elif nc -z localhost 7497 2>/dev/null; then
            check_pass "TWS reachable on localhost:7497"
        else
            check_warn "IB Gateway/TWS not reachable (start before deployment)"
        fi
    else
        check_warn "nc (netcat) not installed - cannot check IB connectivity"
    fi

    # Check internet connectivity
    if command -v curl &> /dev/null; then
        if curl -s --max-time 5 https://www.google.com > /dev/null 2>&1; then
            check_pass "Internet connectivity available"
        else
            check_warn "Internet connectivity issues detected"
        fi
    fi

    # Check Redis connectivity (if used)
    if command -v redis-cli &> /dev/null; then
        if redis-cli ping &>/dev/null; then
            check_pass "Redis is running"
        else
            check_warn "Redis not running (will use SQLite only)"
        fi
    fi
}

check_file_permissions() {
    section_header "File Permissions"

    cd "$PROJECT_ROOT"

    # Check scripts are executable
    local scripts=(
        "scripts/deploy.sh"
        "scripts/monitor.sh"
        "scripts/backup_state.sh"
        "scripts/health_check.sh"
    )

    for script in "${scripts[@]}"; do
        if [ -f "$script" ]; then
            if [ -x "$script" ]; then
                check_pass "$script is executable"
            else
                check_warn "$script is not executable (run: chmod +x $script)"
            fi
        fi
    done

    # Check data directory permissions
    if [ -d "data" ]; then
        local data_perms=$(stat -f "%A" data 2>/dev/null || stat -c "%a" data 2>/dev/null)
        if [ "$data_perms" = "700" ] || [ "$data_perms" = "755" ]; then
            check_pass "data/ permissions: $data_perms"
        else
            check_warn "data/ permissions: $data_perms (should be 700 or 755)"
        fi
    fi
}

check_disk_space() {
    section_header "Disk Space"

    # Check available disk space
    local available_space=$(df -h . | awk 'NR==2 {print $4}')
    local available_space_mb=$(df -m . | awk 'NR==2 {print $4}')

    check_info "Available disk space: $available_space"

    # Warn if less than 1GB available
    if [ "$available_space_mb" -lt 1024 ]; then
        check_warn "Low disk space: $available_space (recommend >1GB)"
    else
        check_pass "Sufficient disk space available"
    fi

    # Check Docker disk usage
    if command -v docker &> /dev/null && docker info &> /dev/null; then
        local docker_images=$(docker images -q | wc -l)
        local docker_containers=$(docker ps -a -q | wc -l)
        check_info "Docker images: $docker_images, Containers: $docker_containers"
    fi
}

check_python_dependencies() {
    section_header "Python Dependencies"

    # Check Python version
    if command -v python3 &> /dev/null; then
        local python_version=$(python3 --version | cut -d' ' -f2)
        check_pass "Python 3 installed: $python_version"

        # Check if in virtual environment (optional)
        if [ -n "${VIRTUAL_ENV:-}" ]; then
            check_info "Virtual environment active: $VIRTUAL_ENV"
        fi

        # Check critical Python packages
        local packages=("pandas" "numpy" "ib_insync" "redis" "flask")
        local missing_packages=()

        for package in "${packages[@]}"; do
            if python3 -c "import $package" 2>/dev/null; then
                check_pass "Python package '$package' installed"
            else
                missing_packages+=("$package")
                check_warn "Python package '$package' not installed"
            fi
        done

        if [ ${#missing_packages[@]} -gt 0 ]; then
            check_info "Install missing packages: pip install ${missing_packages[*]}"
        fi
    else
        check_fail "Python 3 not installed"
    fi
}

check_ml_models() {
    section_header "ML Models"

    cd "$PROJECT_ROOT"

    # Check if models directory exists
    if [ -d "models" ]; then
        check_pass "models/ directory exists"

        # Check for trained model
        if [ -f "models/setup_classifier_latest.joblib" ]; then
            local model_size=$(du -h models/setup_classifier_latest.joblib | cut -f1)
            check_pass "ML model found: setup_classifier_latest.joblib ($model_size)"
        else
            check_warn "ML model not trained (run: python scripts/train_model_stationary.py)"
        fi
    else
        check_warn "models/ directory not found (ML features disabled)"
    fi
}

check_git_status() {
    section_header "Git Status"

    cd "$PROJECT_ROOT"

    if command -v git &> /dev/null && [ -d ".git" ]; then
        # Check current branch
        local current_branch=$(git branch --show-current)
        check_info "Current branch: $current_branch"

        # Check for uncommitted changes
        if git diff-index --quiet HEAD -- 2>/dev/null; then
            check_pass "No uncommitted changes"
        else
            check_warn "Uncommitted changes detected"
            git status --short | head -5 | while read line; do
                check_info "  $line"
            done
        fi

        # Check if up to date with remote
        git fetch origin &>/dev/null
        local behind=$(git rev-list HEAD..origin/$current_branch --count 2>/dev/null || echo "0")
        if [ "$behind" -eq 0 ]; then
            check_pass "Up to date with remote"
        else
            check_warn "$behind commits behind remote (run: git pull)"
        fi
    else
        check_warn "Not a git repository"
    fi
}

################################################################################
# Main Execution
################################################################################

main() {
    echo ""
    echo "═══════════════════════════════════════════════════════════════════════════"
    echo "  🔍 SLOB Trading System - Pre-flight Checks"
    echo "═══════════════════════════════════════════════════════════════════════════"

    # Run all checks
    check_docker
    check_environment_variables
    check_database
    check_configuration_files
    check_network_connectivity
    check_file_permissions
    check_disk_space
    check_python_dependencies
    check_ml_models
    check_git_status

    # Summary
    echo ""
    echo "═══════════════════════════════════════════════════════════════════════════"
    echo "  Summary"
    echo "═══════════════════════════════════════════════════════════════════════════"

    if [ $ERROR_COUNT -eq 0 ] && [ $WARNING_COUNT -eq 0 ]; then
        echo -e "${GREEN}${BOLD}✅ All pre-flight checks passed!${NC}"
        echo ""
        exit 0
    elif [ $ERROR_COUNT -eq 0 ]; then
        echo -e "${YELLOW}${BOLD}⚠ $WARNING_COUNT warning(s) found${NC}"
        echo ""
        if [ "$STRICT_MODE" = true ]; then
            echo "Strict mode enabled - treating warnings as errors"
            exit 2
        else
            echo "Deployment can proceed (warnings are non-critical)"
            exit 0
        fi
    else
        echo -e "${RED}${BOLD}✗ $ERROR_COUNT error(s) found${NC}"
        if [ $WARNING_COUNT -gt 0 ]; then
            echo -e "${YELLOW}⚠ $WARNING_COUNT warning(s) found${NC}"
        fi
        echo ""
        echo "Fix errors before deploying"
        exit 1
    fi
}

main "$@"
