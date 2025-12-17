"""
Candle Store

SQLite persistence layer for historical M1 candles.
Provides efficient storage and retrieval of OHLCV data.
"""

import sqlite3
import logging
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd

from .candle_aggregator import Candle

logger = logging.getLogger(__name__)


class CandleStore:
    """
    SQLite storage for historical candles.

    Features:
    - Efficient bulk inserts
    - Time-range queries
    - Symbol-based filtering
    - Automatic schema creation
    - Connection pooling

    Usage:
        store = CandleStore(db_path='data/candles.db')

        # Save candle
        await store.save_candle(candle)

        # Bulk save
        await store.save_candles(candles)

        # Query
        df = store.get_candles('NQ', start_time, end_time)
    """

    # Database schema
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS candles (
        symbol TEXT NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume INTEGER NOT NULL,
        tick_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (symbol, timestamp)
    );

    CREATE INDEX IF NOT EXISTS idx_candles_symbol_time
    ON candles (symbol, timestamp DESC);

    CREATE INDEX IF NOT EXISTS idx_candles_timestamp
    ON candles (timestamp DESC);
    """

    def __init__(self, db_path: str = 'data/candles.db'):
        """
        Initialize candle store.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Connection (will be created on demand)
        self.conn: Optional[sqlite3.Connection] = None

        # Statistics
        self.candles_saved = 0
        self.queries_executed = 0

        # Initialize database
        self._initialize_db()

        logger.info(f"✅ CandleStore initialized at {self.db_path}")

    def _initialize_db(self):
        """Initialize database schema."""
        conn = self._get_connection()

        try:
            # Execute schema
            conn.executescript(self.SCHEMA)
            conn.commit()

            logger.info("Database schema initialized")

        except sqlite3.Error as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def _get_connection(self) -> sqlite3.Connection:
        """
        Get database connection.

        Returns:
            SQLite connection
        """
        if self.conn is None:
            self.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,  # Allow multi-threaded access
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )

            # Enable foreign keys
            self.conn.execute("PRAGMA foreign_keys = ON")

            # Use WAL mode for better concurrent access
            self.conn.execute("PRAGMA journal_mode = WAL")

        return self.conn

    def save_candle(self, candle: Candle):
        """
        Save a single candle to database.

        Args:
            candle: Candle to save

        Raises:
            sqlite3.Error: If save fails
        """
        if not candle.is_complete():
            logger.warning(f"Skipping incomplete candle: {candle}")
            return

        conn = self._get_connection()

        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO candles
                (symbol, timestamp, open, high, low, close, volume, tick_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candle.symbol,
                    candle.timestamp,
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                    candle.tick_count
                )
            )

            conn.commit()
            self.candles_saved += 1

            logger.debug(f"Saved candle: {candle.symbol} @ {candle.timestamp}")

        except sqlite3.Error as e:
            logger.error(f"Failed to save candle: {e}")
            conn.rollback()
            raise

    def save_candles(self, candles: List[Candle]):
        """
        Bulk save candles to database.

        Args:
            candles: List of candles to save

        Raises:
            sqlite3.Error: If save fails
        """
        if not candles:
            return

        # Filter out incomplete candles
        complete_candles = [c for c in candles if c.is_complete()]

        if not complete_candles:
            logger.warning("No complete candles to save")
            return

        conn = self._get_connection()

        try:
            # Prepare data
            data = [
                (
                    c.symbol,
                    c.timestamp,
                    c.open,
                    c.high,
                    c.low,
                    c.close,
                    c.volume,
                    c.tick_count
                )
                for c in complete_candles
            ]

            # Bulk insert
            conn.executemany(
                """
                INSERT OR REPLACE INTO candles
                (symbol, timestamp, open, high, low, close, volume, tick_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                data
            )

            conn.commit()
            self.candles_saved += len(complete_candles)

            logger.info(f"Bulk saved {len(complete_candles)} candles")

        except sqlite3.Error as e:
            logger.error(f"Failed to bulk save candles: {e}")
            conn.rollback()
            raise

    def get_candles(
        self,
        symbol: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Query candles from database.

        Args:
            symbol: Symbol to query
            start_time: Start time (inclusive)
            end_time: End time (inclusive)
            limit: Max number of candles to return

        Returns:
            DataFrame with OHLCV data
        """
        conn = self._get_connection()
        self.queries_executed += 1

        # Build query
        query = "SELECT * FROM candles WHERE symbol = ?"
        params = [symbol]

        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)

        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)

        query += " ORDER BY timestamp ASC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        try:
            df = pd.read_sql_query(query, conn, params=params)

            # Convert timestamp column to datetime
            if not df.empty and 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)

            logger.debug(f"Query returned {len(df)} candles for {symbol}")

            return df

        except sqlite3.Error as e:
            logger.error(f"Query failed: {e}")
            raise

    def get_latest_candle(self, symbol: str) -> Optional[Candle]:
        """
        Get most recent candle for symbol.

        Args:
            symbol: Symbol to query

        Returns:
            Latest candle or None
        """
        conn = self._get_connection()

        try:
            cursor = conn.execute(
                """
                SELECT symbol, timestamp, open, high, low, close, volume, tick_count
                FROM candles
                WHERE symbol = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (symbol,)
            )

            row = cursor.fetchone()

            if row:
                candle = Candle(symbol=row[0], timestamp=row[1])
                candle.open = row[2]
                candle.high = row[3]
                candle.low = row[4]
                candle.close = row[5]
                candle.volume = row[6]
                candle.tick_count = row[7]

                return candle

            return None

        except sqlite3.Error as e:
            logger.error(f"Failed to get latest candle: {e}")
            return None

    def get_candle_count(self, symbol: Optional[str] = None) -> int:
        """
        Get total number of candles stored.

        Args:
            symbol: Filter by symbol (None = all symbols)

        Returns:
            Count of candles
        """
        conn = self._get_connection()

        try:
            if symbol:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM candles WHERE symbol = ?",
                    (symbol,)
                )
            else:
                cursor = conn.execute("SELECT COUNT(*) FROM candles")

            count = cursor.fetchone()[0]
            return count

        except sqlite3.Error as e:
            logger.error(f"Failed to get candle count: {e}")
            return 0

    def get_symbols(self) -> List[str]:
        """
        Get list of all symbols in database.

        Returns:
            List of symbol names
        """
        conn = self._get_connection()

        try:
            cursor = conn.execute(
                "SELECT DISTINCT symbol FROM candles ORDER BY symbol"
            )

            symbols = [row[0] for row in cursor.fetchall()]
            return symbols

        except sqlite3.Error as e:
            logger.error(f"Failed to get symbols: {e}")
            return []

    def get_date_range(self, symbol: str) -> Optional[Dict[str, datetime]]:
        """
        Get date range for a symbol.

        Args:
            symbol: Symbol to query

        Returns:
            Dict with 'start' and 'end' datetimes, or None
        """
        conn = self._get_connection()

        try:
            cursor = conn.execute(
                """
                SELECT MIN(timestamp), MAX(timestamp)
                FROM candles
                WHERE symbol = ?
                """,
                (symbol,)
            )

            row = cursor.fetchone()

            if row and row[0] and row[1]:
                # Convert strings to datetime if needed
                start = row[0] if isinstance(row[0], datetime) else datetime.fromisoformat(row[0])
                end = row[1] if isinstance(row[1], datetime) else datetime.fromisoformat(row[1])
                return {
                    'start': start,
                    'end': end
                }

            return None

        except sqlite3.Error as e:
            logger.error(f"Failed to get date range: {e}")
            return None

    def delete_candles(
        self,
        symbol: str,
        before: Optional[datetime] = None
    ):
        """
        Delete candles from database.

        Args:
            symbol: Symbol to delete
            before: Delete candles before this time (None = delete all)
        """
        conn = self._get_connection()

        try:
            if before:
                conn.execute(
                    "DELETE FROM candles WHERE symbol = ? AND timestamp < ?",
                    (symbol, before)
                )
            else:
                conn.execute(
                    "DELETE FROM candles WHERE symbol = ?",
                    (symbol,)
                )

            deleted = conn.total_changes
            conn.commit()

            logger.info(f"Deleted {deleted} candles for {symbol}")

        except sqlite3.Error as e:
            logger.error(f"Failed to delete candles: {e}")
            conn.rollback()
            raise

    def vacuum(self):
        """
        Optimize database (reclaim space after deletes).

        Should be run periodically to maintain performance.
        """
        conn = self._get_connection()

        try:
            logger.info("Running VACUUM on database...")
            conn.execute("VACUUM")
            logger.info("✅ VACUUM completed")

        except sqlite3.Error as e:
            logger.error(f"VACUUM failed: {e}")

    def get_stats(self) -> Dict:
        """
        Get storage statistics.

        Returns:
            Dict with stats
        """
        total_candles = self.get_candle_count()
        symbols = self.get_symbols()

        # Get database file size
        db_size_mb = self.db_path.stat().st_size / (1024 * 1024) if self.db_path.exists() else 0

        return {
            'db_path': str(self.db_path),
            'db_size_mb': round(db_size_mb, 2),
            'total_candles': total_candles,
            'symbols_count': len(symbols),
            'symbols': symbols,
            'candles_saved': self.candles_saved,
            'queries_executed': self.queries_executed
        }

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.info("✅ Database connection closed")

    def __del__(self):
        """Cleanup on destruction."""
        self.close()
