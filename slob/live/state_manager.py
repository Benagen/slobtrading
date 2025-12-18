"""
State Manager - Dual Storage System

Manages persistent state for live trading using:
- Redis: Hot storage for active setups and positions (fast in-memory)
- SQLite: Cold storage for historical trades and audit trail (durable)

Key features:
- Crash recovery (restore state from Redis/SQLite on startup)
- Transactional integrity
- Automatic state persistence
- Daily backups
"""

import json
import sqlite3
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import asdict

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logging.warning("redis not installed - using in-memory fallback")

from slob.live.setup_state import SetupCandidate, SetupState, InvalidationReason


logger = logging.getLogger(__name__)


class StateManagerConfig:
    """Configuration for StateManager."""

    def __init__(
        self,
        redis_host: str = 'localhost',
        redis_port: int = 6379,
        redis_db: int = 0,
        redis_password: Optional[str] = None,
        sqlite_path: str = 'data/slob_state.db',
        backup_dir: str = 'data/backups',
        enable_redis: bool = True,
    ):
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.redis_password = redis_password
        self.sqlite_path = sqlite_path
        self.backup_dir = backup_dir
        self.enable_redis = enable_redis and REDIS_AVAILABLE


class StateManager:
    """
    Manages persistent state for live trading system.

    Architecture:
    - Redis: Active setups, open positions, session state (hot, fast)
    - SQLite: Historical trades, completed setups, audit log (cold, durable)

    Usage:
        manager = StateManager(config)
        await manager.initialize()

        # Save active setup
        await manager.save_setup(candidate)

        # Load on startup
        active_setups = await manager.load_active_setups()

        # Persist completed trade
        await manager.persist_trade(trade_data)
    """

    def __init__(self, config: StateManagerConfig):
        self.config = config
        self.redis_client: Optional[redis.Redis] = None
        self.sqlite_conn: Optional[sqlite3.Connection] = None

        # In-memory fallback if Redis unavailable
        self._memory_store: Dict[str, str] = {}

    async def initialize(self):
        """
        Initialize storage connections and create schemas.

        Steps:
        1. Connect to Redis (if enabled)
        2. Create SQLite database and tables
        3. Create backup directory
        4. Verify connectivity
        """
        logger.info("Initializing StateManager...")

        # Redis connection
        if self.config.enable_redis:
            try:
                self.redis_client = redis.Redis(
                    host=self.config.redis_host,
                    port=self.config.redis_port,
                    db=self.config.redis_db,
                    password=self.config.redis_password,
                    decode_responses=True
                )
                await self.redis_client.ping()
                logger.info(f"✅ Redis connected: {self.config.redis_host}:{self.config.redis_port}")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}. Using in-memory fallback.")
                self.redis_client = None
        else:
            logger.info("Redis disabled - using in-memory fallback")

        # SQLite connection
        self._init_sqlite()

        # Create backup directory
        Path(self.config.backup_dir).mkdir(parents=True, exist_ok=True)

        logger.info("✅ StateManager initialized")

    def _init_sqlite(self):
        """Create SQLite database and schema."""
        # Ensure parent directory exists
        Path(self.config.sqlite_path).parent.mkdir(parents=True, exist_ok=True)

        self.sqlite_conn = sqlite3.connect(
            self.config.sqlite_path,
            check_same_thread=False  # Allow async usage
        )
        self.sqlite_conn.row_factory = sqlite3.Row  # Return rows as dicts

        cursor = self.sqlite_conn.cursor()

        # Table: setups (all detected setups, completed or invalidated)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS setups (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                last_updated TIMESTAMP NOT NULL,

                -- LSE session
                lse_high REAL,
                lse_low REAL,
                lse_close_time TIMESTAMP,

                -- LIQ #1
                liq1_detected BOOLEAN,
                liq1_time TIMESTAMP,
                liq1_price REAL,
                liq1_confidence REAL,

                -- Consolidation
                consol_candles_count INTEGER,
                consol_high REAL,
                consol_low REAL,
                consol_range REAL,
                consol_quality_score REAL,
                consol_confirmed BOOLEAN,
                consol_confirmed_time TIMESTAMP,

                -- No-wick
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
                exit_reason TEXT,  -- 'TP', 'SL', 'MANUAL', 'EOD'

                pnl REAL,
                pnl_percent REAL,

                sl_price REAL,
                tp_price REAL,

                result TEXT,  -- 'WIN', 'LOSS', 'BREAKEVEN', 'OPEN'

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (setup_id) REFERENCES setups(id)
            )
        """)

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

        # Indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_setups_state ON setups(state)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_setups_created ON setups(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_setup ON trades(setup_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_date ON session_state(date)")

        self.sqlite_conn.commit()
        logger.info(f"✅ SQLite initialized: {self.config.sqlite_path}")

    # ─────────────────────────────────────────────────────────────────
    # SETUP STATE MANAGEMENT (Redis + SQLite)
    # ─────────────────────────────────────────────────────────────────

    async def save_setup(self, candidate: SetupCandidate):
        """
        Save setup candidate to both Redis (hot) and SQLite (cold).

        Redis key: setup:active:{setup_id}
        SQLite: INSERT OR REPLACE into setups table

        Args:
            candidate: SetupCandidate to persist
        """
        setup_data = candidate.to_dict()
        setup_json = json.dumps(setup_data)

        # Redis: Active setup (if still in progress)
        if candidate.is_valid() and not candidate.is_complete():
            await self._redis_set(f"setup:active:{candidate.id}", setup_json)
            logger.debug(f"Saved active setup to Redis: {candidate.id[:8]}")
        else:
            # Remove from active if completed/invalidated
            await self._redis_delete(f"setup:active:{candidate.id}")

        # SQLite: Persistent storage (all setups)
        self._sqlite_save_setup(setup_data, setup_json)
        logger.debug(f"Saved setup to SQLite: {candidate.id[:8]} (state: {candidate.state.name})")

    def _sqlite_save_setup(self, setup_data: Dict, raw_json: str):
        """Save setup to SQLite."""
        cursor = self.sqlite_conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO setups (
                id, symbol, state, created_at, last_updated,
                lse_high, lse_low, lse_close_time,
                liq1_detected, liq1_time, liq1_price, liq1_confidence,
                consol_candles_count, consol_high, consol_low, consol_range,
                consol_quality_score, consol_confirmed, consol_confirmed_time,
                nowick_found, nowick_time, nowick_high, nowick_low, nowick_wick_ratio,
                liq2_detected, liq2_time, liq2_price,
                entry_triggered, entry_trigger_time, entry_price,
                sl_price, tp_price, risk_reward_ratio,
                invalidation_reason, invalidation_time,
                candles_processed, raw_data
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?
            )
        """, (
            setup_data['id'],
            setup_data['symbol'],
            setup_data['state'],
            setup_data['created_at'],
            setup_data['last_updated'],
            setup_data['lse_high'],
            setup_data['lse_low'],
            setup_data['lse_close_time'],
            setup_data['liq1_detected'],
            setup_data['liq1_time'],
            setup_data['liq1_price'],
            setup_data['liq1_confidence'],
            setup_data['consol_candles_count'],
            setup_data['consol_high'],
            setup_data['consol_low'],
            setup_data['consol_range'],
            setup_data['consol_quality_score'],
            setup_data['consol_confirmed'],
            setup_data['consol_confirmed_time'],
            setup_data['nowick_found'],
            setup_data['nowick_time'],
            setup_data['nowick_high'],
            setup_data['nowick_low'],
            setup_data['nowick_wick_ratio'],
            setup_data['liq2_detected'],
            setup_data['liq2_time'],
            setup_data['liq2_price'],
            setup_data['entry_triggered'],
            setup_data['entry_trigger_time'],
            setup_data['entry_price'],
            setup_data['sl_price'],
            setup_data['tp_price'],
            setup_data['risk_reward_ratio'],
            setup_data['invalidation_reason'],
            setup_data['invalidation_time'],
            setup_data['candles_processed'],
            raw_json
        ))

        self.sqlite_conn.commit()

    async def load_active_setups(self) -> List[SetupCandidate]:
        """
        Load all active setup candidates from Redis (or SQLite if Redis unavailable).

        Called on system startup to recover in-progress setups.

        Returns:
            List of SetupCandidate objects
        """
        active_setups = []

        # Try Redis first
        if self.redis_client:
            pattern = "setup:active:*"
            keys = await self._redis_keys(pattern)

            logger.info(f"Loading {len(keys)} active setups from Redis...")

            for key in keys:
                setup_json = await self._redis_get(key)
                if setup_json:
                    try:
                        setup_data = json.loads(setup_json)
                        candidate = self._deserialize_setup(setup_data)
                        active_setups.append(candidate)
                        logger.debug(f"Loaded setup: {candidate.id[:8]} (state: {candidate.state.name})")
                    except Exception as e:
                        logger.error(f"Failed to deserialize setup {key}: {e}")
        else:
            # Fallback: Load active setups from SQLite
            logger.info("Redis unavailable - loading active setups from SQLite...")

            cursor = self.sqlite_conn.cursor()
            cursor.execute("""
                SELECT raw_data FROM setups
                WHERE state NOT IN ('SETUP_COMPLETE', 'INVALIDATED')
                ORDER BY created_at DESC
            """)

            rows = cursor.fetchall()
            logger.info(f"Loading {len(rows)} active setups from SQLite...")

            for row in rows:
                try:
                    setup_data = json.loads(row['raw_data'])
                    candidate = self._deserialize_setup(setup_data)
                    active_setups.append(candidate)
                    logger.debug(f"Loaded setup: {candidate.id[:8]} (state: {candidate.state.name})")
                except Exception as e:
                    logger.error(f"Failed to deserialize setup from SQLite: {e}")

        logger.info(f"✅ Loaded {len(active_setups)} active setups")
        return active_setups

    def _deserialize_setup(self, data: Dict) -> SetupCandidate:
        """
        Deserialize setup data from dict back to SetupCandidate.

        Args:
            data: Dict from to_dict()

        Returns:
            SetupCandidate instance
        """
        # Parse timestamps
        created_at = datetime.fromisoformat(data['created_at'])
        last_updated = datetime.fromisoformat(data['last_updated'])

        lse_close_time = datetime.fromisoformat(data['lse_close_time']) if data['lse_close_time'] else None
        liq1_time = datetime.fromisoformat(data['liq1_time']) if data['liq1_time'] else None
        consol_confirmed_time = datetime.fromisoformat(data['consol_confirmed_time']) if data['consol_confirmed_time'] else None
        nowick_time = datetime.fromisoformat(data['nowick_time']) if data['nowick_time'] else None
        liq2_time = datetime.fromisoformat(data['liq2_time']) if data['liq2_time'] else None
        entry_trigger_time = datetime.fromisoformat(data['entry_trigger_time']) if data['entry_trigger_time'] else None
        invalidation_time = datetime.fromisoformat(data['invalidation_time']) if data['invalidation_time'] else None

        # Parse enums
        state = SetupState[data['state']]
        invalidation_reason = InvalidationReason(data['invalidation_reason']) if data['invalidation_reason'] else None

        # Reconstruct candidate (consol_candles not stored, will be empty)
        candidate = SetupCandidate(
            id=data['id'],
            state=state,
            created_at=created_at,
            last_updated=last_updated,

            lse_high=data['lse_high'],
            lse_low=data['lse_low'],
            lse_close_time=lse_close_time,

            liq1_detected=data['liq1_detected'],
            liq1_time=liq1_time,
            liq1_price=data['liq1_price'],
            liq1_confidence=data['liq1_confidence'],

            consol_candles=[],  # Not persisted (too large)
            consol_high=data['consol_high'],
            consol_low=data['consol_low'],
            consol_range=data['consol_range'],
            consol_quality_score=data['consol_quality_score'],
            consol_confirmed=data['consol_confirmed'],
            consol_confirmed_time=consol_confirmed_time,

            nowick_found=data['nowick_found'],
            nowick_time=nowick_time,
            nowick_high=data['nowick_high'],
            nowick_low=data['nowick_low'],
            nowick_wick_ratio=data['nowick_wick_ratio'],

            liq2_detected=data['liq2_detected'],
            liq2_time=liq2_time,
            liq2_price=data['liq2_price'],

            entry_triggered=data['entry_triggered'],
            entry_trigger_time=entry_trigger_time,
            entry_price=data['entry_price'],

            sl_price=data['sl_price'],
            tp_price=data['tp_price'],
            risk_reward_ratio=data['risk_reward_ratio'],

            invalidation_reason=invalidation_reason,
            invalidation_time=invalidation_time,

            symbol=data['symbol'],
            candles_processed=data['candles_processed']
        )

        return candidate

    # ─────────────────────────────────────────────────────────────────
    # TRADE MANAGEMENT (SQLite only)
    # ─────────────────────────────────────────────────────────────────

    async def persist_trade(self, trade_data: Dict):
        """
        Save executed trade to SQLite.

        Args:
            trade_data: Dict with trade details
                - setup_id
                - symbol
                - entry_time, entry_price, position_size
                - exit_time, exit_price, exit_reason (optional)
                - pnl, pnl_percent
                - sl_price, tp_price
                - result ('WIN', 'LOSS', 'BREAKEVEN', 'OPEN')
        """
        cursor = self.sqlite_conn.cursor()

        cursor.execute("""
            INSERT INTO trades (
                setup_id, symbol,
                entry_time, entry_price, position_size,
                exit_time, exit_price, exit_reason,
                pnl, pnl_percent,
                sl_price, tp_price,
                result
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade_data['setup_id'],
            trade_data['symbol'],
            trade_data['entry_time'],
            trade_data['entry_price'],
            trade_data['position_size'],
            trade_data.get('exit_time'),
            trade_data.get('exit_price'),
            trade_data.get('exit_reason'),
            trade_data.get('pnl', 0.0),
            trade_data.get('pnl_percent', 0.0),
            trade_data['sl_price'],
            trade_data['tp_price'],
            trade_data['result']
        ))

        self.sqlite_conn.commit()
        logger.info(f"✅ Trade persisted: {trade_data['setup_id'][:8]} ({trade_data['result']})")

    async def get_trades_for_setup(self, setup_id: str) -> List[Dict]:
        """Get all trades associated with a setup."""
        cursor = self.sqlite_conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE setup_id = ?", (setup_id,))

        trades = []
        for row in cursor.fetchall():
            trades.append(dict(row))

        return trades

    # ─────────────────────────────────────────────────────────────────
    # SESSION STATE MANAGEMENT
    # ─────────────────────────────────────────────────────────────────

    async def init_session(self, session_date: date, starting_capital: float):
        """Initialize trading session for the day."""
        cursor = self.sqlite_conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO session_state (
                date, started_at, starting_capital
            ) VALUES (?, ?, ?)
        """, (session_date, datetime.now(), starting_capital))

        self.sqlite_conn.commit()
        logger.info(f"✅ Session initialized: {session_date} (capital: ${starting_capital:,.2f})")

    async def update_session(self, session_date: date, **updates):
        """Update session state."""
        # Build dynamic UPDATE query
        fields = ', '.join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [session_date]

        cursor = self.sqlite_conn.cursor()
        cursor.execute(f"UPDATE session_state SET {fields} WHERE date = ?", values)
        self.sqlite_conn.commit()

    async def get_session(self, session_date: date) -> Optional[Dict]:
        """Get session state for a date."""
        cursor = self.sqlite_conn.cursor()
        cursor.execute("SELECT * FROM session_state WHERE date = ?", (session_date,))

        row = cursor.fetchone()
        return dict(row) if row else None

    # ─────────────────────────────────────────────────────────────────
    # CRASH RECOVERY
    # ─────────────────────────────────────────────────────────────────

    async def recover_state(self) -> Dict[str, Any]:
        """
        Recover full system state after crash.

        Returns:
            Dict with:
                - active_setups: List[SetupCandidate]
                - open_trades: List[Dict]
                - session_state: Dict
        """
        logger.info("🔄 Recovering state from persistence layer...")

        # Load active setups from Redis
        active_setups = await self.load_active_setups()

        # Load open trades from SQLite
        cursor = self.sqlite_conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE result = 'OPEN' ORDER BY entry_time DESC")
        open_trades = [dict(row) for row in cursor.fetchall()]

        # Load today's session
        today = date.today()
        session_state = await self.get_session(today)

        logger.info(f"✅ State recovered: {len(active_setups)} setups, {len(open_trades)} open trades")

        return {
            'active_setups': active_setups,
            'open_trades': open_trades,
            'session_state': session_state
        }

    # ─────────────────────────────────────────────────────────────────
    # REDIS HELPERS (with in-memory fallback)
    # ─────────────────────────────────────────────────────────────────

    async def _redis_set(self, key: str, value: str):
        """Set Redis key (or in-memory fallback)."""
        if self.redis_client:
            await self.redis_client.set(key, value)
        else:
            self._memory_store[key] = value

    async def _redis_get(self, key: str) -> Optional[str]:
        """Get Redis key (or in-memory fallback)."""
        if self.redis_client:
            return await self.redis_client.get(key)
        else:
            return self._memory_store.get(key)

    async def _redis_delete(self, key: str):
        """Delete Redis key (or in-memory fallback)."""
        if self.redis_client:
            await self.redis_client.delete(key)
        else:
            self._memory_store.pop(key, None)

    async def _redis_keys(self, pattern: str) -> List[str]:
        """Get Redis keys matching pattern (or in-memory fallback)."""
        if self.redis_client:
            return await self.redis_client.keys(pattern)
        else:
            import fnmatch
            return [k for k in self._memory_store.keys() if fnmatch.fnmatch(k, pattern)]

    # ─────────────────────────────────────────────────────────────────
    # CLEANUP
    # ─────────────────────────────────────────────────────────────────

    async def close(self):
        """Close all connections."""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis connection closed")

        if self.sqlite_conn:
            self.sqlite_conn.close()
            logger.info("SQLite connection closed")
