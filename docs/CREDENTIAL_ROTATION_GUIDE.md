# Credential Rotation Guide

**Last Updated**: 2025-12-25
**Audience**: SLOB System Administrators
**Priority**: CRITICAL - Security

---

## ⚠️ WHEN TO ROTATE CREDENTIALS

Rotate credentials **immediately** if:

1. ✅ Credentials were accidentally committed to version control
2. ✅ System was compromised or suspected breach
3. ✅ Team member with access leaves the organization
4. ✅ Credentials were shared via insecure channel (email, Slack, etc.)
5. ✅ Regular rotation schedule (every 90 days recommended)

---

## 🔐 CREDENTIAL INVENTORY

All credentials used by SLOB system:

| Credential | Location | Exposure Risk | Rotation Frequency |
|------------|----------|---------------|-------------------|
| Alpaca API Key | `.env` | HIGH | Every 90 days |
| Alpaca API Secret | `.env` | HIGH | Every 90 days |
| IB Account ID | `.env` | MEDIUM | Never (account ID) |
| Redis Password | `.env` | HIGH | Every 90 days |
| Telegram Bot Token | `.env` | MEDIUM | If compromised |
| Email SMTP Password | `.env` | HIGH | Every 90 days |
| Dashboard Secret Key | `.env` | CRITICAL | Every 90 days |
| Dashboard Password | `.env` (hashed) | CRITICAL | Every 90 days |

---

## 📋 STEP-BY-STEP ROTATION PROCEDURES

### 1. Alpaca API Credentials

**Time Required**: 5 minutes
**Downtime**: 1-2 minutes

```bash
# Step 1: Generate new credentials
# - Login to https://app.alpaca.markets/paper/dashboard/overview
# - Navigate to "Your API Keys"
# - Click "Generate New Key"
# - IMPORTANT: Copy both Key and Secret immediately (shown only once)

# Step 2: Update .env file
nano /Users/erikaberg/Downloads/slobprototype/.env

# Update these lines:
# ALPACA_API_KEY=<new_key_here>
# ALPACA_API_SECRET=<new_secret_here>

# Step 3: Restart services
docker-compose restart slob-bot

# Step 4: Verify new credentials work
docker-compose logs -f slob-bot
# Look for: "✅ Connected to Alpaca" (not "❌ Authentication failed")

# Step 5: Delete old credentials from Alpaca dashboard
# - Go back to "Your API Keys"
# - Click "Delete" on old key

# Step 6: Document rotation
echo "$(date): Rotated Alpaca API credentials - Reason: [YOUR_REASON]" >> docs/credential_rotation_log.txt
```

**Rollback Procedure** (if new credentials fail):
```bash
# Restore old credentials in .env
# Restart: docker-compose restart slob-bot
# DO NOT delete old key from Alpaca yet!
```

---

### 2. Interactive Brokers Account

**Note**: IB Account ID is not a secret credential - it's an identifier. No rotation needed.

If you suspect IB Gateway compromise:
```bash
# Step 1: Change IB account password via IB Account Management
# Step 2: Restart IB Gateway with new password
# Step 3: No changes needed in .env (account ID stays same)
```

---

### 3. Redis Password

**Time Required**: 5 minutes
**Downtime**: 2-3 minutes

```bash
# Step 1: Generate new secure password
NEW_REDIS_PASS=$(openssl rand -base64 32)
echo "New Redis Password: $NEW_REDIS_PASS"

# Step 2: Update Redis configuration
# If using Docker:
docker-compose exec redis redis-cli
# > CONFIG SET requirepass <new_password>
# > AUTH <new_password>
# > CONFIG REWRITE
# > EXIT

# Step 3: Update .env file
nano .env
# Update: REDIS_PASSWORD=<new_password>

# Step 4: Restart dependent services
docker-compose restart slob-bot

# Step 5: Verify connection
docker-compose logs slob-bot | grep "Redis"
# Look for: "✅ Redis connected"

# Step 6: Document
echo "$(date): Rotated Redis password - Reason: [YOUR_REASON]" >> docs/credential_rotation_log.txt
```

---

### 4. Telegram Bot Token

**Time Required**: 3 minutes
**Downtime**: None (alerts will pause)

```bash
# Step 1: Revoke old token (optional but recommended)
# - Open Telegram
# - Talk to @BotFather
# - Send: /mybots
# - Select your bot
# - Click "API Token" → "Revoke current token"

# Step 2: Generate new token
# - @BotFather → "API Token" → "Generate New Token"
# - Copy new token

# Step 3: Update .env
nano .env
# Update: TELEGRAM_BOT_TOKEN=<new_token>

# Step 4: Restart
docker-compose restart slob-bot

# Step 5: Test alerts
python scripts/test_telegram_alert.py

# Step 6: Document
echo "$(date): Rotated Telegram token - Reason: [YOUR_REASON]" >> docs/credential_rotation_log.txt
```

---

### 5. Email SMTP Password

**Time Required**: 5 minutes
**Downtime**: None (alerts will pause)

```bash
# Step 1: Generate new App-Specific Password (Gmail example)
# - Go to https://myaccount.google.com/apppasswords
# - Click "Generate"
# - Copy the 16-character password

# Step 2: Update .env
nano .env
# Update: SMTP_PASSWORD=<new_app_password>

# Step 3: Restart
docker-compose restart slob-bot

# Step 4: Test email
python scripts/test_email_alert.py

# Step 5: Delete old app password from Google account

# Step 6: Document
echo "$(date): Rotated SMTP password - Reason: [YOUR_REASON]" >> docs/credential_rotation_log.txt
```

---

### 6. Dashboard Secret Key (CRITICAL)

**Time Required**: 2 minutes
**Downtime**: None (but all users logged out)

```bash
# Step 1: Generate new secret key
python -c "import secrets; print('DASHBOARD_SECRET_KEY=' + secrets.token_hex(32))"

# Step 2: Update .env
nano .env
# Replace DASHBOARD_SECRET_KEY with new value

# Step 3: Restart
docker-compose restart slob-bot

# WARNING: All active dashboard sessions will be invalidated
# Users must log in again

# Step 4: Document
echo "$(date): Rotated dashboard secret key - Reason: [YOUR_REASON]" >> docs/credential_rotation_log.txt
```

---

### 7. Dashboard Password

**Time Required**: 3 minutes
**Downtime**: None

```bash
# Step 1: Generate new password hash
python -c "from werkzeug.security import generate_password_hash; import getpass; print(generate_password_hash(getpass.getpass('New Password: ')))"

# Step 2: Update .env
nano .env
# Update: DASHBOARD_PASSWORD_HASH=<new_hash>

# Step 3: Restart
docker-compose restart slob-bot

# Step 4: Test login at http://localhost:5000/login

# Step 5: Document
echo "$(date): Rotated dashboard password - Reason: [YOUR_REASON]" >> docs/credential_rotation_log.txt
```

---

## 🚨 EMERGENCY PROCEDURES

### If Credentials Are Compromised RIGHT NOW

**DO THIS IMMEDIATELY** (in order):

```bash
# 1. STOP ALL TRADING (30 seconds)
docker-compose stop slob-bot

# 2. REVOKE COMPROMISED CREDENTIALS (2-5 minutes)
# - Alpaca: Delete API keys at https://app.alpaca.markets
# - Telegram: Talk to @BotFather → /revoke
# - Email: Revoke app password at https://myaccount.google.com/apppasswords

# 3. GENERATE NEW CREDENTIALS (5 minutes)
# Follow rotation procedures above for each compromised credential

# 4. RESTART SYSTEM (1 minute)
docker-compose up -d

# 5. VERIFY SYSTEM HEALTH (2 minutes)
./scripts/health_check.sh

# 6. NOTIFY TEAM
# Send alert to all team members about the compromise

# 7. INCIDENT REPORT
echo "=== SECURITY INCIDENT ===" >> docs/credential_rotation_log.txt
echo "Date: $(date)" >> docs/credential_rotation_log.txt
echo "Compromised: [CREDENTIAL_TYPE]" >> docs/credential_rotation_log.txt
echo "Action Taken: [SUMMARY]" >> docs/credential_rotation_log.txt
echo "========================" >> docs/credential_rotation_log.txt
```

**Total Time**: ~15 minutes

---

## 📅 SCHEDULED ROTATION

Add to cron for quarterly rotation reminder:

```bash
# Edit crontab
crontab -e

# Add this line (runs first day of every quarter at 9 AM)
0 9 1 1,4,7,10 * echo "⚠️ QUARTERLY CREDENTIAL ROTATION DUE" | mail -s "SLOB Security Reminder" your_email@example.com
```

---

## ✅ POST-ROTATION CHECKLIST

After rotating any credential:

- [ ] Old credential revoked/deleted at source
- [ ] New credential updated in `.env`
- [ ] Services restarted successfully
- [ ] Functionality tested (alerts, trading, dashboard)
- [ ] Rotation documented in `credential_rotation_log.txt`
- [ ] Team notified (if applicable)
- [ ] No error logs related to authentication

---

## 📝 CREDENTIAL ROTATION LOG

Keep a log of all rotations:

```bash
# Create log file
touch docs/credential_rotation_log.txt

# Log format:
echo "$(date): [CREDENTIAL_TYPE] rotated - Reason: [SCHEDULED|COMPROMISE|TEAM_CHANGE] - By: [YOUR_NAME]" >> docs/credential_rotation_log.txt
```

---

## 🔒 BEST PRACTICES

1. **Never** commit credentials to git (even in private repos)
2. **Use** environment variables or Docker secrets (not hardcoded)
3. **Rotate** credentials every 90 days minimum
4. **Document** every rotation in the log
5. **Test** immediately after rotation
6. **Revoke** old credentials after confirming new ones work
7. **Use** strong, randomly generated passwords (not human-memorable)
8. **Store** backup credentials in encrypted password manager (1Password, Bitwarden)
9. **Audit** credential access quarterly
10. **Monitor** for unauthorized API usage

---

## 📞 SUPPORT

If credential rotation fails or causes issues:

1. **Rollback** to previous working credentials
2. **Check logs**: `docker-compose logs slob-bot`
3. **Verify** credential format is correct
4. **Test** credentials manually before updating .env
5. **Contact** Alpaca/IB support if provider-side issues

---

## 🔗 RELATED DOCUMENTATION

- [Security Best Practices](SECURITY.md)
- [Deployment Guide](DEPLOYMENT.md)
- [Incident Response Plan](INCIDENT_RESPONSE.md)

---

**Last Review**: 2025-12-25
**Next Review**: 2026-03-25 (quarterly)
