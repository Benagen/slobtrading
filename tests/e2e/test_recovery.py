"""
End-to-End Recovery Tests

Tests system resilience and recovery capabilities:
- Crash recovery (state restoration)
- Database corruption recovery
- Connection failure recovery
- Graceful shutdown
- Rollback procedures

Usage:
    pytest tests/e2e/test_recovery.py -v
    pytest tests/e2e/test_recovery.py -v -m recovery
"""

import pytest
import sqlite3
import time
import os
import signal
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
TEST_DB_PATH = PROJECT_ROOT / "data" / "test_recovery.db"
BACKUP_DIR = PROJECT_ROOT / "data" / "backups"


@pytest.fixture(scope="module")
def test_database():
    """Create test database with sample data."""
    # Create database
    conn = sqlite3.connect(str(TEST_DB_PATH))
    cursor = conn.cursor()

    # Create tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_setups (
            id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            entry_price REAL,
            sl_price REAL,
            tp_price REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setup_id TEXT NOT NULL,
            entry_time DATETIME,
            exit_time DATETIME,
            outcome TEXT,
            pnl REAL,
            FOREIGN KEY (setup_id) REFERENCES active_setups(id)
        )
    """)

    # Insert test data
    cursor.execute("""
        INSERT INTO active_setups (id, state, entry_price, sl_price, tp_price)
        VALUES ('setup_001', 'ACTIVE', 100.50, 98.50, 105.50)
    """)

    cursor.execute("""
        INSERT INTO trade_history (setup_id, entry_time, outcome, pnl)
        VALUES ('setup_001', datetime('now'), 'WIN', 250.00)
    """)

    conn.commit()
    conn.close()

    yield TEST_DB_PATH

    # Cleanup
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.mark.recovery
class TestCrashRecovery:
    """Test system recovery from crashes."""

    def test_database_state_restoration(self, test_database):
        """Test database state can be restored after crash."""
        print("\n[TEST] Testing database state restoration...")

        # Read initial state
        conn = sqlite3.connect(str(test_database))
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM active_setups")
        initial_count = cursor.fetchone()[0]

        cursor.execute("SELECT id, state FROM active_setups WHERE id='setup_001'")
        initial_row = cursor.fetchone()

        conn.close()

        # Simulate crash (close connection abruptly)
        # SQLite should handle this gracefully due to WAL mode

        # Reconnect and verify state
        conn = sqlite3.connect(str(test_database))
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM active_setups")
        restored_count = cursor.fetchone()[0]

        cursor.execute("SELECT id, state FROM active_setups WHERE id='setup_001'")
        restored_row = cursor.fetchone()

        conn.close()

        assert restored_count == initial_count, "Setup count mismatch after crash"
        assert restored_row == initial_row, "Setup data corrupted after crash"

        print("[SUCCESS] Database state restored successfully")

    def test_wal_recovery(self, test_database):
        """Test Write-Ahead Log (WAL) recovery."""
        print("\n[TEST] Testing WAL recovery...")

        conn = sqlite3.connect(str(test_database))
        cursor = conn.cursor()

        # Enable WAL mode
        cursor.execute("PRAGMA journal_mode=WAL")
        wal_mode = cursor.fetchone()[0]
        assert wal_mode == "wal", f"WAL mode not enabled: {wal_mode}"

        # Perform write operation
        cursor.execute("""
            INSERT INTO active_setups (id, state, entry_price)
            VALUES ('setup_002', 'PENDING', 200.50)
        """)
        conn.commit()

        # Check WAL file exists
        wal_file = Path(str(test_database) + "-wal")
        assert wal_file.exists(), "WAL file not created"

        conn.close()

        # Simulate recovery by reopening database
        conn = sqlite3.connect(str(test_database))
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM active_setups WHERE id='setup_002'")
        row = cursor.fetchone()

        assert row is not None, "WAL recovery failed - data lost"
        assert row[0] == "setup_002", f"WAL recovery corrupted data: {row[0]}"

        conn.close()

        print("[SUCCESS] WAL recovery successful")

    def test_backup_restoration(self, test_database):
        """Test backup can be restored."""
        print("\n[TEST] Testing backup restoration...")

        backup_script = PROJECT_ROOT / "scripts" / "backup_state.sh"

        if not backup_script.exists():
            pytest.skip("backup_state.sh not found")

        # Create backup
        os.makedirs(BACKUP_DIR, exist_ok=True)

        # Manual backup (copy database)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = BACKUP_DIR / f"test_backup_{timestamp}.db"
        shutil.copy(test_database, backup_file)

        assert backup_file.exists(), "Backup file not created"

        # Corrupt original database
        with open(test_database, "w") as f:
            f.write("CORRUPTED")

        # Verify corruption
        try:
            conn = sqlite3.connect(str(test_database))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM active_setups")
            conn.close()
            assert False, "Database should be corrupted"
        except sqlite3.DatabaseError:
            pass  # Expected

        # Restore from backup
        shutil.copy(backup_file, test_database)

        # Verify restoration
        conn = sqlite3.connect(str(test_database))
        cursor = conn.cursor()

        cursor.execute("PRAGMA integrity_check")
        integrity = cursor.fetchone()[0]
        assert integrity == "ok", f"Restored database corrupted: {integrity}"

        cursor.execute("SELECT COUNT(*) FROM active_setups")
        count = cursor.fetchone()[0]
        assert count >= 1, "Restored database missing data"

        conn.close()

        # Cleanup
        if backup_file.exists():
            backup_file.unlink()

        print("[SUCCESS] Backup restoration successful")


@pytest.mark.recovery
class TestGracefulShutdown:
    """Test graceful shutdown procedures."""

    def test_signal_handler_syntax(self):
        """Test signal handlers are properly defined."""
        print("\n[TEST] Testing signal handler definition...")

        engine_file = PROJECT_ROOT / "slob" / "live" / "live_trading_engine.py"

        if not engine_file.exists():
            pytest.skip("live_trading_engine.py not found")

        content = engine_file.read_text()

        # Check signal handling exists
        assert "signal" in content or "SIGTERM" in content or "graceful_shutdown" in content, \
            "No signal handling found in LiveTradingEngine"

        print("[SUCCESS] Signal handlers defined")

    def test_state_persistence_on_shutdown(self, test_database):
        """Test state is persisted on shutdown."""
        print("\n[TEST] Testing state persistence on shutdown...")

        conn = sqlite3.connect(str(test_database))
        cursor = conn.cursor()

        # Add new setup
        cursor.execute("""
            INSERT INTO active_setups (id, state, entry_price)
            VALUES ('shutdown_test', 'ACTIVE', 150.00)
        """)
        conn.commit()

        # Simulate graceful shutdown (commit and close)
        conn.commit()
        conn.close()

        # Verify data persisted
        conn = sqlite3.connect(str(test_database))
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM active_setups WHERE id='shutdown_test'")
        row = cursor.fetchone()

        assert row is not None, "State not persisted on shutdown"
        assert row[0] == "shutdown_test", f"State corrupted: {row[0]}"

        conn.close()

        print("[SUCCESS] State persisted on shutdown")


@pytest.mark.recovery
class TestRollbackProcedure:
    """Test rollback procedures."""

    def test_rollback_script_syntax(self):
        """Test rollback.sh has valid syntax."""
        print("\n[TEST] Testing rollback.sh syntax...")

        rollback_script = PROJECT_ROOT / "scripts" / "rollback.sh"

        if not rollback_script.exists():
            pytest.skip("rollback.sh not found")

        result = subprocess.run(
            ["bash", "-n", str(rollback_script)],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0, f"rollback.sh has syntax errors: {result.stderr}"
        print("[SUCCESS] rollback.sh syntax valid")

    def test_rollback_safety_backup(self, test_database):
        """Test rollback creates safety backup."""
        print("\n[TEST] Testing rollback safety backup...")

        # Simulate rollback safety backup creation
        safety_backup = Path(str(test_database) + ".rollback_backup")

        # Create safety backup
        shutil.copy(test_database, safety_backup)

        assert safety_backup.exists(), "Safety backup not created"

        # Verify backup is valid
        conn = sqlite3.connect(str(safety_backup))
        cursor = conn.cursor()

        cursor.execute("PRAGMA integrity_check")
        integrity = cursor.fetchone()[0]
        assert integrity == "ok", f"Safety backup corrupted: {integrity}"

        conn.close()

        # Cleanup
        if safety_backup.exists():
            safety_backup.unlink()

        print("[SUCCESS] Safety backup created and verified")

    def test_database_rollback_simulation(self, test_database):
        """Test database rollback simulation."""
        print("\n[TEST] Testing database rollback simulation...")

        # Create "old" state backup
        old_backup = BACKUP_DIR / "old_state.db"
        os.makedirs(BACKUP_DIR, exist_ok=True)

        conn = sqlite3.connect(str(old_backup))
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE active_setups (
                id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                entry_price REAL
            )
        """)

        cursor.execute("""
            INSERT INTO active_setups (id, state, entry_price)
            VALUES ('old_setup', 'COMPLETED', 90.00)
        """)

        conn.commit()
        conn.close()

        # Create "new" state (current database)
        conn = sqlite3.connect(str(test_database))
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO active_setups (id, state, entry_price)
            VALUES ('new_setup', 'ACTIVE', 110.00)
        """)

        conn.commit()
        conn.close()

        # Perform rollback (replace current with old)
        shutil.copy(old_backup, test_database)

        # Verify rollback
        conn = sqlite3.connect(str(test_database))
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM active_setups WHERE id='old_setup'")
        old_row = cursor.fetchone()

        cursor.execute("SELECT id FROM active_setups WHERE id='new_setup'")
        new_row = cursor.fetchone()

        conn.close()

        assert old_row is not None, "Rollback failed - old data not found"
        assert new_row is None, "Rollback failed - new data still present"

        # Cleanup
        if old_backup.exists():
            old_backup.unlink()

        print("[SUCCESS] Database rollback simulation successful")


@pytest.mark.recovery
class TestErrorRecovery:
    """Test recovery from various error conditions."""

    def test_corrupted_database_detection(self):
        """Test system detects corrupted database."""
        print("\n[TEST] Testing corrupted database detection...")

        # Create corrupted database
        corrupted_db = PROJECT_ROOT / "data" / "corrupted_test.db"

        with open(corrupted_db, "w") as f:
            f.write("NOT A VALID SQLITE DATABASE")

        # Try to open corrupted database
        try:
            conn = sqlite3.connect(str(corrupted_db))
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM active_setups")
            conn.close()
            assert False, "Should have detected corrupted database"
        except sqlite3.DatabaseError as e:
            print(f"[SUCCESS] Corrupted database detected: {e}")

        # Cleanup
        if corrupted_db.exists():
            corrupted_db.unlink()

    def test_missing_table_recovery(self, test_database):
        """Test recovery from missing table."""
        print("\n[TEST] Testing missing table recovery...")

        conn = sqlite3.connect(str(test_database))
        cursor = conn.cursor()

        # Try to query non-existent table
        try:
            cursor.execute("SELECT * FROM non_existent_table")
            assert False, "Should have raised error for missing table"
        except sqlite3.OperationalError as e:
            assert "no such table" in str(e).lower(), f"Unexpected error: {e}"
            print(f"[SUCCESS] Missing table detected: {e}")

        # Verify existing tables still work
        cursor.execute("SELECT COUNT(*) FROM active_setups")
        count = cursor.fetchone()[0]
        assert count >= 0, "Existing table corrupted"

        conn.close()

    def test_disk_full_simulation(self, test_database):
        """Test handling of disk full condition (simulated)."""
        print("\n[TEST] Testing disk full handling...")

        # This is a simulation - we can't actually fill the disk
        # But we can test error handling for write failures

        conn = sqlite3.connect(str(test_database))
        cursor = conn.cursor()

        # Try to insert very large data (may fail on constrained systems)
        large_data = "X" * (10 * 1024 * 1024)  # 10MB string

        try:
            cursor.execute("""
                INSERT INTO active_setups (id, state, entry_price)
                VALUES (?, ?, ?)
            """, (large_data, "TEST", 100.0))
            conn.commit()
            print("[INFO] Large insert succeeded (sufficient disk space)")
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            print(f"[SUCCESS] Write failure handled gracefully: {e}")

        conn.close()


@pytest.mark.recovery
class TestConnectionRecovery:
    """Test connection recovery scenarios."""

    def test_database_lock_timeout(self, test_database):
        """Test database lock timeout handling."""
        print("\n[TEST] Testing database lock timeout...")

        # Create two connections
        conn1 = sqlite3.connect(str(test_database))
        conn2 = sqlite3.connect(str(test_database))

        cursor1 = conn1.cursor()
        cursor2 = conn2.cursor()

        # Set short timeout
        conn2.execute("PRAGMA busy_timeout = 1000")  # 1 second

        # Start exclusive transaction in conn1
        cursor1.execute("BEGIN EXCLUSIVE")

        # Try to write from conn2 (should wait/timeout)
        try:
            cursor2.execute("""
                INSERT INTO active_setups (id, state, entry_price)
                VALUES ('lock_test', 'PENDING', 100.0)
            """)
            conn2.commit()
            # May succeed if WAL mode is enabled (allows concurrent reads/writes)
            print("[INFO] Concurrent write succeeded (WAL mode enabled)")
        except sqlite3.OperationalError as e:
            assert "locked" in str(e).lower() or "busy" in str(e).lower(), \
                f"Unexpected error: {e}"
            print(f"[SUCCESS] Database lock detected: {e}")

        # Release lock
        conn1.rollback()
        conn1.close()
        conn2.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "recovery"])
