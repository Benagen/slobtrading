# SLOB Trading System - Secrets Setup Guide

**Complete guide for configuring secrets and sensitive credentials.**

*Version*: 1.0
*Last Updated*: 2025-12-26
*Status*: Production Ready

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Setup](#quick-setup)
3. [Secret Types](#secret-types)
4. [Setup Methods](#setup-methods)
5. [Docker Secrets](#docker-secrets)
6. [Environment Variables](#environment-variables)
7. [Security Best Practices](#security-best-practices)
8. [Troubleshooting](#troubleshooting)

---

## Overview

The SLOB trading system uses a **priority-based secrets management** system:

1. **Docker Secrets** (highest priority) - Production deployment
2. **Local files** in `secrets/` directory - Development
3. **Environment variables** in `.env` file - Fallback

**Architecture**: `slob/config/secrets.py` handles all secret loading with automatic fallback.

---

## Quick Setup

### For Development (Local Files)

```bash
# 1. Create secrets directory
mkdir -p secrets

# 2. Create individual secret files
echo "YOUR_IB_ACCOUNT" > secrets/ib_account
echo "YOUR_IB_USERNAME" > secrets/ib_username
echo "YOUR_IB_PASSWORD" > secrets/ib_password

echo "YOUR_TELEGRAM_BOT_TOKEN" > secrets/telegram_bot_token
echo "YOUR_TELEGRAM_CHAT_ID" > secrets/telegram_chat_id

# Generate dashboard password hash
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('YOUR_SECURE_PASSWORD'))" > secrets/dashboard_password_hash

# 3. Set permissions
chmod 600 secrets/*

# 4. Verify
ls -la secrets/
```

### For Production (Docker Secrets)

```bash
# 1. Initialize Docker Swarm (if not already)
docker swarm init

# 2. Create Docker secrets from files
docker secret create ib_account secrets/ib_account
docker secret create ib_username secrets/ib_username
docker secret create ib_password secrets/ib_password
docker secret create telegram_bot_token secrets/telegram_bot_token
docker secret create telegram_chat_id secrets/telegram_chat_id
docker secret create dashboard_password_hash secrets/dashboard_password_hash

# 3. Deploy with Docker Compose
docker stack deploy -c docker-compose.secrets.yml slob
```

---

## Secret Types

### Required Secrets (Interactive Brokers)

| Secret Name | Description | Example | How to Obtain |
|-------------|-------------|---------|---------------|
| `ib_account` | IB account number | `DU1234567` (paper) or `U1234567` (live) | IB account settings |
| `ib_username` | IB Gateway username | `your_username` | IB account settings |
| `ib_password` | IB Gateway password | `your_password` | IB account settings |
| `dashboard_secret_key` | Flask secret key | Random 32-char string | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `dashboard_password_hash` | Dashboard password hash | bcrypt hash | `python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your_password'))"` |

### Optional Secrets (Monitoring)

| Secret Name | Description | Required For |
|-------------|-------------|--------------|
| `telegram_bot_token` | Telegram bot token | Trade alerts |
| `telegram_chat_id` | Telegram chat ID | Trade alerts |
| `smtp_username` | Email SMTP username | Email alerts |
| `smtp_password` | Email SMTP password | Email alerts |
| `dashboard_password_hash` | Dashboard password hash | Web dashboard login |

### AWS Backup Secrets (Optional)

| Secret Name | Description | Required For |
|-------------|-------------|--------------|
| `aws_access_key_id` | AWS access key | S3 backups |
| `aws_secret_access_key` | AWS secret key | S3 backups |

---

## Setup Methods

### Method 1: Local Files (Recommended for Development)

**Pros**: Simple, fast iteration, easy to manage
**Cons**: Not suitable for production, manual file management

**Steps**:

```bash
# Create secrets directory
mkdir -p secrets
chmod 700 secrets

# IB credentials
echo "DU1234567" > secrets/ib_account
echo "your_username" > secrets/ib_username
echo "your_password" > secrets/ib_password

# Telegram (optional)
echo "123456789:ABCdefGHIjklMNOpqrsTUVwxyz" > secrets/telegram_bot_token
echo "987654321" > secrets/telegram_chat_id

# Dashboard password
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('my-secure-password'))" > secrets/dashboard_password_hash

# Set restrictive permissions
chmod 600 secrets/*

# Verify
cat secrets/ib_account  # Should show your account number
```

**Important**: Ensure `secrets/` is in `.gitignore`:
```bash
grep "^secrets/" .gitignore
# Should output: secrets/
```

---

### Method 2: Environment Variables (Fallback)

**Pros**: Quick setup, CI/CD friendly
**Cons**: Less secure, harder to rotate, visible in process list

**Steps**:

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your credentials:
   ```bash
   # IB Configuration
   IB_ACCOUNT=U1234567
   IB_USERNAME=your_username
   IB_PASSWORD=your_password

   # Telegram (optional)
   TELEGRAM_BOT_TOKEN=123456789:ABC...
   TELEGRAM_CHAT_ID=987654321

   # Dashboard
   DASHBOARD_PASSWORD_HASH=pbkdf2:sha256:...
   ```

3. Verify `.env` is in `.gitignore`:
   ```bash
   grep "^\.env$" .gitignore
   ```

**Security Warning**: Environment variables are less secure than file-based secrets. Use for development only.

---

### Method 3: Docker Secrets (Production)

**Pros**: Most secure, encrypted at rest, Docker-managed
**Cons**: Requires Docker Swarm, more complex setup

**Prerequisites**:
- Docker Swarm initialized
- `docker-compose.secrets.yml` configured

**Steps**:

1. Initialize Docker Swarm (if not already done):
   ```bash
   docker swarm init
   ```

2. Create secret files locally (temporary):
   ```bash
   mkdir -p /tmp/slob-secrets
   echo "U1234567" > /tmp/slob-secrets/ib_account
   echo "your_username" > /tmp/slob-secrets/ib_username
   # ... (create all secrets)
   ```

3. Create Docker secrets:
   ```bash
   docker secret create ib_account /tmp/slob-secrets/ib_account
   docker secret create ib_username /tmp/slob-secrets/ib_username
   docker secret create ib_password /tmp/slob-secrets/ib_password
   docker secret create telegram_bot_token /tmp/slob-secrets/telegram_bot_token
   docker secret create telegram_chat_id /tmp/slob-secrets/telegram_chat_id
   docker secret create dashboard_password_hash /tmp/slob-secrets/dashboard_password_hash
   ```

4. Remove temporary files:
   ```bash
   rm -rf /tmp/slob-secrets
   ```

5. Deploy with Docker Compose:
   ```bash
   docker stack deploy -c docker-compose.secrets.yml slob
   ```

6. Verify secrets are loaded:
   ```bash
   docker exec $(docker ps -qf "name=slob_slob-bot") ls -la /run/secrets/
   # Should show all secret files
   ```

---

## Docker Secrets

### Creating Secrets

```bash
# From file
docker secret create ib_account secrets/ib_account

# From stdin
echo "U1234567" | docker secret create ib_account -

# From environment variable
echo "$IB_ACCOUNT" | docker secret create ib_account -
```

### Listing Secrets

```bash
docker secret ls
```

### Inspecting Secrets (metadata only)

```bash
docker secret inspect ib_account
```

### Removing Secrets

```bash
# Remove single secret
docker secret rm ib_account

# Remove all SLOB secrets
docker secret ls --filter "label=project=slob" -q | xargs docker secret rm
```

### Rotating Secrets

```bash
# 1. Create new secret with different name
echo "NEW_PASSWORD" | docker secret create ib_password_v2 -

# 2. Update service to use new secret
# Edit docker-compose.secrets.yml to reference ib_password_v2

# 3. Redeploy
docker stack deploy -c docker-compose.secrets.yml slob

# 4. Remove old secret
docker secret rm ib_password
```

---

## Environment Variables

### Priority Order

The secrets manager (`slob/config/secrets.py`) loads secrets in this order:

1. Docker Secrets (`/run/secrets/[secret_name]`)
2. Local files (`./secrets/[secret_name]`)
3. Environment variables (`os.environ.get('[SECRET_NAME]')`)

**Example**: For `ib_account`:
1. Check `/run/secrets/ib_account`
2. Check `./secrets/ib_account`
3. Check `$IB_ACCOUNT` environment variable
4. Raise error if not found

### Setting Environment Variables

**Temporary (current shell)**:
```bash
export IB_ACCOUNT="U1234567"
export IB_PASSWORD="your_password"
```

**Permanent (via .env file)**:
```bash
# .env file
IB_ACCOUNT=U1234567
IB_PASSWORD=your_password
```

**Docker Compose**:
```yaml
# docker-compose.yml
services:
  slob-bot:
    environment:
      - IB_ACCOUNT=${IB_ACCOUNT}
      - IB_PASSWORD=${IB_PASSWORD}
```

---

## Security Best Practices

### 1. Use Restrictive File Permissions

```bash
# Secrets directory: only owner can read/write/execute
chmod 700 secrets/

# Secret files: only owner can read/write
chmod 600 secrets/*

# Verify
ls -la secrets/
# Should show: -rw------- (600)
```

### 2. Never Commit Secrets to Git

**Verify .gitignore**:
```bash
cat .gitignore | grep -E "^(secrets/|\.env$|.*\.key$|.*\.pem$)"
```

**Should include**:
```
secrets/
.env
.env.local
*.key
*.pem
*.p12
*.pfx
```

**Check for accidental commits**:
```bash
# Search git history for accidentally committed secrets
git log -S "IB_PASSWORD" --all
git log -S "DASHBOARD_SECRET_KEY" --all

# If found, rotate credentials immediately
```

### 3. Rotate Credentials Regularly

**Schedule**:
- IB password: Every 90 days (IB requirement)
- API keys: Every 6 months
- Dashboard password: Every 3 months

**Process**:
1. Generate new credentials
2. Update secret files/Docker secrets
3. Restart services
4. Verify connection
5. Revoke old credentials

### 4. Use Password Hashing for Dashboard

**Never store plaintext passwords**:
```bash
# Generate hash
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your-password'))"

# Output (example):
# pbkdf2:sha256:260000$sQHDvs9RtlWz8Lzq$f5e8a...

# Save to secret file
echo "pbkdf2:sha256:260000$..." > secrets/dashboard_password_hash
```

### 5. Separate Production and Development Secrets

```bash
# Development
./secrets/ib_account           # Paper trading account (DU prefix)
./secrets/dashboard_secret_key # Development secret key

# Production (different files/secrets)
/run/secrets/ib_account           # Live trading account (U prefix)
/run/secrets/dashboard_secret_key # Production secret key (different from dev)
```

### 6. Monitor Secret Access

```bash
# Check who accessed secrets directory
sudo ausearch -f /path/to/secrets/ -ts recent

# Monitor file access
inotifywait -m -e access secrets/
```

---

## Troubleshooting

### Secret Not Found

**Error**: `SecretNotFoundError: Required secret 'ib_account' not found`

**Solutions**:
1. Check secret exists:
   ```bash
   # Docker secrets
   docker secret ls | grep ib_account

   # Local files
   ls -la secrets/ib_account

   # Environment variable
   echo $IB_ACCOUNT
   ```

2. Check permissions:
   ```bash
   ls -la secrets/ib_account
   # Should be readable by current user
   ```

3. Check file contents:
   ```bash
   cat secrets/ib_account
   # Should NOT be empty
   ```

4. Verify secret name matches exactly (case-sensitive):
   ```bash
   # Correct: ib_account
   # Wrong: IB_ACCOUNT, ib-account, ibAccount
   ```

---

### Dashboard Login Fails

**Error**: Invalid username/password

**Solutions**:
1. Verify password hash is set:
   ```bash
   cat secrets/dashboard_password_hash
   # Should output: pbkdf2:sha256:...
   ```

2. Regenerate password hash:
   ```bash
   python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('new-password'))" > secrets/dashboard_password_hash
   ```

3. Restart dashboard:
   ```bash
   docker-compose restart slob-bot
   ```

4. Check logs:
   ```bash
   docker logs slob_slob-bot 2>&1 | grep -i "dashboard\|login"
   ```

---

### IB Connection Fails

**Error**: `IB connection failed: Authentication failed`

**Solutions**:
1. Verify credentials are correct:
   ```bash
   cat secrets/ib_account
   cat secrets/ib_username
   # DO NOT cat password (security risk)
   ```

2. Verify IB Gateway is running:
   ```bash
   lsof -i :4002
   ```

3. Test credentials manually via IB TWS/Gateway

4. Check for special characters in password:
   ```bash
   # If password has special chars, ensure proper escaping
   # Use single quotes to prevent shell interpretation
   echo 'P@$$w0rd!' > secrets/ib_password
   ```

---

### Docker Secrets Not Accessible

**Error**: `FileNotFoundError: [Errno 2] No such file or directory: '/run/secrets/ib_account'`

**Solutions**:
1. Verify Docker Swarm is initialized:
   ```bash
   docker info | grep Swarm
   # Should show: Swarm: active
   ```

2. Check secrets are created:
   ```bash
   docker secret ls
   ```

3. Verify service has access to secrets:
   ```bash
   docker service inspect slob_slob-bot --format='{{json .Spec.TaskTemplate.ContainerSpec.Secrets}}'
   ```

4. Check container mounts:
   ```bash
   docker exec $(docker ps -qf "name=slob_slob-bot") ls -la /run/secrets/
   ```

---

## Obtaining Credentials

### Interactive Brokers

1. **Account Number** (`ib_account`):
   - Log into IB Client Portal
   - Account Settings → Account Number (format: U1234567)

2. **Username/Password** (`ib_username`, `ib_password`):
   - Same credentials used to log into IB Gateway/TWS
   - Enable API connections in Account Settings

3. **Paper vs Live Trading**:

   **Paper Trading (Recommended for Testing)**:
   - Account format: `DU1234567` (starts with 'DU')
   - Port: `4002`
   - Set in `.env`:
     ```bash
     IB_ACCOUNT=DU1234567
     IB_GATEWAY_PORT=4002
     TRADING_MODE=paper
     REQUIRE_LIVE_CONFIRMATION=false
     ```

   **Live Trading (Real Money)**:
   - Account format: `U1234567` (starts with 'U')
   - Port: `4001`
   - **CRITICAL**: Must set `REQUIRE_LIVE_CONFIRMATION=true` to enable
   - Set in `.env`:
     ```bash
     IB_ACCOUNT=U1234567
     IB_GATEWAY_PORT=4001
     TRADING_MODE=live
     REQUIRE_LIVE_CONFIRMATION=true  # ← REQUIRED for live trading
     ```

   **Safety Check**:
   - The system validates trading mode on startup
   - Mismatched configurations (e.g., paper account with live port) will fail
   - Live trading without `REQUIRE_LIVE_CONFIRMATION=true` will fail
   - This prevents accidental live trading

### Telegram

1. **Bot Token** (`telegram_bot_token`):
   - Message @BotFather on Telegram
   - Send `/newbot` and follow instructions
   - Copy token (format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

2. **Chat ID** (`telegram_chat_id`):
   - Message your bot
   - Visit: `https://api.telegram.org/bot[YOUR_TOKEN]/getUpdates`
   - Find `"chat":{"id":987654321}` in response
   - Use that ID

### Email (SMTP)

**Gmail Example**:
1. Enable 2-factor authentication
2. Generate app password:
   - Google Account → Security → App Passwords
   - Select "Mail" and device
   - Copy generated password

**Configuration**:
```bash
echo "your-email@gmail.com" > secrets/smtp_username
echo "your-app-password" > secrets/smtp_password
```

In `.env`:
```bash
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_FROM=your-email@gmail.com
SMTP_TO=alerts@yourdomain.com
```

---

## Automated Setup Script

**Coming Soon**: `scripts/setup_secrets.sh`

```bash
#!/bin/bash
# Automated secrets setup (planned)

./scripts/setup_secrets.sh --interactive
# Prompts for each credential
# Validates format
# Creates secret files with correct permissions
# Tests connections
```

---

## Related Documentation

- **Main Guide**: [README.md](../README.md)
- **Deployment**: [DEPLOYMENT.md](DEPLOYMENT.md)
- **Operations**: [OPERATIONAL_RUNBOOK.md](OPERATIONAL_RUNBOOK.md)
- **Security Tests**: `tests/e2e/test_security.py`

---

**Last Updated**: 2025-12-26
**Version**: 1.0
**Status**: Production Ready
