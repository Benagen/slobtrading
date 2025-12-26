# SLOB Trading System - Incident Response Guide

**Procedurer för hantering av incidenter och systemfel.**

*Version*: 2.0
*Last Updated*: 2025-12-26
*System Status*: Production Ready (95%)

---

## 🚨 Incident Severity Levels

| Severity | Description | Response Time | Example |
|----------|-------------|---------------|---------|
| **P0 - Critical** | Trading stopped, data loss risk | Immediate | Database corruption, System crash |
| **P1 - High** | Trading degraded, manual intervention needed | <15 min | IB connection lost, Circuit breaker triggered |
| **P2 - Medium** | Functionality impaired, workaround available | <1 hour | Dashboard down, Alert failures |
| **P3 - Low** | Minor issues, no immediate impact | <24 hours | Slow queries, Log rotation issues |

---

## 📋 Table of Contents

1. [Critical Incidents (P0)](#critical-incidents-p0)
2. [High Priority Incidents (P1)](#high-priority-incidents-p1)
3. [Medium Priority Incidents (P2)](#medium-priority-incidents-p2)
4. [Low Priority Incidents (P3)](#low-priority-incidents-p3)
5. [Common Error Messages](#common-error-messages)
6. [Post-Incident Review](#post-incident-review)

---

## 🔴 Critical Incidents (P0)

### P0-1: Database Corruption

**Symptoms**:
- `sqlite3.DatabaseError: database disk image is malformed`
- System crashes on startup
- Trades not being recorded

**Immediate Actions**:
```bash
# 1. STOP SYSTEM IMMEDIATELY
docker-compose stop slob-bot

# 2. Assess damage
sqlite3 data/slob_state.db "PRAGMA integrity_check;"

# Output scenarios:
# - "ok" → False alarm, proceed to step 5
# - "Error" → Corruption confirmed, proceed to step 3
```

**Recovery Procedure**:
```bash
# 3. Create safety backup of corrupted database
cp data/slob_state.db data/slob_state.db.corrupted_$(date +%Y%m%d_%H%M%S)

# 4. Restore from latest backup
./scripts/rollback.sh --db-only --auto

# 5. Verify restored database
sqlite3 data/slob_state.db "PRAGMA integrity_check;"
# Expected output: "ok"

# 6. Restart system
docker-compose start slob-bot

# 7. Monitor recovery
./scripts/monitor.sh --watch
```

**Post-Incident**:
- Document what caused corruption
- Review backup frequency (increase if needed)
- Check disk health: `sudo smartctl -a /dev/sda`

**Prevention**:
- Enable WAL mode (already enabled)
- Daily backups (already configured)
- Monitor disk space weekly

---

### P0-2: System Crash with Open Positions

**Symptoms**:
- System stopped unexpectedly
- Open positions in IB TWS
- No record in database

**Immediate Actions**:
```bash
# 1. Check IB TWS for open positions
# Note: Symbol, quantity, entry price

# 2. MANUAL POSITION MANAGEMENT
# Option A: Close manually via IB TWS if unfavorable
# Option B: Let system recover and manage

# 3. Check crash reason
tail -100 logs/trading.log
tail -50 logs/errors.log

# 4. Attempt system restart
docker-compose restart slob-bot

# 5. Verify position reconciliation
# System should detect and reconcile positions
grep "Position reconciliation" logs/trading.log
```

**Recovery Procedure**:
```bash
# If system doesn't reconcile:

# 1. Stop system
docker-compose stop slob-bot

# 2. Manually add position to database
sqlite3 data/slob_state.db "
INSERT INTO active_setups (id, state, entry_price, sl_price, tp_price)
VALUES (
    'manual_$(date +%s)',
    'ACTIVE',
    [entry_price],
    [sl_price],
    [tp_price]
);
"

# 3. Restart system
docker-compose start slob-bot

# 4. Verify position tracked
./scripts/monitor.sh
```

**Post-Incident**:
- Identify crash cause
- Fix if code issue
- Improve crash handling if needed

---

### P0-3: Runaway Trading (Multiple Duplicate Orders)

**Symptoms**:
- Multiple orders for same setup
- Unexpected position sizes
- Idempotency protection failed

**Immediate Actions**:
```bash
# 1. STOP SYSTEM IMMEDIATELY
docker-compose stop slob-bot

# 2. CLOSE ALL POSITIONS MANUALLY VIA IB TWS
# Use flat button or close positions individually

# 3. Assess damage
sqlite3 data/slob_state.db "
SELECT id, state, entry_price
FROM active_setups
WHERE state != 'SETUP_COMPLETE';
"

# 4. Check IB TWS positions
# Verify all closed

# 5. Document incident
echo "Runaway trading incident $(date)" >> incidents.log
```

**Recovery Procedure**:
```bash
# DO NOT restart system until root cause identified

# 1. Review logs for duplicate orders
grep "duplicate" logs/trading.log
grep "orderRef" logs/trading.log

# 2. Check idempotency logic
grep "_check_duplicate_order" logs/trading.log

# 3. If code issue found, fix immediately

# 4. Run idempotency tests
pytest tests/live/test_order_executor_idempotency.py -v

# 5. Only restart after fix verified
docker-compose start slob-bot

# 6. Monitor closely for 1 hour
./scripts/monitor.sh --watch
```

**Post-Incident**:
- Full code review of order placement
- Add additional idempotency checks
- Increase monitoring frequency

**Prevention**:
- Regular idempotency tests
- Monitor orderRef generation
- Alert on duplicate order attempts

---

## 🟠 High Priority Incidents (P1)

### P1-1: IB Gateway Connection Lost

**Symptoms**:
- `IB connection lost` in logs
- Dashboard shows disconnected
- No real-time data

**Immediate Actions**:
```bash
# 1. Check IB Gateway status
lsof -i :4002

# 2. Check system logs
tail -f logs/trading.log | grep "IB"

# 3. System should auto-reconnect
# Wait 2-5 minutes for exponential backoff
```

**If Auto-Reconnect Fails**:
```bash
# 1. Restart IB Gateway manually
# (Process depends on IB Gateway setup)

# 2. If still not connecting, restart system
docker-compose restart slob-bot

# 3. Monitor reconnection
tail -f logs/trading.log | grep "IB.*connect"

# 4. Verify connection successful
python scripts/test_ib_connection.py
```

**Post-Incident**:
- Document disconnect duration
- Check if during market hours
- Review IB Gateway logs
- Consider increasing timeout settings

---

### P1-2: Circuit Breaker Triggered (Max Drawdown)

**Symptoms**:
- `Circuit breaker triggered` alert
- `Trading stopped: max drawdown reached`
- Dashboard shows red circuit breaker

**Immediate Actions**:
```bash
# 1. System has automatically stopped trading
# This is by design - NO IMMEDIATE ACTION NEEDED

# 2. Access dashboard
open http://localhost:5000

# 3. Review recent trades
# Check P&L chart for drawdown cause
```

**Analysis Procedure**:
```bash
# 1. Calculate actual drawdown
sqlite3 data/slob_state.db "
SELECT
    ROUND(MIN(running_total), 2) as max_dd,
    ROUND((MIN(running_total) / 50000.0) * 100, 2) as dd_pct
FROM (
    SELECT SUM(pnl) OVER (ORDER BY entry_time) as running_total
    FROM trade_history
);
"

# 2. Review losing trades
sqlite3 data/slob_state.db "
SELECT entry_time, pnl, outcome
FROM trade_history
WHERE pnl < 0
ORDER BY entry_time DESC
LIMIT 10;
"

# 3. Analyze for patterns
# - All same direction?
# - Similar setups?
# - Market conditions?
```

**Decision: Resume or Stop**:
```bash
# Option A: Stop trading for the day
# No action needed - system will remain stopped

# Option B: Reduce position sizes and resume
nano .env
# Change: RISK_PER_TRADE=0.005  # Reduce from 0.01 to 0.005
# Change: MAX_POSITION_SIZE=2   # Reduce from 5 to 2
docker-compose restart slob-bot

# Option C: Reset circuit breaker (ONLY if drawdown was measurement error)
# Not recommended - circuit breaker is protection

# 4. Monitor closely if resumed
./scripts/monitor.sh --watch
```

**Post-Incident**:
- Document what caused drawdown
- Review strategy parameters
- Consider if backtest assumptions still valid
- Update risk management if needed

---

### P1-3: Order Rejected by IB

**Symptoms**:
- `Order rejected` alerts
- Orders not filling
- `REJECTED` status in logs

**Immediate Actions**:
```bash
# 1. Check rejection reason in logs
grep "rejected\|REJECTED" logs/trading.log | tail -10

# Common rejection reasons:
# - Insufficient margin
# - Invalid price (outside trading hours)
# - Market closed
# - Invalid contract
```

**Recovery by Reason**:

**Insufficient Margin**:
```bash
# 1. Check account balance
python scripts/test_ib_connection.py

# 2. Reduce position sizes
nano .env
# MAX_POSITION_SIZE=1  # Reduce to 1 contract
docker-compose restart slob-bot
```

**Invalid Price**:
```bash
# 1. Check if outside trading hours
date
# Market hours: 09:30-16:00 EST

# 2. If during hours, check price limits
# Review setup entry price vs current market price

# 3. May need to adjust buffer settings
```

**Market Closed**:
```bash
# 1. Verify trading hours
date

# 2. System should not trade outside hours
# If it is, check trading hours configuration
grep "trading_hours" .env

# 3. Update if needed
```

---

### P1-4: Unexpected Position Detected

**Symptoms**:
- Position in IB TWS not in database
- Position reconciliation warning
- Unknown orderRef

**Immediate Actions**:
```bash
# 1. STOP SYSTEM
docker-compose stop slob-bot

# 2. Document position
# Note: Symbol, quantity, entry price, orderRef

# 3. Check if it's a system position
grep "[orderRef]" logs/trading.log

# 4. If NOT a system position:
# CLOSE MANUALLY VIA IB TWS
# Someone else may have traded on this account
```

**Recovery Procedure**:
```bash
# If it IS a system position but not in database:

# 1. Add to database manually
sqlite3 data/slob_state.db "
INSERT INTO active_setups (id, state, entry_price, sl_price, tp_price)
VALUES ('recovery_$(date +%s)', 'ACTIVE', [entry], [sl], [tp]);
"

# 2. Restart system
docker-compose start slob-bot

# 3. Monitor position management
tail -f logs/trading.log | grep "recovery_"
```

**Post-Incident**:
- Determine how position was opened without database record
- Fix state management if needed
- Improve position reconciliation

---

## 🟡 Medium Priority Incidents (P2)

### P2-1: Dashboard Not Accessible

**Symptoms**:
- http://localhost:5000 not responding
- `Connection refused` error

**Recovery**:
```bash
# 1. Check if dashboard running
lsof -i :5000

# 2. If not running, check logs
tail -50 logs/trading.log | grep -i "dashboard\|flask"

# 3. Restart dashboard
python -m slob.monitoring.dashboard &

# 4. Verify accessible
curl http://localhost:5000

# 5. If still fails, check for errors
tail -f logs/errors.log
```

**Note**: Dashboard down does NOT affect trading. Trading continues normally.

---

### P2-2: Telegram Alerts Not Working

**Recovery**:
```bash
# 1. Test Telegram connectivity
python slob/monitoring/telegram_notifier.py

# 2. If fails, check configuration
grep "TELEGRAM" .env

# 3. Verify bot token valid
curl "https://api.telegram.org/bot[TOKEN]/getMe"

# 4. Verify chat ID correct
curl "https://api.telegram.org/bot[TOKEN]/getUpdates"

# 5. Restart system to reload configuration
docker-compose restart slob-bot
```

---

### P2-3: Email Alerts Not Sending

**Recovery**:
```bash
# 1. Test email configuration
python slob.monitoring.email_notifier.py

# 2. Check SMTP settings
grep "SMTP" .env

# 3. Test SMTP connection
python -c "
import smtplib
server = smtplib.SMTP('smtp.gmail.com', 587)
server.starttls()
server.login('[email]', '[app_password]')
print('✅ SMTP works!')
"

# 4. Check app password (Gmail)
# May need to regenerate at: https://myaccount.google.com/apppasswords

# 5. Restart system
docker-compose restart slob-bot
```

---

## 🟢 Low Priority Incidents (P3)

### P3-1: Slow Dashboard Performance

**Recovery**:
```bash
# 1. Vacuum database
sqlite3 data/slob_state.db "VACUUM;"

# 2. Check database size
ls -lh data/*.db

# 3. If >1GB, archive old data
sqlite3 data/slob_state.db "
DELETE FROM trade_history
WHERE entry_time < datetime('now', '-1 year');
"

# 4. Restart dashboard
pkill -f "python.*dashboard"
python -m slob.monitoring.dashboard &
```

---

### P3-2: Log Files Growing Too Large

**Recovery**:
```bash
# 1. Check log sizes
du -sh logs/

# 2. Manual cleanup (if >10GB)
find logs/ -name "*.log.*" -mtime +7 -delete

# 3. Verify log rotation configured
grep "setup_logging" scripts/run_paper_trading.py

# 4. Increase retention if needed
# Edit slob/monitoring/logging_config.py
# backupCount=30  # Increase or decrease
```

---

### P3-3: Backup Failures

**Recovery**:
```bash
# 1. Check disk space
df -h

# 2. Manually create backup
./scripts/backup_state.sh --verify

# 3. Check backup directory permissions
ls -ld data/backups

# 4. If S3 upload failing:
aws s3 ls s3://$AWS_S3_BUCKET
# Verify credentials and bucket access

# 5. Review backup logs
grep "backup" logs/trading.log
```

---

## 📝 Common Error Messages

### "Database is locked"
**Cause**: Multiple processes accessing SQLite
**Fix**:
```bash
# 1. Check for multiple processes
ps aux | grep "python.*slob"

# 2. Kill duplicate processes
pkill -f "python.*run_paper_trading"

# 3. Wait 10 seconds
sleep 10

# 4. Restart single instance
docker-compose up -d slob-bot
```

---

### "Connection refused - port 4002"
**Cause**: IB Gateway not running
**Fix**:
```bash
# 1. Start IB Gateway manually

# 2. Verify port open
lsof -i :4002

# 3. System should auto-connect
tail -f logs/trading.log | grep "IB.*connect"
```

---

### "Insufficient margin"
**Cause**: Account balance too low for position size
**Fix**:
```bash
# 1. Check account balance
python scripts/test_ib_connection.py

# 2. Reduce position size
nano .env
# MAX_POSITION_SIZE=1
docker-compose restart slob-bot
```

---

### "Setup invalidated"
**Cause**: Setup conditions no longer met
**Fix**:
- This is normal operation
- Setup was detected but invalidated before entry
- No action needed

---

## 📊 Post-Incident Review

### Incident Report Template

```markdown
# Incident Report

**Date**: 2025-12-26 14:30 EST
**Severity**: P1
**Duration**: 15 minutes
**Impact**: Trading stopped during incident

## Summary
[Brief description of what happened]

## Timeline
- 14:30 - Incident detected
- 14:32 - System stopped
- 14:35 - Root cause identified
- 14:40 - Fix applied
- 14:45 - System restored, monitoring

## Root Cause
[What caused the incident]

## Resolution
[How it was fixed]

## Action Items
- [ ] Task 1 to prevent recurrence
- [ ] Task 2 for monitoring
- [ ] Task 3 for documentation

## Lessons Learned
[What was learned from this incident]
```

### Review Checklist
- [ ] Incident documented
- [ ] Root cause identified
- [ ] Fix implemented
- [ ] Tests added/updated
- [ ] Monitoring improved
- [ ] Documentation updated
- [ ] Team informed (if applicable)

---

## 📞 Escalation Contacts

### Internal
- **System Owner**: [Your name]
- **Email**: [Your email]
- **Phone**: [Your phone]

### External
- **IB Support**: +1-877-442-2757 (US)
- **IB Tech Support**: https://www.interactivebrokers.com/en/support/help.php
- **Telegram Support**: @BotSupport

---

## 📚 Related Documentation

- **Operations**: [OPERATIONAL_RUNBOOK.md](OPERATIONAL_RUNBOOK.md)
- **Deployment**: [DEPLOYMENT.md](DEPLOYMENT.md)
- **Testing**: [TESTING_GUIDE.md](TESTING_GUIDE.md)
- **Main Guide**: [README.md](README.md)

---

*This guide is a living document. Update after each incident.*

---

*Last Updated: 2025-12-26*
*Version: 2.0*
*Status: Production Ready*
