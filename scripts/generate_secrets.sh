#!/bin/bash
# ==============================================================================
# Generate Docker Secrets Files
# ==============================================================================
# This script creates secure secret files for Docker secrets management
#
# Usage:
#   ./scripts/generate_secrets.sh
#
# What it does:
#   1. Creates secrets/ directory with restricted permissions (700)
#   2. Prompts for all credentials
#   3. Generates random values for certain secrets
#   4. Saves each secret to a separate file
#   5. Sets strict file permissions (600) on all secret files
# ==============================================================================

set -e  # Exit on error

SECRETS_DIR="./secrets"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "===================================================================="
echo "  SLOB Trading System - Docker Secrets Generator"
echo "===================================================================="
echo ""

# Check if secrets directory exists
if [ -d "$SECRETS_DIR" ]; then
    echo -e "${YELLOW}⚠️  Warning: secrets/ directory already exists${NC}"
    read -p "Do you want to overwrite existing secrets? (yes/no): " OVERWRITE
    if [ "$OVERWRITE" != "yes" ]; then
        echo "Aborted."
        exit 1
    fi
    echo "Backing up existing secrets..."
    tar -czf "secrets_backup_$(date +%Y%m%d_%H%M%S).tar.gz" "$SECRETS_DIR"
    rm -rf "$SECRETS_DIR"
fi

# Create secrets directory with restricted permissions
echo "Creating secrets directory..."
mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

echo ""
echo "===================================================================="
echo "  Step 1: Interactive Brokers Credentials"
echo "===================================================================="
echo ""

read -p "IB Username: " IB_USERNAME
read -sp "IB Password: " IB_PASSWORD
echo ""
read -p "IB Account ID: " IB_ACCOUNT
read -sp "VNC Password (for debugging, default: vncpass): " VNC_PASSWORD
echo ""
VNC_PASSWORD=${VNC_PASSWORD:-vncpass}

# Save IB secrets
echo -n "$IB_USERNAME" > "$SECRETS_DIR/ib_username.txt"
echo -n "$IB_PASSWORD" > "$SECRETS_DIR/ib_password.txt"
echo -n "$IB_ACCOUNT" > "$SECRETS_DIR/ib_account.txt"
echo -n "$VNC_PASSWORD" > "$SECRETS_DIR/vnc_password.txt"

echo ""
echo "===================================================================="
echo "  Step 2: Alpaca API Credentials"
echo "===================================================================="
echo ""
echo "Get your keys from: https://app.alpaca.markets/paper/dashboard/overview"
echo ""

read -p "Alpaca API Key: " ALPACA_KEY
read -sp "Alpaca API Secret: " ALPACA_SECRET
echo ""

# Save Alpaca secrets
echo -n "$ALPACA_KEY" > "$SECRETS_DIR/alpaca_api_key.txt"
echo -n "$ALPACA_SECRET" > "$SECRETS_DIR/alpaca_api_secret.txt"

echo ""
echo "===================================================================="
echo "  Step 3: Telegram Bot (Optional - press Enter to skip)"
echo "===================================================================="
echo ""

read -p "Telegram Bot Token (optional): " TELEGRAM_TOKEN
read -p "Telegram Chat ID (optional): " TELEGRAM_CHAT

# Save Telegram secrets (even if empty)
echo -n "$TELEGRAM_TOKEN" > "$SECRETS_DIR/telegram_bot_token.txt"
echo -n "$TELEGRAM_CHAT" > "$SECRETS_DIR/telegram_chat_id.txt"

echo ""
echo "===================================================================="
echo "  Step 4: Email SMTP Credentials (Optional - press Enter to skip)"
echo "===================================================================="
echo ""

read -p "SMTP Server (e.g., smtp.gmail.com): " SMTP_SERVER
read -p "SMTP Username/Email: " SMTP_USER
read -sp "SMTP Password (app-specific password): " SMTP_PASS
echo ""

# Save SMTP secrets
echo -n "$SMTP_PASS" > "$SECRETS_DIR/smtp_password.txt"

echo ""
echo "===================================================================="
echo "  Step 5: Generating Random Secrets"
echo "===================================================================="
echo ""

# Generate Redis password
echo "Generating Redis password..."
REDIS_PASSWORD=$(openssl rand -base64 32)
echo -n "$REDIS_PASSWORD" > "$SECRETS_DIR/redis_password.txt"

# Generate Dashboard secret key
echo "Generating Dashboard secret key..."
DASHBOARD_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
echo -n "$DASHBOARD_SECRET" > "$SECRETS_DIR/dashboard_secret_key.txt"

# Generate Dashboard password hash
echo "Generating Dashboard password hash..."
read -sp "Dashboard Password: " DASHBOARD_PASS
echo ""
DASHBOARD_HASH=$(python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('$DASHBOARD_PASS'))")
echo -n "$DASHBOARD_HASH" > "$SECRETS_DIR/dashboard_password_hash.txt"

echo ""
echo "===================================================================="
echo "  Step 6: Setting File Permissions"
echo "===================================================================="
echo ""

# Set restrictive permissions on all secret files
chmod 600 "$SECRETS_DIR"/*.txt

echo -e "${GREEN}✅ All secret files created with 600 permissions${NC}"

echo ""
echo "===================================================================="
echo "  Summary"
echo "===================================================================="
echo ""
echo "Secrets created:"
ls -lh "$SECRETS_DIR"

echo ""
echo -e "${GREEN}✅ Secrets generation complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Verify all secrets are correct:"
echo "     ls -la secrets/"
echo ""
echo "  2. Start services with secrets:"
echo "     docker-compose -f docker-compose.yml -f docker-compose.secrets.yml up -d"
echo ""
echo "  3. Verify services are running:"
echo "     docker-compose ps"
echo ""
echo -e "${YELLOW}⚠️  IMPORTANT SECURITY REMINDERS:${NC}"
echo "  - NEVER commit secrets/ directory to git (already in .gitignore)"
echo "  - Keep backups encrypted in secure location (password manager)"
echo "  - Rotate credentials every 90 days (see docs/CREDENTIAL_ROTATION_GUIDE.md)"
echo "  - Run: chmod 700 secrets/ to ensure directory permissions"
echo ""
echo "===================================================================="
