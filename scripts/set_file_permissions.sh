#!/bin/bash
# ==============================================================================
# Set Secure File Permissions for SLOB Trading System
# ==============================================================================
# This script sets restrictive file permissions on sensitive files and directories
#
# Usage:
#   ./scripts/set_file_permissions.sh
#
# What it does:
#   1. Sets 700 (rwx------) on sensitive directories
#   2. Sets 600 (rw-------) on sensitive files (databases, secrets, logs)
#   3. Sets 755 (rwxr-xr-x) on script files
#   4. Validates permissions after setting
# ==============================================================================

set -e  # Exit on error

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "===================================================================="
echo "  SLOB Trading System - File Permissions Setup"
echo "===================================================================="
echo ""

# Check if running as root (not recommended)
if [ "$EUID" -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Warning: Running as root${NC}"
    echo "Consider running as a dedicated user instead"
    echo ""
fi

# ============================================================================
# DIRECTORIES
# ============================================================================

echo "Setting directory permissions..."
echo ""

# Data directories (700 - owner only)
if [ -d "data" ]; then
    chmod 700 data/
    echo -e "${GREEN}✅ data/ → 700 (rwx------)${NC}"
fi

if [ -d "data/backups" ]; then
    chmod 700 data/backups/
    echo -e "${GREEN}✅ data/backups/ → 700 (rwx------)${NC}"
fi

# Secrets directory (700 - owner only)
if [ -d "secrets" ]; then
    chmod 700 secrets/
    echo -e "${GREEN}✅ secrets/ → 700 (rwx------)${NC}"
fi

# Logs directory (700 - owner only, contains sensitive trading data)
if [ -d "logs" ]; then
    chmod 700 logs/
    echo -e "${GREEN}✅ logs/ → 700 (rwx------)${NC}"
fi

# Scripts directory (755 - executable by all, writable by owner)
if [ -d "scripts" ]; then
    chmod 755 scripts/
    echo -e "${GREEN}✅ scripts/ → 755 (rwxr-xr-x)${NC}"
fi

echo ""

# ============================================================================
# DATABASE FILES
# ============================================================================

echo "Setting database file permissions..."
echo ""

# SQLite databases (600 - owner read/write only)
for db_file in data/*.db data/*.sqlite data/*.sqlite3; do
    if [ -f "$db_file" ]; then
        chmod 600 "$db_file"
        echo -e "${GREEN}✅ $(basename $db_file) → 600 (rw-------)${NC}"
    fi
done

# SQLite WAL and SHM files (600)
for wal_file in data/*.db-wal data/*.db-shm data/*.db-journal; do
    if [ -f "$wal_file" ]; then
        chmod 600 "$wal_file"
        echo -e "${GREEN}✅ $(basename $wal_file) → 600 (rw-------)${NC}"
    fi
done

echo ""

# ============================================================================
# SECRET FILES
# ============================================================================

echo "Setting secret file permissions..."
echo ""

# .env file (600 - contains credentials)
if [ -f ".env" ]; then
    chmod 600 .env
    echo -e "${GREEN}✅ .env → 600 (rw-------)${NC}"
fi

# Secrets directory files (600)
if [ -d "secrets" ]; then
    for secret_file in secrets/*.txt; do
        if [ -f "$secret_file" ]; then
            chmod 600 "$secret_file"
            echo -e "${GREEN}✅ $(basename $secret_file) → 600 (rw-------)${NC}"
        fi
    done
fi

# SSH keys, certificates (600)
for key_file in *.key *.pem *.p12 *.pfx; do
    if [ -f "$key_file" ]; then
        chmod 600 "$key_file"
        echo -e "${GREEN}✅ $(basename $key_file) → 600 (rw-------)${NC}"
    fi
done

echo ""

# ============================================================================
# LOG FILES
# ============================================================================

echo "Setting log file permissions..."
echo ""

# Log files (600 - contain trading data)
for log_file in logs/*.log; do
    if [ -f "$log_file" ]; then
        chmod 600 "$log_file"
        echo -e "${GREEN}✅ $(basename $log_file) → 600 (rw-------)${NC}"
    fi
done

echo ""

# ============================================================================
# SCRIPT FILES
# ============================================================================

echo "Setting script file permissions..."
echo ""

# Make shell scripts executable (755)
for script_file in scripts/*.sh; do
    if [ -f "$script_file" ]; then
        chmod 755 "$script_file"
        echo -e "${GREEN}✅ $(basename $script_file) → 755 (rwxr-xr-x)${NC}"
    fi
done

# Make Python scripts executable (755)
for py_file in scripts/*.py; do
    if [ -f "$py_file" ]; then
        chmod 755 "$py_file"
        echo -e "${GREEN}✅ $(basename $py_file) → 755 (rwxr-xr-x)${NC}"
    fi
done

echo ""

# ============================================================================
# VALIDATION
# ============================================================================

echo "===================================================================="
echo "  Validation"
echo "===================================================================="
echo ""

# Function to check permissions
check_permissions() {
    local file=$1
    local expected=$2
    local description=$3

    if [ -e "$file" ]; then
        actual=$(stat -f "%OLp" "$file" 2>/dev/null || stat -c "%a" "$file" 2>/dev/null)
        if [ "$actual" = "$expected" ]; then
            echo -e "${GREEN}✅ $description: $file ($actual)${NC}"
        else
            echo -e "${RED}❌ $description: $file (expected $expected, got $actual)${NC}"
        fi
    fi
}

# Validate critical files/directories
check_permissions "data" "700" "Data directory"
check_permissions "secrets" "700" "Secrets directory"
check_permissions "logs" "700" "Logs directory"
check_permissions ".env" "600" "Environment file"

# Check if any files are world-readable (security issue)
echo ""
echo "Checking for world-readable sensitive files..."
WORLD_READABLE=$(find data/ secrets/ logs/ .env -type f -perm -004 2>/dev/null || true)

if [ -n "$WORLD_READABLE" ]; then
    echo -e "${RED}❌ WARNING: World-readable files found:${NC}"
    echo "$WORLD_READABLE"
else
    echo -e "${GREEN}✅ No world-readable sensitive files found${NC}"
fi

echo ""
echo "===================================================================="
echo "  Summary"
echo "===================================================================="
echo ""

# Count files by permission level
COUNT_700=$(find . -maxdepth 2 -type d -perm 700 2>/dev/null | wc -l)
COUNT_600=$(find data/ secrets/ logs/ -type f -perm 600 2>/dev/null | wc -l || echo 0)
COUNT_755=$(find scripts/ -type f -perm 755 2>/dev/null | wc -l || echo 0)

echo "Directories with 700 permissions: $COUNT_700"
echo "Files with 600 permissions: $COUNT_600"
echo "Scripts with 755 permissions: $COUNT_755"

echo ""
echo -e "${GREEN}✅ File permissions set successfully!${NC}"
echo ""
echo "Next steps:"
echo "  1. Verify permissions: ls -la data/ secrets/ logs/"
echo "  2. Test application startup"
echo "  3. Check logs for permission errors"
echo ""
echo -e "${YELLOW}⚠️  IMPORTANT SECURITY NOTES:${NC}"
echo "  - Run this script after every git pull or file restore"
echo "  - Never commit files with 777 or world-writable permissions"
echo "  - Keep database backups encrypted and access-controlled"
echo "  - Run 'find . -perm -002' periodically to check for world-writable files"
echo ""
echo "===================================================================="
