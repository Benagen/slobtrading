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
        # TLS/SSL configuration
        redis_tls_enabled: bool = False,
        redis_ca_cert: Optional[str] = None,
        redis_client_cert: Optional[str] = None,
        redis_client_key: Optional[str] = None,
    ):
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.redis_password = redis_password
        self.sqlite_path = sqlite_path
        self.backup_dir = backup_dir
        self.enable_redis = enable_redis and REDIS_AVAILABLE
        # TLS settings
        self.redis_tls_enabled = redis_tls_enabled
        self.redis_ca_cert = redis_ca_cert
        self.redis_client_cert = redis_client_cert
        self.redis_client_key = redis_client_key


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
        self.using_in_memory = False  # Track if using in-memory fallback
        self.redis_available = False  # Track Redis availability
        self.redis_prefix = "slob"  # Prefix for all Redis keys

        # In-memory fallback if Redis unavailable
        self._memory_store: Dict[str, str] = {}

        # Background tasks
        self._health_monitor_task: Optional[asyncio.Task] = None

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
                # Build Redis connection parameters
                redis_params = {
                    'host': self.config.redis_host,
                    'port': self.config.redis_port,
                    'db': self.config.redis_db,
                    'password': self.config.redis_password,
                    'decode_responses': True
                }

                # Add TLS/SSL parameters if enabled
                if self.config.redis_tls_enabled:
                    redis_params['ssl'] = True
                    redis_params['ssl_cert_reqs'] = 'required'

                    if self.config.redis_ca_cert:
                        redis_params['ssl_ca_certs'] = self.config.redis_ca_cert
                    if self.config.redis_client_cert:
                        redis_params['ssl_certfile'] = self.config.redis_client_cert
                    if self.config.redis_client_key:
                        redis_params['ssl_keyfile'] = self.config.redis_client_key

                    logger.info(f"Connecting to Redis with TLS enabled...")

                self.redis_client = redis.Redis(**redis_params)
                await self.redis_client.ping()

                tls_status = "with TLS" if self.config.redis_tls_enabled else "without TLS"
                logger.info(f"✅ Redis connected ({tls_status}): {self.config.redis_host}:{self.config.redis_port}")
                self.using_in_memory = False
                self.redis_available = True
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}. Using in-memory fallback.")
                self.redis_client = None
                self.using_in_memory = True
                self.redis_available = False
        else:
            logger.info("Redis disabled - using in-memory fallback")
            self.using_in_memory = True
            self.redis_available = False

        # SQLite connection
        self._init_sqlite()

        # Create backup directory
        Path(self.config.backup_dir).mkdir(parents=True, exist_ok=True)

        # Start Redis health monitoring if Redis is enabled
        if self.config.enable_redis and self.redis_available:
            self._health_monitor_task = asyncio.create_task(self._redis_health_monitor())
            logger.info("Started Redis health monitor")

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

        # Enable WAL mode for crash recovery and better concurrency
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")  # Balance safety/performance

        # Verify WAL mode enabled
        wal_mode = cursor.execute("PRAGMA journal_mode").fetchone()[0]
        if wal_mode.upper() != 'WAL':
            logger.warning(f"WAL mode not enabled, using {wal_mode}")
        else:
            logger.info("SQLite WAL mode enabled for crash recovery")

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

                FOREIGN KEY (setup_id) REFERENCES setups(id)
            )
        """)

        # Table: active_setups (Redis fallback for active setups)
        # This lightweight table enables quick recovery of active setups
        # when Redis is unavailable
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_setups (
                setup_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                state TEXT NOT NULL,
                raw_data TEXT NOT NULL,
                last_updated REAL NOT NULL
            )
        """)

        # Indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_setups_state ON setups(state)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_setups_created ON setups(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_setup ON trades(setup_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_date ON session_state(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_shadow_timestamp ON shadow_predictions(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_shadow_agreement ON shadow_predictions(agreement)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_shadow_setup ON shadow_predictions(setup_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_active_setups_state ON active_setups(state)")

        self.sqlite_conn.commit()
        logger.info(f"✅ SQLite initialized: {self.config.sqlite_path}")

    # ─────────────────────────────────────────────────────────────────
    # SETUP STATE MANAGEMENT (Redis + SQLite)
    # ─────────────────────────────────────────────────────────────────

    async def save_setup(self, candidate: SetupCandidate):
        """
        Save setup candidate to Redis, SQLite setups table, and active_setups table.

        Dual-write strategy:
        - Redis (hot): Fast access for active setups
        - SQLite active_setups (warm): Fallback for Redis failures
        - SQLite setups (cold): Complete historical record

        Args:
            candidate: SetupCandidate to persist
        """
        setup_data = candidate.to_dict()
        setup_json = json.dumps(setup_data)

        is_active = candidate.is_valid() and not candidate.is_complete()

        # Primary: Redis (if available)
        if is_active:
            if self.redis_available:
                try:
                    await self._redis_set(f"setup:active:{candidate.id}", setup_json)
                    logger.debug(f"Saved active setup to Redis: {candidate.id[:8]}")
                except Exception as e:
                    logger.error(f"Redis write failed: {e}")
                    self.redis_available = False
        else:
            # Remove from active if completed/invalidated
            try:
                await self._redis_delete(f"setup:active:{candidate.id}")
            except Exception as e:
                logger.error(f"Redis delete failed: {e}")

        # Fallback: SQLite active_setups (ALWAYS write for durability)
        if is_active:
            self._sqlite_save_active_setup(candidate.id, setup_data, setup_json)
            logger.debug(f"Saved active setup to SQLite fallback: {candidate.id[:8]}")
        else:
            # Remove from active_setups if completed/invalidated
            self._sqlite_remove_active_setup(candidate.id)

        # Cold storage: SQLite setups (all setups)
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

    def _sqlite_save_active_setup(self, setup_id: str, setup_data: Dict, raw_json: str):
        """
        Save active setup to active_setups table for Redis fallback.

        Args:
            setup_id: Setup ID
            setup_data: Setup data dictionary
            raw_json: JSON string of complete setup data
        """
        cursor = self.sqlite_conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO active_setups (
                setup_id, symbol, state, raw_data, last_updated
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            setup_id,
            setup_data['symbol'],
            setup_data['state'],
            raw_json,
            time.time()
        ))

        self.sqlite_conn.commit()

    def _sqlite_remove_active_setup(self, setup_id: str):
        """
        Remove setup from active_setups table when completed/invalidated.

        Args:
            setup_id: Setup ID to remove
        """
        cursor = self.sqlite_conn.cursor()

        cursor.execute("DELETE FROM active_setups WHERE setup_id = ?", (setup_id,))

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

    async def get_active_setups(self) -> List[Dict]:
        """
        Get all active (not completed) setups from Redis or SQLite fallback.

        Tries Redis first, falls back to active_setups table if Redis unavailable.

        Returns:
            List of setup dictionaries with state NOT IN ('SETUP_COMPLETE', 'INVALIDATED')
        """
        active_setups = []

        # Try Redis first (if available)
        if self.redis_available and self.redis_client:
            try:
                keys = await self._redis_keys("setup:active:*")
                logger.debug(f"Found {len(keys)} active setup keys in Redis")

                for key in keys:
                    data_json = await self._redis_get(key)
                    if data_json:
                        setup_data = json.loads(data_json)
                        active_setups.append(setup_data)

                if active_setups:
                    logger.info(f"✅ Loaded {len(active_setups)} active setups from Redis")
                    return active_setups
            except Exception as e:
                logger.warning(f"Failed to load setups from Redis: {e}")
                self.redis_available = False

        # Fallback to SQLite active_setups table
        logger.info("Using SQLite fallback for active setups")
        cursor = self.sqlite_conn.cursor()
        cursor.execute("""
            SELECT raw_data
            FROM active_setups
            WHERE state NOT IN ('SETUP_COMPLETE', 'INVALIDATED')
            ORDER BY last_updated DESC
        """)

        rows = cursor.fetchall()
        logger.debug(f"Found {len(rows)} active setups in SQLite fallback")

        for row in rows:
            try:
                setup_data = json.loads(row['raw_data'])
                active_setups.append(setup_data)
            except Exception as e:
                logger.error(f"Failed to deserialize setup from SQLite: {e}")

        logger.info(f"✅ Loaded {len(active_setups)} active setups from SQLite fallback")
        return active_setups

    async def get_open_trades(self) -> List[Dict]:
        """
        Get all open (not closed) trades from SQLite.

        Returns:
            List of trade dictionaries with result = 'OPEN'
        """
        cursor = self.sqlite_conn.cursor()
        cursor.execute("""
            SELECT *
            FROM trades
            WHERE result = 'OPEN'
            ORDER BY entry_time DESC
        """)

        trades = []
        for row in cursor.fetchall():
            trades.append(dict(row))

        logger.info(f"✅ Found {len(trades)} open trades")
        return trades

    async def close_trade(self, trade_id: str, exit_price: float, exit_reason: str):
        """
        Mark a trade as closed (for reconciliation).

        Args:
            trade_id: Trade identifier
            exit_price: Price at which trade was closed
            exit_reason: Reason for closure (e.g., 'EXTERNAL_CLOSE', 'MANUAL_CLOSE')
        """
        cursor = self.sqlite_conn.cursor()

        # Update trade to mark as closed
        cursor.execute("""
            UPDATE trades
            SET result = 'CLOSED',
                exit_price = ?,
                exit_time = ?,
                exit_reason = ?
            WHERE id = ?
        """, (exit_price, datetime.now().isoformat(), exit_reason, trade_id))

        self.sqlite_conn.commit()
        logger.info(f"✅ Trade {trade_id} marked as closed: exit_price={exit_price}, reason={exit_reason}")

    # ─────────────────────────────────────────────────────────────────
    # ML SHADOW MODE (SQLite only)
    # ─────────────────────────────────────────────────────────────────

    async def save_shadow_result(self, shadow_result: Dict):
        """
        Save ML shadow prediction to database.

        Stores:
        - Setup ID
        - ML probability and decision
        - Rule-based decision
        - Agreement/disagreement
        - Feature values (as JSON)
        - Model version

        Args:
            shadow_result: Dict with shadow prediction details
                - setup_id
                - timestamp
                - ml_probability
                - ml_decision ('TAKE' or 'SKIP')
                - ml_threshold
                - rule_decision ('TAKE')
                - agreement (bool)
                - features (dict or DataFrame)
                - model_version
        """
        cursor = self.sqlite_conn.cursor()

        # Convert features to JSON if it's a DataFrame or dict
        features_json = shadow_result.get('features')
        if hasattr(features_json, 'to_dict'):  # DataFrame
            features_json = json.dumps(features_json.to_dict('records')[0])
        elif isinstance(features_json, dict):
            features_json = json.dumps(features_json)
        elif isinstance(features_json, str):
            pass  # Already JSON
        else:
            features_json = None

        cursor.execute("""
            INSERT INTO shadow_predictions (
                setup_id, timestamp, ml_probability, ml_decision,
                ml_threshold, rule_decision, agreement,
                features, model_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            shadow_result['setup_id'],
            shadow_result['timestamp'],
            shadow_result['ml_probability'],
            shadow_result['ml_decision'],
            shadow_result['ml_threshold'],
            shadow_result['rule_decision'],
            shadow_result['agreement'],
            features_json,
            shadow_result.get('model_version', 'unknown')
        ))

        self.sqlite_conn.commit()
        logger.debug(f"✅ Shadow result saved: {shadow_result['setup_id'][:8]} "
                    f"(ML={shadow_result['ml_probability']:.1%}, agree={shadow_result['agreement']})")

    async def update_shadow_outcome(self, setup_id: str, outcome: str, pnl: float):
        """
        Update shadow prediction with actual trade outcome.

        Called when trade completes to backfill actual results.

        Args:
            setup_id: Setup ID to update
            outcome: 'WIN' or 'LOSS'
            pnl: Actual P&L in dollars
        """
        cursor = self.sqlite_conn.cursor()

        cursor.execute("""
            UPDATE shadow_predictions
            SET actual_outcome = ?, actual_pnl = ?
            WHERE setup_id = ?
        """, (outcome, pnl, setup_id))

        self.sqlite_conn.commit()
        logger.debug(f"✅ Shadow outcome updated: {setup_id[:8]} ({outcome}, ${pnl:.2f})")

    async def get_shadow_statistics(self, days: int = 30) -> Dict[str, Any]:
        """
        Get shadow mode statistics for analysis.

        Args:
            days: Number of days to look back

        Returns:
            Dict with statistics:
                - total_predictions
                - agreements
                - disagreements
                - agreement_rate
                - avg_ml_probability
                - predictions_by_decision
        """
        cursor = self.sqlite_conn.cursor()

        # Overall stats
        cursor.execute(f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN agreement = 1 THEN 1 ELSE 0 END) as agreements,
                AVG(ml_probability) as avg_prob,
                SUM(CASE WHEN ml_decision = 'TAKE' THEN 1 ELSE 0 END) as ml_approved,
                SUM(CASE WHEN ml_decision = 'SKIP' THEN 1 ELSE 0 END) as ml_rejected
            FROM shadow_predictions
            WHERE timestamp > datetime('now', '-{days} days')
        """)

        row = cursor.fetchone()
        total = row['total'] or 0
        agreements = row['agreements'] or 0
        avg_prob = row['avg_prob'] or 0.0
        ml_approved = row['ml_approved'] or 0
        ml_rejected = row['ml_rejected'] or 0

        agreement_rate = agreements / total if total > 0 else 0.0

        return {
            'total_predictions': total,
            'agreements': agreements,
            'disagreements': total - agreements,
            'agreement_rate': agreement_rate,
            'avg_ml_probability': avg_prob,
            'ml_approved': ml_approved,
            'ml_rejected': ml_rejected
        }

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
    # REDIS HEALTH MONITORING
    # ─────────────────────────────────────────────────────────────────

    async def _check_redis_health(self) -> bool:
        """
        Check if Redis is available and responsive.

        Returns:
            True if Redis is healthy, False otherwise
        """
        if not self.redis_client:
            return False

        try:
            await self.redis_client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False

    async def _redis_health_monitor(self):
        """
        Monitor Redis health and trigger failover if needed.

        Runs in background, checking every 30 seconds.
        If Redis becomes unavailable, triggers failover to in-memory store.
        If Redis becomes available again, restores connection.
        """
        logger.info("Redis health monitor started (check interval: 30s)")

        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds

                is_healthy = await self._check_redis_health()

                # Redis just became unavailable
                if not is_healthy and self.redis_available:
                    logger.critical("⚠️ Redis became unavailable - switching to in-memory fallback")
                    self.redis_available = False
                    self.using_in_memory = True

                    # TODO: Trigger alert via Telegram/Email
                    # await self._send_redis_failover_alert()

                # Redis just became available again
                elif is_healthy and not self.redis_available:
                    logger.info("✅ Redis connection restored")
                    self.redis_available = True
                    self.using_in_memory = False

            except asyncio.CancelledError:
                logger.info("Redis health monitor cancelled")
                raise
            except Exception as e:
                logger.error(f"Error in Redis health monitor: {e}", exc_info=True)

    # ─────────────────────────────────────────────────────────────────
    # CLEANUP
    # ─────────────────────────────────────────────────────────────────

    async def close(self):
        """Close all connections."""
        # Stop health monitor task
        if self._health_monitor_task:
            self._health_monitor_task.cancel()
            try:
                await self._health_monitor_task
            except asyncio.CancelledError:
                pass
            logger.info("Health monitor task stopped")

        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis connection closed")

        if self.sqlite_conn:
            self.sqlite_conn.close()
            logger.info("SQLite connection closed")
