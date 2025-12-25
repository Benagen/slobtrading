# SLOB Strategy - Production Deployment Guide

Complete guide for deploying the SLOB trading strategy to production VPS.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Phase 1: Repository Setup](#phase-1-repository-setup)
3. [Phase 2: Local Validation](#phase-2-local-validation)
4. [Phase 3: Dockerization](#phase-3-dockerization)
5. [Phase 4: Monitoring Setup](#phase-4-monitoring-setup)
6. [Phase 5: VPS Deployment](#phase-5-vps-deployment)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### System Requirements
- **Python**: 3.9+
- **Operating System**: Ubuntu 22.04 LTS (production) or macOS/Linux (local)
- **RAM**: Minimum 2GB (4GB recommended)
- **Disk Space**: 10GB+ for data and logs
- **Network**: Stable internet connection

### Accounts & Services
- ✅ Interactive Brokers paper trading account
- ✅ IB Gateway or TWS installed and configured
- ✅ VPS account (DigitalOcean NYC3 recommended for low latency)
- 🔲 Telegram account (optional, for alerts)
- 🔲 Email/SMTP credentials (optional, for notifications)

### Knowledge Required
- Basic Docker familiarity
- SSH and command-line skills
- Understanding of trading concepts (stop-loss, take-profit, etc.)

---

## Phase 1: Repository Setup

**Duration**: 30 minutes
**Goal**: Clean git repository with proper secrets management

### 1.1 Clone Repository

```bash
git clone <your-repo-url>
cd slobprototype
```

### 1.2 Environment Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit with your credentials
nano .env  # or your preferred editor
```

**Required Settings**:
```bash
IB_USERNAME=your_ib_username
IB_PASSWORD=your_ib_password
IB_ACCOUNT=DU1234567  # Your paper account
TELEGRAM_BOT_TOKEN=your_token  # Optional
TELEGRAM_CHAT_ID=your_chat_id  # Optional
```

### 1.3 Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install packages
pip install -r requirements.txt
```

### 1.4 Verify Installation

```bash
# Test imports
python -c "from slob.live import LiveTradingEngine; print('✓ Imports OK')"

# Check data directory
ls -la data/
```

---

## Phase 2: Local Validation

**Duration**: 48+ hours (mostly monitoring time)
**Goal**: Validate system works end-to-end with IB

### 2.1 Test IB Connection

```bash
# Start IB Gateway/TWS first, then:
python scripts/test_ib_connection.py
```

**Expected Output**:
```
✓ Connected to IB Gateway
✓ Account: DU1234567
✓ NQ front month: NQZ2025
✓ Market data streaming
```

**Troubleshooting**:
- Ensure IB Gateway is running
- Check paper trading mode is enabled
- Verify API settings in TWS/Gateway (Enable ActiveX and Socket Clients)

### 2.2 Run Integration Tests

```bash
# Run all integration tests
pytest tests/integration/test_live_engine_integration.py -v

# Expected: All tests should pass
```

### 2.3 Start Monitoring Mode

```bash
# Monitor for 48 hours without placing orders
python scripts/run_paper_trading.py --monitor-only

# Or run in background
nohup python scripts/run_paper_trading.py --monitor-only > logs/monitor.log 2>&1 &
```

**What to Check**:
- ✅ IB connection stays stable
- ✅ Candles aggregate correctly
- ✅ Setup detection logs appear (if market conditions are right)
- ✅ No crashes or memory leaks

### 2.4 Test Order Execution (Dry Run)

```bash
# Enable order placement in paper mode
python scripts/run_paper_trading.py

# Monitor logs for:
# - Setup detected events
# - Bracket order placement
# - Order status updates
```

**Validation Checklist**:
- [ ] IB connection stable for 48+ hours
- [ ] Candles store correctly in SQLite
- [ ] Setup detection matches expected frequency (~0.65/week)
- [ ] Orders place without duplicates
- [ ] State persists across restarts
- [ ] No error messages in logs

---

## Phase 3: Dockerization

**Duration**: 2-3 hours
**Goal**: Containerize system for reproducible deployment

### 3.1 Build Docker Image

```bash
# Build the main container
docker build -t slob-bot:latest .

# Expected output: Successfully built and tagged
```

### 3.2 Start Services

```bash
# Start all services (IB Gateway + SLOB bot)
docker-compose up -d

# Check status
docker-compose ps
```

**Expected Output**:
```
NAME            STATUS          PORTS
ib-gateway      Up 30 seconds   4002/tcp, 5900/tcp
slob-bot        Up 15 seconds
```

### 3.3 Verify Container Health

```bash
# Check health status
docker-compose ps

# View logs
docker-compose logs -f slob-bot

# Run health check script
docker exec slob-bot python scripts/health_check.py
```

**Expected Health Check Output**:
```
Database: ✓
IB Gateway: ✓
```

### 3.4 Test Container Persistence

```bash
# Restart container
docker-compose restart slob-bot

# Verify state persists
docker-compose logs --tail=50 slob-bot | grep "Recovered state"

# Check database still accessible
docker exec slob-bot ls -lh /app/data/*.db
```

**Validation Checklist**:
- [ ] Containers build successfully
- [ ] IB Gateway container connects
- [ ] SLOB bot starts and connects to IB
- [ ] Data persists in volumes across restarts
- [ ] Logs accessible via docker-compose logs
- [ ] Health checks pass

---

## Phase 4: Monitoring Setup

**Duration**: 4-6 hours
**Goal**: Add alerts and dashboard

### 4.1 Setup Telegram Bot

1. **Create Bot**:
   - Message @BotFather on Telegram
   - Send `/newbot` and follow prompts
   - Save the bot token

2. **Get Chat ID**:
   ```bash
   # Send a message to your bot, then visit:
   curl https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates

   # Look for "chat":{"id":123456789}
   ```

3. **Update .env**:
   ```bash
   TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
   TELEGRAM_CHAT_ID=123456789
   ```

4. **Test Notification**:
   ```bash
   python -c "
   from slob.monitoring.telegram_notifier import TelegramNotifier
   notifier = TelegramNotifier()
   notifier.send_alert('Test alert from SLOB bot', 'INFO')
   "
   ```

### 4.2 Setup Email Notifications

1. **Gmail Setup** (recommended):
   - Enable 2-Factor Authentication
   - Generate App Password: https://myaccount.google.com/apppasswords
   - Use app password (not your regular password)

2. **Update .env**:
   ```bash
   SMTP_SERVER=smtp.gmail.com
   SMTP_PORT=587
   SENDER_EMAIL=your-email@gmail.com
   SENDER_PASSWORD=your-app-password
   ALERT_EMAILS=recipient1@example.com,recipient2@example.com
   ```

3. **Test Email**:
   ```bash
   python -c "
   from slob.monitoring.email_notifier import EmailNotifier
   notifier = EmailNotifier()
   notifier.send_email('SLOB Test', 'Email notifications working!')
   "
   ```

### 4.3 Setup Web Dashboard

1. **Start Dashboard Container**:
   ```bash
   # Dashboard starts automatically with docker-compose up
   # Access at http://localhost:5000
   ```

2. **Verify Dashboard**:
   - Open browser to `http://localhost:5000`
   - Should see SLOB dashboard with status
   - Check `/api/status` endpoint

**Validation Checklist**:
- [ ] Telegram bot sends test message
- [ ] Email notifications received
- [ ] Dashboard accessible and shows data
- [ ] All notification channels working

---

## Phase 5: VPS Deployment

**Duration**: 2-3 hours
**Goal**: Deploy to production VPS (NYC3)

### 5.1 VPS Prerequisites

**If not already done**:
```bash
# SSH to VPS
ssh root@YOUR_VPS_IP

# Update system
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# Install Docker Compose
apt install docker-compose-plugin -y

# Create application directory
mkdir -p /opt/slob
cd /opt/slob
```

### 5.2 Deploy to VPS

**From local machine**:

```bash
# Set VPS IP
export VPS_HOST="your.vps.ip.address"

# Make deploy script executable
chmod +x deploy.sh

# Deploy
./deploy.sh
```

**What deploy.sh does**:
1. Syncs code to VPS (excluding data/logs)
2. Stops existing containers
3. Builds fresh images
4. Starts services
5. Shows status and logs

### 5.3 Transfer Secrets

```bash
# Copy .env to VPS (one-time)
scp .env root@YOUR_VPS_IP:/opt/slob/

# Verify
ssh root@YOUR_VPS_IP 'cat /opt/slob/.env | grep IB_USERNAME'
```

### 5.4 Monitor Production

```bash
# Use monitor script
chmod +x monitor.sh
./monitor.sh

# Or SSH directly
ssh root@YOUR_VPS_IP 'cd /opt/slob && docker-compose logs -f slob-bot'
```

### 5.5 Setup Auto-Restart (Cron)

**On VPS**:
```bash
# Edit crontab
crontab -e

# Add health check (every 5 minutes)
*/5 * * * * /usr/bin/docker exec slob-bot python scripts/health_check.py || /usr/bin/docker-compose -f /opt/slob/docker-compose.yml restart slob-bot

# Add daily backup (2 AM)
0 2 * * * cp /opt/slob/data/slob_state.db /opt/slob/data/backups/slob_state_$(date +\%Y\%m\%d).db
```

### 5.6 Final Validation

```bash
# Check all services running
ssh root@YOUR_VPS_IP 'docker-compose -f /opt/slob/docker-compose.yml ps'

# Verify logs
ssh root@YOUR_VPS_IP 'docker-compose -f /opt/slob/docker-compose.yml logs --tail=100 slob-bot'

# Test notification
ssh root@YOUR_VPS_IP 'docker exec slob-bot python -c "
from slob.monitoring.telegram_notifier import TelegramNotifier
TelegramNotifier().send_alert(\"VPS deployment successful!\", \"SUCCESS\")
"'
```

**Production Checklist**:
- [ ] VPS deployment successful
- [ ] All containers running
- [ ] IB connection stable
- [ ] Telegram alerts received
- [ ] Dashboard accessible (if exposed)
- [ ] Health checks passing
- [ ] Cron jobs configured
- [ ] Backups working

---

## Troubleshooting

### IB Connection Issues

**Problem**: "Connection refused" or "Unable to connect"

**Solutions**:
```bash
# 1. Check IB Gateway is running
docker-compose logs ib-gateway | grep "started successfully"

# 2. Verify port is open
docker exec slob-bot nc -zv ib-gateway 4002

# 3. Check TWS/Gateway settings
# - Enable API in Global Configuration
# - Check "Enable ActiveX and Socket Clients"
# - Add 127.0.0.1 to Trusted IPs

# 4. Restart IB Gateway
docker-compose restart ib-gateway
sleep 30
docker-compose restart slob-bot
```

### Database Locked Errors

**Problem**: "Database is locked"

**Solutions**:
```bash
# 1. Check for multiple processes
docker exec slob-bot ps aux | grep python

# 2. Stop all containers
docker-compose down

# 3. Wait for DB to release locks
sleep 10

# 4. Restart
docker-compose up -d
```

### No Setups Detected

**Problem**: Running for days but no setups found

**Analysis**:
- **Expected frequency**: 0.65 setups per week (about 1 every 10 days)
- **Market dependent**: May go weeks without valid setups
- **Check logs**: Look for LIQ #1 candidates being detected but failing other criteria

**Validation**:
```bash
# Check detection logs
docker-compose logs slob-bot | grep "LIQ DETECTED"
docker-compose logs slob-bot | grep "CONSOL"
docker-compose logs slob-bot | grep "SWEEP"

# Compare with backtest on same period
python scripts/run_backtest_with_ib_data.py --input data/nq_6mo.csv
```

### Memory Leaks

**Problem**: Container memory usage growing

**Solutions**:
```bash
# 1. Check memory usage
docker stats slob-bot

# 2. Restart container (state persists)
docker-compose restart slob-bot

# 3. Add memory limit to docker-compose.yml
services:
  slob-bot:
    mem_limit: 1g
    memswap_limit: 1g
```

### Order Execution Failures

**Problem**: Orders not placing or getting rejected

**Check**:
```bash
# 1. Verify account has permissions
# Check IB paper trading settings

# 2. Check order logs
docker-compose logs slob-bot | grep "ORDER"

# 3. Verify position size calculation
docker-compose logs slob-bot | grep "position_size"

# 4. Test manual order
python scripts/test_order_execution.py
```

### Dashboard Not Loading

**Problem**: Can't access web dashboard

**Solutions**:
```bash
# 1. Check dashboard container
docker-compose ps dashboard

# 2. Check port binding
docker-compose logs dashboard

# 3. Test locally
curl http://localhost:5000/api/status

# 4. If on VPS, check firewall
ufw status
ufw allow 5000/tcp
```

---

## Maintenance

### Daily Checks
```bash
# Morning routine (automated via monitor.sh)
./monitor.sh
```

### Weekly Tasks
```bash
# Check disk usage
df -h /opt/slob/data

# Review logs for errors
docker-compose logs --since 7d slob-bot | grep ERROR

# Verify backups
ls -lh /opt/slob/data/backups/
```

### Monthly Tasks
```bash
# Update containers
docker-compose pull
docker-compose up -d --build

# Clean old logs
find /opt/slob/logs -name "*.log" -mtime +30 -delete

# Clean old backups (keep 60 days)
find /opt/slob/data/backups -name "*.db" -mtime +60 -delete
```

---

## Performance Optimization

### Latency Tuning
```bash
# Check latency to IBKR servers
ping api.ibkr.com

# NYC3 VPS should see <10ms
```

### Database Optimization
```bash
# Enable WAL mode (better for concurrent access)
sqlite3 /app/data/slob_state.db "PRAGMA journal_mode=WAL;"

# Vacuum database monthly
sqlite3 /app/data/slob_state.db "VACUUM;"
```

### Log Rotation
```bash
# Add to cron (weekly)
0 0 * * 0 docker-compose exec slob-bot find /app/logs -name "*.log" -mtime +7 -exec gzip {} \;
```

---

## Security Best Practices

1. **Never commit .env**: Already in .gitignore
2. **Use SSH keys**: Disable password auth on VPS
3. **Firewall**: Only expose necessary ports
4. **Regular updates**: Keep Docker and system updated
5. **Backup encryption**: Encrypt database backups
6. **Monitoring**: Review logs for unusual activity

---

## Support & Resources

- **Plan**: `.claude/plans/eager-spinning-scott.md`
- **Validation**: `data/setups_for_review.csv`
- **Logs**: `docker-compose logs -f slob-bot`
- **Health**: `docker exec slob-bot python scripts/health_check.py`

---

*Last Updated: 2025-12-25*
*Version: 1.0*
