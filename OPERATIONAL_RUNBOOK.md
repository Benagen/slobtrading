# SLOB Trading System - Operational Runbook

**Dagliga operationer och rutinmässiga procedurer för drift av SLOB trading systemet.**

*Version*: 2.0
*Last Updated*: 2025-12-26
*System Status*: Production Ready (95%)

---

## 📋 Table of Contents

1. [Daily Operations](#daily-operations)
2. [Weekly Tasks](#weekly-tasks)
3. [Monthly Tasks](#monthly-tasks)
4. [Monitoring Procedures](#monitoring-procedures)
5. [Common Tasks](#common-tasks)
6. [Performance Checks](#performance-checks)
7. [Backup Verification](#backup-verification)
8. [Alert Management](#alert-management)
9. [System Maintenance](#system-maintenance)
10. [Emergency Procedures](#emergency-procedures)

---

## 📅 Daily Operations

### Morning Checklist (30 minutes before market open)

**Time**: 08:30 EST (30 min before market open at 09:00)

#### 1. System Health Check
```bash
# Run monitoring script
./scripts/monitor.sh

# Check all critical components
✓ IB Gateway connected (port 4002)
✓ Database accessible
✓ Dashboard running (port 5000)
✓ No critical errors in logs
✓ Sufficient disk space (>10GB)
```

#### 2. Verify IB Gateway Connection
```bash
# Check IB Gateway is running
lsof -i :4002

# Test connection
python scripts/test_ib_connection.py

# Expected output:
# ✅ IB Gateway connected
# ✅ Market data subscription active
# ✅ Account balance: $XX,XXX
```

#### 3. Review Overnight Logs
```bash
# Check for errors during off-hours
tail -100 logs/trading.log | grep -i "error\|critical"

# Check error log
tail -20 logs/errors.log

# Look for:
✓ No connection failures
✓ No database corruption
✓ No unexpected shutdowns
```

#### 4. Verify Account Balance
```bash
# Access dashboard
open http://localhost:5000

# Verify:
✓ Account balance matches IB TWS
✓ No unexpected positions
✓ Current drawdown < 5%
```

#### 5. Check Backup Status
```bash
# Verify latest backup exists
ls -lh data/backups/ | head -5

# Check backup age (should be <24h)
find data/backups -name "*.tar.gz" -mtime -1 -ls
```

#### 6. Review Configuration
```bash
# Verify trading is enabled
grep "ENABLE_TRADING" .env

# Verify position limits
grep "MAX_POSITION_SIZE" .env

# Verify risk settings
grep "RISK_PER_TRADE" .env
```

**Checklist Summary**:
- [ ] System health green
- [ ] IB Gateway connected
- [ ] No critical errors
- [ ] Account balance verified
- [ ] Backup exists (<24h old)
- [ ] Configuration correct

---

### During Trading Hours (09:00 - 16:00 EST)

#### Every 30 Minutes: Quick Status Check
```bash
# Quick monitoring (5 minutes)
./scripts/monitor.sh

# Check:
✓ IB connection active
✓ Active setups count
✓ No error log growth
✓ Dashboard accessible
```

#### Hourly: Review Trading Activity
```bash
# Access dashboard
open http://localhost:5000

# Review:
✓ Recent trades (last hour)
✓ P&L trend
✓ Active positions
✓ Risk metrics (current DD)
```

#### When Setup Detected (Telegram Alert)
```
📢 Telegram Alert: "Setup Detected - abc12345"

Actions:
1. Access dashboard immediately
2. Verify setup details:
   - Entry price reasonable
   - SL/TP calculated correctly
   - Risk:Reward > 1.5:1
3. Confirm order placement
4. Monitor fill status
```

#### When Order Filled (Telegram Alert)
```
📢 Telegram Alert: "Order Filled - SHORT NQ @ 15,234"

Actions:
1. Verify order in IB TWS
2. Check bracket orders (SL + TP) placed
3. Note position in trading journal
4. Set calendar reminder for exit review
```

#### When Error Occurs (Telegram Alert)
```
📢 Telegram Alert: "ERROR - Connection lost"

Actions:
1. Check IB Gateway status
2. Review error logs
3. Verify system auto-reconnected
4. If not reconnected → Manual intervention
5. See INCIDENT_RESPONSE.md
```

---

### End of Day Procedures (16:30 EST)

**Time**: 16:30 EST (30 min after market close at 16:00)

#### 1. Review Daily Performance
```bash
# Access dashboard
open http://localhost:5000

# Review:
✓ Total setups detected today
✓ Orders placed
✓ P&L for the day
✓ Win rate (updated)
✓ Current drawdown
```

#### 2. Verify Open Positions
```bash
# Check for any open positions
# Dashboard → Active Positions section

Expected:
✓ All intraday positions should be closed
✓ If overnight positions → verify risk acceptable
```

#### 3. Check System Logs
```bash
# Review full day logs
tail -500 logs/trading.log

# Look for:
✓ Setup detection count
✓ Order execution count
✓ Any errors/warnings
✓ Connection stability
```

#### 4. Daily Backup
```bash
# Manual backup (automated runs at 2 AM)
./scripts/backup_state.sh --verify

# Verify backup created
ls -lh data/backups/ | head -1
```

#### 5. Update Trading Journal
```markdown
# Trading Journal Entry
Date: 2025-12-26
Setups Detected: 2
Orders Placed: 1
P&L: +$450
Notes: Clean day, spike rule activated on setup #1
```

#### 6. Plan for Next Day
```bash
# Check upcoming economic calendar
# Review any outstanding issues
# Prepare for tomorrow's session
```

**End of Day Checklist**:
- [ ] Daily P&L reviewed
- [ ] No open positions (or documented)
- [ ] Logs checked
- [ ] Backup verified
- [ ] Trading journal updated
- [ ] Tomorrow's plan ready

---

## 📅 Weekly Tasks

### Monday Morning (Weekly Planning)

**Time**: 09:00 Monday

#### 1. Weekly System Review
```bash
# Run comprehensive monitoring
./scripts/monitor.sh --full

# Review:
✓ System uptime (should be high)
✓ Weekly P&L trend
✓ Setup detection frequency
✓ Win rate trend
```

#### 2. Review Last Week's Performance
```bash
# Access dashboard → P&L Chart (7-day view)

Analyze:
✓ Total setups last week
✓ Win rate vs target (47.6%)
✓ Average R:R
✓ Max DD vs threshold (25%)
```

#### 3. Check Backup Retention
```bash
# Verify weekly backups exist
ls -lh data/backups/ | grep "$(date -d '7 days ago' +%Y%m%d)"

# Verify automated cleanup working
find data/backups -name "*.tar.gz" -mtime +30 -ls
# Should be empty (30-day retention)
```

#### 4. Review Alert History
```bash
# Check Telegram message history
# Review frequency of:
✓ Setup alerts (should align with backtest frequency)
✓ Error alerts (should be minimal)
✓ System alerts (startup/shutdown)
```

---

### Wednesday (Mid-week Check)

**Time**: Any time

#### 1. Dependency Updates
```bash
# Check for security updates
pip list --outdated

# Review critical packages:
✓ ib_insync
✓ flask
✓ pandas
✓ xgboost
```

#### 2. Disk Space Monitoring
```bash
# Check disk usage
df -h

# Expected:
✓ At least 10GB free space
✓ Logs not consuming excessive space
```

#### 3. Database Maintenance
```bash
# Check database size
ls -lh data/*.db

# Vacuum database if >500MB
sqlite3 data/slob_state.db "VACUUM;"
```

---

### Friday (Week-end Preparation)

**Time**: 16:30 Friday

#### 1. Weekly Backup
```bash
# Create special weekly backup
./scripts/backup_state.sh --verify --s3

# Tag backup as weekly
mv data/backups/db_$(date +%Y%m%d_*)*.tar.gz \
   data/backups/WEEKLY_db_$(date +%Y%m%d).tar.gz
```

#### 2. Weekly Performance Report
```bash
# Generate weekly summary
python scripts/generate_weekly_report.py

# Email to yourself
# Or review in dashboard
```

#### 3. System Health Score
```bash
# Run all tests (optional but recommended)
pytest tests/e2e/test_deployment.py -v
pytest tests/e2e/test_security.py -v

# All should pass
```

---

## 📅 Monthly Tasks

### First Monday of Month

**Time**: 09:00

#### 1. Monthly Performance Review
```bash
# Access dashboard → P&L Chart (30-day view)

Review:
✓ Monthly P&L
✓ Monthly win rate
✓ Monthly Sharpe ratio
✓ Max DD for month
✓ Compare to backtest metrics
```

#### 2. Security Audit
```bash
# Run security tests
pytest tests/e2e/test_security.py -v

# Verify:
✓ File permissions correct
✓ No credential exposure
✓ Authentication working
✓ No vulnerable dependencies
```

#### 3. Rotate Credentials (if needed)
```bash
# If using shared credentials, rotate:
# - Dashboard password
# - Telegram bot token (if compromised)
# - Email app password (if needed)

# Update .env
nano .env

# Restart system
docker-compose restart
```

#### 4. Dependency Security Scan
```bash
# Install pip-audit if not installed
pip install pip-audit

# Run security scan
pip-audit

# Fix any vulnerabilities found
pip install --upgrade [package]
```

#### 5. Backup Verification Drill
```bash
# Test rollback procedure
./scripts/rollback.sh --db-only --timestamp [last-month-backup]

# Verify:
✓ Database restored successfully
✓ Data integrity intact
✓ System operational

# Rollback to current state
./scripts/rollback.sh --timestamp [current-backup]
```

#### 6. Log Analysis
```bash
# Analyze logs for patterns
grep "ERROR" logs/trading.log.* | wc -l
grep "SETUP FOUND" logs/trading.log.* | wc -l

# Compare to expected frequency
```

---

## 📊 Monitoring Procedures

### Real-time Monitoring

#### Dashboard Monitoring (Continuous)
```bash
# Access dashboard
open http://localhost:5000

# Watch for:
✓ Active setups count
✓ Recent trades list
✓ P&L chart trend
✓ Error log section (should be empty/minimal)
✓ Circuit breaker status (green)
```

#### Command-line Monitoring (When needed)
```bash
# Quick status
./scripts/monitor.sh

# Continuous monitoring (30s refresh)
./scripts/monitor.sh --watch

# Extended information
./scripts/monitor.sh --full

# Specific checks:
./scripts/monitor.sh --tail 100  # Last 100 log lines
```

### Log Monitoring

#### Main Log
```bash
# Follow main log in real-time
tail -f logs/trading.log

# Filter for specific events:
tail -f logs/trading.log | grep "SETUP"      # Setup detection
tail -f logs/trading.log | grep "ORDER"      # Order placement
tail -f logs/trading.log | grep "ERROR"      # Errors
tail -f logs/trading.log | grep "IB"         # IB Gateway events
```

#### Error Log
```bash
# Follow error log
tail -f logs/errors.log

# Expected: Minimal activity
# Action if errors: See INCIDENT_RESPONSE.md
```

### Alert Monitoring

#### Telegram Alerts
```
Expected alerts during trading:
- Setup detected (rare: 0.65/week avg)
- Order placed (when setup detected)
- System started (once per day)
- System stopped (once per day)

Unexpected alerts:
- Connection lost (requires investigation)
- Order rejected (requires investigation)
- Critical error (immediate action)
```

#### Email Alerts
```
Expected emails:
- Daily summary (every 17:00)
- Weekly summary (Friday 17:00)
- Critical errors (rare)

Action if no daily email:
- Check email notifier configuration
- Check logs for email send failures
```

---

## 🔧 Common Tasks

### Restart System

#### Graceful Restart
```bash
# Using Docker
docker-compose restart slob-bot

# Direct (if not using Docker)
pkill -TERM -f "python.*run_paper_trading"
# Wait 10 seconds
python scripts/run_paper_trading.py --account DU123456 --gateway
```

#### Full System Restart
```bash
# Stop everything
docker-compose down

# Wait 30 seconds

# Start everything
docker-compose up -d

# Verify health
./scripts/monitor.sh
```

### View Logs

#### Recent Logs
```bash
# Last 50 lines
tail -50 logs/trading.log

# Last 50 errors
tail -50 logs/errors.log

# Specific date
grep "2025-12-26" logs/trading.log | tail -100
```

#### Search Logs
```bash
# Search for setup detection
grep "SETUP FOUND" logs/trading.log.*

# Search for errors
grep -i "error" logs/trading.log.*

# Search for specific setup ID
grep "abc12345" logs/trading.log.*
```

### Check Active Positions

#### Via Dashboard
```bash
# Access dashboard
open http://localhost:5000

# Navigate to Active Positions section
```

#### Via Command Line
```bash
# Query database
sqlite3 data/slob_state.db "
SELECT id, state, entry_price, sl_price, tp_price
FROM active_setups
WHERE state != 'SETUP_COMPLETE'
ORDER BY created_at DESC;
"
```

#### Via IB TWS
```
1. Open IB TWS
2. Navigate to Portfolio
3. Verify positions match database
```

### Manual Backup

#### Standard Backup
```bash
# Create backup
./scripts/backup_state.sh

# Verify backup created
ls -lh data/backups/ | head -1
```

#### Verified Backup (Recommended)
```bash
# Create and verify backup
./scripts/backup_state.sh --verify

# Output should show:
# ✓ db_YYYYMMDD_HHMMSS.tar.gz - Valid (XXM)
# ✓ logs_YYYYMMDD_HHMMSS.tar.gz - Valid (XXM)
# ✓ config_YYYYMMDD_HHMMSS.tar.gz - Valid (XXK)
```

#### Backup with S3 Upload
```bash
# Ensure AWS credentials configured
export AWS_S3_BUCKET=my-slob-backups

# Create, verify, and upload
./scripts/backup_state.sh --verify --s3
```

### Update Configuration

#### Change Risk Parameters
```bash
# Edit .env file
nano .env

# Find and modify:
RISK_PER_TRADE=0.01          # 1% risk per trade
MAX_POSITION_SIZE=5          # Max 5 contracts
MAX_DRAWDOWN_STOP=0.25       # Stop at 25% DD

# Save and exit (Ctrl+O, Ctrl+X)

# Restart system to apply changes
docker-compose restart slob-bot
```

#### Change Strategy Parameters
```bash
# Edit .env file
nano .env

# Find and modify:
CONSOL_MIN_DURATION=5
CONSOL_MAX_DURATION=30
SL_BUFFER_PIPS=1.0
TP_RISK_REWARD=2.0

# Save and restart
docker-compose restart slob-bot
```

### Database Queries

#### Trade History
```bash
sqlite3 data/slob_state.db "
SELECT
    DATE(entry_time) as date,
    COUNT(*) as trades,
    SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) as wins,
    ROUND(SUM(pnl), 2) as total_pnl
FROM trade_history
WHERE entry_time > datetime('now', '-30 days')
GROUP BY DATE(entry_time)
ORDER BY date DESC;
"
```

#### Active Setups
```bash
sqlite3 data/slob_state.db "
SELECT
    id,
    state,
    entry_price,
    created_at
FROM active_setups
WHERE state != 'SETUP_COMPLETE'
ORDER BY created_at DESC
LIMIT 10;
"
```

#### System Statistics
```bash
sqlite3 data/slob_state.db "
SELECT
    (SELECT COUNT(*) FROM active_setups) as total_setups,
    (SELECT COUNT(*) FROM trade_history) as total_trades,
    (SELECT ROUND(SUM(pnl), 2) FROM trade_history) as total_pnl,
    (SELECT ROUND(AVG(pnl), 2) FROM trade_history) as avg_pnl
FROM active_setups
LIMIT 1;
"
```

---

## 📈 Performance Checks

### Daily Performance Metrics

```bash
# Quick P&L check
sqlite3 data/slob_state.db "
SELECT
    COUNT(*) as trades_today,
    SUM(pnl) as pnl_today,
    SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) as wins
FROM trade_history
WHERE DATE(entry_time) = DATE('now');
"
```

### Weekly Performance Trends
```bash
# Weekly summary
sqlite3 data/slob_state.db "
SELECT
    strftime('%Y-W%W', entry_time) as week,
    COUNT(*) as trades,
    ROUND(SUM(pnl), 2) as total_pnl,
    ROUND(AVG(pnl), 2) as avg_pnl,
    ROUND(100.0 * SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate
FROM trade_history
GROUP BY strftime('%Y-W%W', entry_time)
ORDER BY week DESC
LIMIT 4;
"
```

### System Health Metrics
```bash
# Database size
ls -lh data/*.db

# Log file size
du -sh logs/

# Backup size
du -sh data/backups/

# Memory usage (if Docker)
docker stats --no-stream slob-bot
```

---

## 💾 Backup Verification

### Daily Backup Verification

```bash
# Check latest backup exists
LATEST=$(ls -t data/backups/db_*.tar.gz | head -1)
echo "Latest backup: $LATEST"

# Check age (should be <24 hours)
find data/backups -name "db_*.tar.gz" -mtime -1 | head -1

# Verify integrity
tar -tzf "$LATEST" > /dev/null && echo "✓ Backup integrity OK"
```

### Weekly Backup Test

```bash
# Extract backup to temp directory
TEMP_DIR=$(mktemp -d)
LATEST=$(ls -t data/backups/db_*.tar.gz | head -1)
tar -xzf "$LATEST" -C "$TEMP_DIR"

# Verify database integrity
sqlite3 "$TEMP_DIR/db_*/slob_state.db" "PRAGMA integrity_check;"

# Cleanup
rm -rf "$TEMP_DIR"

# Expected output: "ok"
```

---

## 🚨 Alert Management

### Telegram Alert Configuration

```bash
# Verify Telegram is configured
grep "TELEGRAM_BOT_TOKEN" .env
grep "TELEGRAM_CHAT_ID" .env

# Test Telegram alerts
python slob/monitoring/telegram_notifier.py

# Expected: Test message received
```

### Email Alert Configuration

```bash
# Verify Email is configured
grep "SMTP_SERVER" .env
grep "SENDER_EMAIL" .env

# Test email alerts
python slob/monitoring/email_notifier.py

# Expected: Test email received
```

### Alert Frequency Review

```bash
# Count alerts by type (from logs)
grep "Telegram" logs/trading.log | grep "Setup" | wc -l      # Setup alerts
grep "Telegram" logs/trading.log | grep "Order" | wc -l      # Order alerts
grep "Telegram" logs/trading.log | grep "Error" | wc -l      # Error alerts

# Expected frequency:
# Setup alerts: ~0.65/week (2-3/month)
# Order alerts: Same as setup alerts
# Error alerts: 0-2/month (minimal)
```

---

## 🔧 System Maintenance

### Weekly Maintenance

```bash
# 1. Vacuum database (if needed)
sqlite3 data/slob_state.db "VACUUM;"

# 2. Cleanup old logs (automated but verify)
find logs/ -name "*.log.*" -mtime +30 -delete

# 3. Cleanup old backups (automated but verify)
find data/backups/ -name "*.tar.gz" -mtime +30 -delete

# 4. Check Docker disk usage
docker system df

# 5. Prune unused Docker images
docker image prune -f
```

### Monthly Maintenance

```bash
# 1. Update dependencies (after testing)
pip install --upgrade ib_insync pandas flask

# 2. Security scan
pip-audit

# 3. Full system test
pytest tests/ -v

# 4. Performance benchmark
pytest tests/stress/test_load.py -v

# 5. Backup verification drill
./scripts/rollback.sh --db-only --timestamp [test-backup]
```

---

## 🚑 Emergency Procedures

### System Not Responding

```bash
# 1. Check if process is running
ps aux | grep "run_paper_trading\|slob-bot"

# 2. Check logs for crash
tail -100 logs/trading.log

# 3. Restart system
docker-compose restart slob-bot

# 4. Monitor recovery
./scripts/monitor.sh --watch
```

### IB Connection Lost

```bash
# 1. Check IB Gateway status
lsof -i :4002

# 2. Restart IB Gateway
# (Instructions depend on IB Gateway setup)

# 3. System should auto-reconnect
# Monitor logs:
tail -f logs/trading.log | grep "IB.*connect"

# 4. If not reconnecting, restart system
docker-compose restart slob-bot
```

### Database Corruption

```bash
# 1. Stop system immediately
docker-compose stop slob-bot

# 2. Check database integrity
sqlite3 data/slob_state.db "PRAGMA integrity_check;"

# 3. If corrupted, restore from backup
./scripts/rollback.sh --db-only --auto

# 4. Verify restored database
sqlite3 data/slob_state.db "PRAGMA integrity_check;"

# 5. Restart system
docker-compose start slob-bot
```

### Circuit Breaker Triggered

```bash
# System stops trading at 25% drawdown

# 1. Access dashboard
open http://localhost:5000

# 2. Review:
# - Current drawdown
# - Recent trades
# - What caused drawdown

# 3. Analyze logs for issues
grep "Circuit Breaker" logs/trading.log

# 4. Decide:
# Option A: Reduce position sizes and resume
# Option B: Stop trading for the day
# Option C: Analyze strategy parameters

# 5. To resume (if acceptable):
# Update configuration to reduce risk
nano .env
# RISK_PER_TRADE=0.005  # Reduce to 0.5%
docker-compose restart slob-bot
```

For detailed incident response procedures, see **[INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md)**.

---

## 📞 Contacts & Resources

### Documentation
- Main Guide: [README.md](README.md)
- Deployment: [DEPLOYMENT.md](DEPLOYMENT.md)
- Incidents: [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md)
- Testing: [TESTING_GUIDE.md](TESTING_GUIDE.md)

### Scripts
- Deploy: `./scripts/deploy.sh`
- Monitor: `./scripts/monitor.sh`
- Backup: `./scripts/backup_state.sh`
- Rollback: `./scripts/rollback.sh`
- Pre-flight: `./scripts/preflight_check.sh`

### Logs
- Main Log: `logs/trading.log`
- Error Log: `logs/errors.log`
- Rotated Logs: `logs/trading.log.YYYY-MM-DD`

### Monitoring
- Dashboard: http://localhost:5000
- Telegram: Check bot for alerts
- Email: Daily summaries

---

*This runbook is a living document. Update as procedures change.*

---

*Last Updated: 2025-12-26*
*Version: 2.0*
*Status: Production Ready*
