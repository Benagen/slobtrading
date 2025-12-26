#!/usr/bin/env python3
"""
Database Migration Script

Creates/updates database schema for SLOB trading system.

Usage:
    python scripts/migrate_database.py [DB_PATH]

Default DB_PATH: data/slob_state.db
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime


def migrate_database(db_path: str):
    """Run database migrations."""

    print(f"🔄 Starting database migrations for: {db_path}")
    print(f"   Timestamp: {datetime.now().isoformat()}")
    print()

    # Create directory if it doesn't exist
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check current version
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                description TEXT
            )
        """)
        conn.commit()

        cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        result = cursor.fetchone()
        current_version = result[0] if result else 0
    except sqlite3.OperationalError:
        current_version = 0

    print(f"📊 Current database version: {current_version}")

    # ─────────────────────────────────────────────────────────────────
    # Migration v1: Initial schema
    # ─────────────────────────────────────────────────────────────────
    if current_version < 1:
        print("\n🔨 Running migration v1: Initial schema")

        # Table: active_setups (formerly "setups")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_setups (
                id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                symbol TEXT NOT NULL DEFAULT 'NQ',

                created_at TIMESTAMP NOT NULL,
                last_updated TIMESTAMP NOT NULL,

                -- LSE (Liquidity Sweep Entry)
                lse_high REAL,
                lse_low REAL,
                lse_close_time TIMESTAMP,

                -- LIQ #1
                liq1_detected BOOLEAN,
                liq1_time TIMESTAMP,
                liq1_price REAL,
                liq1_confidence REAL,

                -- Consolidation
                consol_high REAL,
                consol_low REAL,
                consol_range REAL,
                consol_quality_score REAL,
                consol_confirmed BOOLEAN,
                consol_confirmed_time TIMESTAMP,

                -- No-Wick Candle
                nowick_found BOOLEAN,
                nowick_time TIMESTAMP,
                nowick_high REAL,
                nowick_low REAL,
                nowick_wick_ratio REAL,

                -- LIQ #2
                liq2_detected BOOLEAN,
                liq2_time TIMESTAMP,
                liq2_price REAL,

                -- Entry
                entry_triggered BOOLEAN,
                entry_trigger_time TIMESTAMP,
                entry_price REAL,

                -- SL/TP
                sl_price REAL,
                tp_price REAL,
                risk_reward_ratio REAL,

                -- Invalidation
                invalidation_reason TEXT,
                invalidation_time TIMESTAMP,

                -- Metadata
                candles_processed INTEGER,
                raw_data TEXT  -- Full JSON for recovery
            )
        """)
        print("   ✅ Created table: active_setups")

        # Table: trades (executed trades)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setup_id TEXT NOT NULL,
                symbol TEXT NOT NULL,

                entry_time TIMESTAMP NOT NULL,
                entry_price REAL NOT NULL,
                position_size INTEGER NOT NULL,

                exit_time TIMESTAMP,
                exit_price REAL,
                exit_reason TEXT,  -- 'TP', 'SL', 'MANUAL', 'EOD', 'EXTERNAL_CLOSE'

                pnl REAL,
                pnl_percent REAL,

                sl_price REAL,
                tp_price REAL,

                result TEXT,  -- 'WIN', 'LOSS', 'BREAKEVEN', 'OPEN', 'CLOSED'

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (setup_id) REFERENCES active_setups(id)
            )
        """)
        print("   ✅ Created table: trades")

        # Table: session_state (daily trading session metadata)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_state (
                date DATE PRIMARY KEY,
                started_at TIMESTAMP,
                ended_at TIMESTAMP,

                starting_capital REAL,
                ending_capital REAL,

                setups_detected INTEGER DEFAULT 0,
                trades_executed INTEGER DEFAULT 0,
                trades_won INTEGER DEFAULT 0,
                trades_lost INTEGER DEFAULT 0,

                daily_pnl REAL DEFAULT 0.0,

                notes TEXT
            )
        """)
        print("   ✅ Created table: session_state")

        # Table: shadow_predictions (ML shadow mode predictions)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shadow_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setup_id TEXT NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                ml_probability REAL NOT NULL,
                ml_decision TEXT NOT NULL,
                ml_threshold REAL NOT NULL,
                rule_decision TEXT NOT NULL,
                agreement BOOLEAN NOT NULL,
                features TEXT,
                model_version TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                -- Link to actual trade outcome (filled later)
                actual_outcome TEXT,
                actual_pnl REAL,

                FOREIGN KEY (setup_id) REFERENCES active_setups(id)
            )
        """)
        print("   ✅ Created table: shadow_predictions")

        # Indexes for performance
        print("\n🔍 Creating indexes...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_setups_state ON active_setups(state)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_setups_created ON active_setups(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_setup ON trades(setup_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_result ON trades(result)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_date ON session_state(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_shadow_timestamp ON shadow_predictions(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_shadow_agreement ON shadow_predictions(agreement)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_shadow_setup ON shadow_predictions(setup_id)")
        print("   ✅ Created 9 indexes")

        # Mark migration complete
        cursor.execute("""
            INSERT INTO schema_version (version, description)
            VALUES (1, 'Initial schema with active_setups, trades, session_state, shadow_predictions')
        """)

        conn.commit()
        print("\n   ✅ Migration v1 complete")

    # ─────────────────────────────────────────────────────────────────
    # Future migrations go here
    # ─────────────────────────────────────────────────────────────────

    # Example migration v2:
    # if current_version < 2:
    #     print("\n🔨 Running migration v2: Add new column")
    #     cursor.execute("ALTER TABLE trades ADD COLUMN commission REAL DEFAULT 0.0")
    #     cursor.execute("""
    #         INSERT INTO schema_version (version, description)
    #         VALUES (2, 'Added commission column to trades')
    #     """)
    #     conn.commit()
    #     print("   ✅ Migration v2 complete")

    # Get final version
    cursor.execute("SELECT version, description FROM schema_version ORDER BY version DESC LIMIT 1")
    result = cursor.fetchone()
    final_version = result[0] if result else 0
    description = result[1] if result and len(result) > 1 else ""

    conn.close()

    print()
    print("=" * 70)
    print(f"✅ All migrations complete!")
    print(f"   Database: {db_path}")
    print(f"   Final version: {final_version}")
    if description:
        print(f"   Latest: {description}")
    print("=" * 70)

    return final_version


if __name__ == "__main__":
    # Parse command line arguments
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = "data/slob_state.db"

    try:
        final_version = migrate_database(db_path)
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
