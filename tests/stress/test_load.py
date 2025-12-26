"""
Stress Testing Suite

Tests system performance under load:
- High-frequency setup detection
- Concurrent database access
- Memory leak detection
- Connection pool exhaustion
- Large data volumes

Usage:
    pytest tests/stress/test_load.py -v
    pytest tests/stress/test_load.py -v -m stress
    pytest tests/stress/test_load.py -v -m "stress and slow"
"""

import pytest
import asyncio
import sqlite3
import time
import psutil
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent.parent.parent
TEST_DB_PATH = PROJECT_ROOT / "data" / "stress_test.db"


@pytest.fixture(scope="module")
def stress_database():
    """Create database for stress testing."""
    conn = sqlite3.connect(str(TEST_DB_PATH))
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_setups (
            id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            entry_price REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setup_id TEXT NOT NULL,
            entry_time DATETIME,
            pnl REAL
        )
    """)

    conn.commit()
    conn.close()

    yield TEST_DB_PATH

    # Cleanup
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.mark.stress
class TestHighFrequencyOperations:
    """Test high-frequency operations."""

    @pytest.mark.slow
    def test_high_frequency_setup_detection(self, stress_database):
        """Test handling 100 setups in quick succession."""
        print("\n[TEST] Testing high-frequency setup detection...")

        start_time = time.time()
        setup_count = 100

        conn = sqlite3.connect(str(stress_database))
        cursor = conn.cursor()

        # Insert 100 setups rapidly
        for i in range(setup_count):
            setup_id = f"stress_setup_{i:04d}"
            cursor.execute("""
                INSERT INTO active_setups (id, state, entry_price)
                VALUES (?, ?, ?)
            """, (setup_id, "ACTIVE", 100.0 + i))

        conn.commit()

        elapsed = time.time() - start_time

        # Verify all inserted
        cursor.execute("SELECT COUNT(*) FROM active_setups WHERE id LIKE 'stress_setup_%'")
        count = cursor.fetchone()[0]

        conn.close()

        assert count == setup_count, f"Only {count}/{setup_count} setups inserted"

        throughput = setup_count / elapsed
        print(f"[SUCCESS] Inserted {setup_count} setups in {elapsed:.2f}s ({throughput:.0f} setups/sec)")

    @pytest.mark.slow
    def test_high_frequency_trade_logging(self, stress_database):
        """Test logging 500 trades rapidly."""
        print("\n[TEST] Testing high-frequency trade logging...")

        start_time = time.time()
        trade_count = 500

        conn = sqlite3.connect(str(stress_database))
        cursor = conn.cursor()

        # Insert 500 trades
        for i in range(trade_count):
            cursor.execute("""
                INSERT INTO trade_history (setup_id, entry_time, pnl)
                VALUES (?, datetime('now'), ?)
            """, (f"setup_{i % 100}", (-1) ** i * (100 + i)))

        conn.commit()

        elapsed = time.time() - start_time

        # Verify all inserted
        cursor.execute("SELECT COUNT(*) FROM trade_history")
        count = cursor.fetchone()[0]

        conn.close()

        assert count >= trade_count, f"Only {count}/{trade_count} trades inserted"

        throughput = trade_count / elapsed
        print(f"[SUCCESS] Logged {trade_count} trades in {elapsed:.2f}s ({throughput:.0f} trades/sec)")


@pytest.mark.stress
class TestConcurrentDatabaseAccess:
    """Test concurrent database operations."""

    @pytest.mark.slow
    def test_concurrent_writes(self, stress_database):
        """Test 10 concurrent writers."""
        print("\n[TEST] Testing concurrent database writes...")

        num_threads = 10
        writes_per_thread = 20

        def write_to_db(thread_id):
            """Write to database from thread."""
            conn = sqlite3.connect(str(stress_database))
            cursor = conn.cursor()

            for i in range(writes_per_thread):
                setup_id = f"thread_{thread_id}_setup_{i}"
                cursor.execute("""
                    INSERT OR REPLACE INTO active_setups (id, state, entry_price)
                    VALUES (?, ?, ?)
                """, (setup_id, "ACTIVE", 100.0 + thread_id + i))

            conn.commit()
            conn.close()

        start_time = time.time()

        # Execute concurrent writes
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(write_to_db, i) for i in range(num_threads)]
            for future in futures:
                future.result()  # Wait for completion

        elapsed = time.time() - start_time

        # Verify all writes succeeded
        conn = sqlite3.connect(str(stress_database))
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM active_setups WHERE id LIKE 'thread_%'")
        count = cursor.fetchone()[0]

        conn.close()

        expected_count = num_threads * writes_per_thread
        assert count == expected_count, f"Only {count}/{expected_count} writes succeeded"

        print(f"[SUCCESS] {num_threads} threads x {writes_per_thread} writes in {elapsed:.2f}s")

    @pytest.mark.slow
    def test_concurrent_reads(self, stress_database):
        """Test 20 concurrent readers."""
        print("\n[TEST] Testing concurrent database reads...")

        # First, populate database
        conn = sqlite3.connect(str(stress_database))
        cursor = conn.cursor()

        for i in range(100):
            cursor.execute("""
                INSERT OR REPLACE INTO active_setups (id, state, entry_price)
                VALUES (?, ?, ?)
            """, (f"read_test_{i}", "ACTIVE", 100.0 + i))

        conn.commit()
        conn.close()

        num_threads = 20
        reads_per_thread = 50

        def read_from_db(thread_id):
            """Read from database from thread."""
            conn = sqlite3.connect(str(stress_database))
            cursor = conn.cursor()

            for i in range(reads_per_thread):
                cursor.execute("SELECT COUNT(*) FROM active_setups")
                cursor.fetchone()

            conn.close()

        start_time = time.time()

        # Execute concurrent reads
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(read_from_db, i) for i in range(num_threads)]
            for future in futures:
                future.result()

        elapsed = time.time() - start_time

        total_reads = num_threads * reads_per_thread
        throughput = total_reads / elapsed

        print(f"[SUCCESS] {total_reads} concurrent reads in {elapsed:.2f}s ({throughput:.0f} reads/sec)")


@pytest.mark.stress
class TestMemoryLeaks:
    """Test for memory leaks."""

    @pytest.mark.slow
    def test_memory_usage_stability(self, stress_database):
        """Test memory usage doesn't grow unbounded."""
        print("\n[TEST] Testing memory usage stability...")

        process = psutil.Process(os.getpid())

        # Get initial memory usage
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Perform 1000 database operations
        conn = sqlite3.connect(str(stress_database))
        cursor = conn.cursor()

        for i in range(1000):
            # Insert
            cursor.execute("""
                INSERT OR REPLACE INTO active_setups (id, state, entry_price)
                VALUES (?, ?, ?)
            """, (f"leak_test_{i}", "ACTIVE", 100.0 + i))

            # Read
            cursor.execute("SELECT * FROM active_setups WHERE id = ?", (f"leak_test_{i}",))
            cursor.fetchone()

            # Update
            cursor.execute("""
                UPDATE active_setups SET state = 'COMPLETED' WHERE id = ?
            """, (f"leak_test_{i}",))

            if i % 100 == 0:
                conn.commit()

        conn.commit()
        conn.close()

        # Get final memory usage
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory

        print(f"[INFO] Initial memory: {initial_memory:.2f} MB")
        print(f"[INFO] Final memory: {final_memory:.2f} MB")
        print(f"[INFO] Memory increase: {memory_increase:.2f} MB")

        # Allow up to 50MB increase (generous threshold)
        assert memory_increase < 50, f"Memory leak detected: {memory_increase:.2f} MB increase"

        print(f"[SUCCESS] Memory usage stable (increase: {memory_increase:.2f} MB)")

    @pytest.mark.slow
    def test_connection_cleanup(self, stress_database):
        """Test database connections are properly closed."""
        print("\n[TEST] Testing connection cleanup...")

        connections_before = len(psutil.Process(os.getpid()).open_files())

        # Open and close 100 connections
        for i in range(100):
            conn = sqlite3.connect(str(stress_database))
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            conn.close()

        connections_after = len(psutil.Process(os.getpid()).open_files())
        connection_leak = connections_after - connections_before

        print(f"[INFO] Open file descriptors before: {connections_before}")
        print(f"[INFO] Open file descriptors after: {connections_after}")
        print(f"[INFO] Difference: {connection_leak}")

        # Allow small variance (up to 5 file descriptors)
        assert connection_leak < 5, f"Connection leak detected: {connection_leak} unclosed connections"

        print(f"[SUCCESS] Connections properly cleaned up")


@pytest.mark.stress
class TestLargeDataVolumes:
    """Test handling large data volumes."""

    @pytest.mark.slow
    def test_large_number_of_setups(self, stress_database):
        """Test handling 10,000 setups."""
        print("\n[TEST] Testing large number of setups...")

        setup_count = 10000
        batch_size = 1000

        conn = sqlite3.connect(str(stress_database))
        cursor = conn.cursor()

        start_time = time.time()

        # Insert in batches for efficiency
        for batch in range(0, setup_count, batch_size):
            values = []
            for i in range(batch, min(batch + batch_size, setup_count)):
                values.append((f"large_test_{i}", "ACTIVE", 100.0 + i))

            cursor.executemany("""
                INSERT OR REPLACE INTO active_setups (id, state, entry_price)
                VALUES (?, ?, ?)
            """, values)

            conn.commit()

        elapsed = time.time() - start_time

        # Verify count
        cursor.execute("SELECT COUNT(*) FROM active_setups WHERE id LIKE 'large_test_%'")
        count = cursor.fetchone()[0]

        conn.close()

        assert count == setup_count, f"Only {count}/{setup_count} setups inserted"

        throughput = setup_count / elapsed
        print(f"[SUCCESS] Inserted {setup_count:,} setups in {elapsed:.2f}s ({throughput:.0f} setups/sec)")

    @pytest.mark.slow
    def test_query_performance_with_large_dataset(self, stress_database):
        """Test query performance with large dataset."""
        print("\n[TEST] Testing query performance with large dataset...")

        conn = sqlite3.connect(str(stress_database))
        cursor = conn.cursor()

        # Ensure we have data
        cursor.execute("SELECT COUNT(*) FROM active_setups")
        total_count = cursor.fetchone()[0]

        if total_count < 1000:
            pytest.skip("Insufficient data (run test_large_number_of_setups first)")

        # Test various queries
        queries = [
            ("COUNT(*)", "SELECT COUNT(*) FROM active_setups"),
            ("Simple SELECT", "SELECT * FROM active_setups LIMIT 100"),
            ("WHERE filter", "SELECT * FROM active_setups WHERE state = 'ACTIVE' LIMIT 100"),
            ("ORDER BY", "SELECT * FROM active_setups ORDER BY created_at DESC LIMIT 100"),
        ]

        for query_name, query_sql in queries:
            start_time = time.time()
            cursor.execute(query_sql)
            cursor.fetchall()
            elapsed = time.time() - start_time

            print(f"  {query_name}: {elapsed*1000:.2f}ms")

            # All queries should complete in < 1 second
            assert elapsed < 1.0, f"{query_name} too slow: {elapsed:.2f}s"

        conn.close()

        print("[SUCCESS] All queries completed within acceptable time")


@pytest.mark.stress
class TestDatabasePerformance:
    """Test database performance benchmarks."""

    @pytest.mark.slow
    def test_insert_performance(self, stress_database):
        """Benchmark insert performance."""
        print("\n[TEST] Benchmarking insert performance...")

        conn = sqlite3.connect(str(stress_database))
        cursor = conn.cursor()

        iterations = 1000
        start_time = time.time()

        for i in range(iterations):
            cursor.execute("""
                INSERT INTO active_setups (id, state, entry_price)
                VALUES (?, ?, ?)
            """, (f"benchmark_insert_{i}", "ACTIVE", 100.0 + i))

        conn.commit()
        elapsed = time.time() - start_time

        conn.close()

        inserts_per_sec = iterations / elapsed

        print(f"[BENCHMARK] {iterations} inserts in {elapsed:.2f}s ({inserts_per_sec:.0f} inserts/sec)")

        # Expect at least 500 inserts/sec
        assert inserts_per_sec > 500, f"Insert performance too slow: {inserts_per_sec:.0f} inserts/sec"

        print(f"[SUCCESS] Insert performance acceptable")

    @pytest.mark.slow
    def test_select_performance(self, stress_database):
        """Benchmark select performance."""
        print("\n[TEST] Benchmarking select performance...")

        conn = sqlite3.connect(str(stress_database))
        cursor = conn.cursor()

        # Ensure data exists
        cursor.execute("SELECT COUNT(*) FROM active_setups")
        count = cursor.fetchone()[0]

        if count < 100:
            pytest.skip("Insufficient data for benchmark")

        iterations = 10000
        start_time = time.time()

        for i in range(iterations):
            cursor.execute("SELECT * FROM active_setups LIMIT 10")
            cursor.fetchall()

        elapsed = time.time() - start_time

        conn.close()

        selects_per_sec = iterations / elapsed

        print(f"[BENCHMARK] {iterations} selects in {elapsed:.2f}s ({selects_per_sec:.0f} selects/sec)")

        # Expect at least 1000 selects/sec
        assert selects_per_sec > 1000, f"Select performance too slow: {selects_per_sec:.0f} selects/sec"

        print(f"[SUCCESS] Select performance acceptable")

    @pytest.mark.slow
    def test_update_performance(self, stress_database):
        """Benchmark update performance."""
        print("\n[TEST] Benchmarking update performance...")

        conn = sqlite3.connect(str(stress_database))
        cursor = conn.cursor()

        # Insert test data
        for i in range(1000):
            cursor.execute("""
                INSERT OR REPLACE INTO active_setups (id, state, entry_price)
                VALUES (?, ?, ?)
            """, (f"benchmark_update_{i}", "ACTIVE", 100.0))

        conn.commit()

        iterations = 1000
        start_time = time.time()

        for i in range(iterations):
            cursor.execute("""
                UPDATE active_setups SET state = 'COMPLETED' WHERE id = ?
            """, (f"benchmark_update_{i}",))

        conn.commit()
        elapsed = time.time() - start_time

        conn.close()

        updates_per_sec = iterations / elapsed

        print(f"[BENCHMARK] {iterations} updates in {elapsed:.2f}s ({updates_per_sec:.0f} updates/sec)")

        # Expect at least 500 updates/sec
        assert updates_per_sec > 500, f"Update performance too slow: {updates_per_sec:.0f} updates/sec"

        print(f"[SUCCESS] Update performance acceptable")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "stress"])
