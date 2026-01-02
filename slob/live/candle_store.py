
import sqlite3
import logging
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Union

from .candle_aggregator import Candle
# Vi behöver inte importera Event här, vi kollar duck-typing istället

logger = logging.getLogger(__name__)

class CandleStore:
    """
    Persists candle data to SQLite database.
    """

    def __init__(self, db_path: str = "data/candles.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info(f"✅ CandleStore initialized at {self.db_path}")

    def _init_db(self):
        """Initialize database schema."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Candles table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS candles (
                        timestamp TEXT PRIMARY KEY,
                        open REAL,
                        high REAL,
                        low REAL,
                        close REAL,
                        volume INTEGER,
                        is_complete BOOLEAN
                    )
                ''')
                
                # Trades table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        setup_id TEXT,
                        symbol TEXT,
                        entry_time TEXT,
                        entry_price REAL,
                        position_size INTEGER,
                        sl_price REAL,
                        tp_price REAL,
                        exit_time TEXT,
                        exit_price REAL,
                        pnl REAL,
                        result TEXT
                    )
                ''')
                
                conn.commit()
                # logger.info("Database schema initialized")
        except Exception as e:
            logger.error(f"Failed to init DB: {e}")

    def save_candle(self, data: Any) -> None:
        """
        Save a completed candle to the database.
        Handles Candle objects, Event objects, and Dictionaries.
        """
        try:
            candle = data
            
            # --- UNWRAP LOGIC V2 (More Robust) ---
            # 1. Check if it's an Event wrapper (try common attribute names)
            if hasattr(data, 'payload'):
                candle = data.payload
            elif hasattr(data, 'data'):
                candle = data.data
            
            # 2. Extract values based on type (Object vs Dict)
            timestamp = None
            open_ = 0.0
            high = 0.0
            low = 0.0
            close = 0.0
            volume = 0
            is_complete = False
            
            if isinstance(candle, dict):
                # Handle Dictionary
                timestamp = candle.get('timestamp')
                open_ = candle.get('open', 0.0)
                high = candle.get('high', 0.0)
                low = candle.get('low', 0.0)
                close = candle.get('close', 0.0)
                volume = candle.get('volume', 0)
                is_complete = candle.get('is_complete', True) # Assume complete if dict came from aggregator
                
            elif hasattr(candle, 'timestamp'):
                # Handle Candle Object
                timestamp = candle.timestamp
                open_ = candle.open
                high = candle.high
                low = candle.low
                close = candle.close
                volume = candle.volume
                is_complete = getattr(candle, 'is_complete', True)
            
            else:
                # If we still can't identify it, log debug info
                logger.warning(f"save_candle received unknown object: {type(data)}")
                if hasattr(data, '__dict__'):
                     logger.warning(f"Attributes: {data.__dict__.keys()}")
                return

            # 3. Final Validation
            if not is_complete:
                return
                
            if isinstance(timestamp, datetime):
                timestamp_str = timestamp.isoformat()
            else:
                timestamp_str = str(timestamp)

            # 4. Insert into DB
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO candles 
                    (timestamp, open, high, low, close, volume, is_complete)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    timestamp_str,
                    open_,
                    high,
                    low,
                    close,
                    volume,
                    True
                ))
                conn.commit()
                # logger.debug(f"Saved candle: {timestamp_str}")
                
        except Exception as e:
            logger.error(f"Failed to save candle: {e}", exc_info=True)

    def get_recent_candles(self, limit: int = 100) -> List[Dict]:
        """Get most recent candles."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM candles 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                ''', (limit,))
                
                rows = cursor.fetchall()
                return [dict(row) for row in rows][::-1]
        except Exception as e:
            logger.error(f"Failed to fetch candles: {e}")
            return []

    def close(self) -> None:
        """Close connections."""
        logger.info("✅ Database connection closed")

    def get_stats(self) -> Dict[str, int]:
        try:
             with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM candles")
                count = cursor.fetchone()[0]
                return {'total_candles': count}
        except Exception as e:
            logger.debug(f"Could not get candle stats: {e}")
            return {'total_candles': 0}
