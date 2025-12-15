"""
Configuration for 5/1 SLOB Strategy

This module contains all strategy parameters and settings.
"""

import pytz
from typing import Optional


class SLOBConfig:
    """Configuration for 5/1 SLOB strategy"""

    # ============================================================================
    # MARKET & INSTRUMENT
    # ============================================================================
    SYMBOL = "NQ=F"  # US100 futures (Nasdaq 100)

    # ============================================================================
    # TIME CONFIGURATION (UTC+2 Stockholm)
    # ============================================================================
    TIMEZONE = pytz.timezone('Europe/Stockholm')

    # Session times
    ASIA_START = "02:00"
    ASIA_END = "09:00"
    LSE_START = "09:00"
    LSE_END = "15:30"
    NYSE_START = "15:30"
    NYSE_END = "22:00"

    # ============================================================================
    # CONSOLIDATION PARAMETERS
    # ============================================================================
    # Fixed pip ranges (will be replaced by ATR-based in Phase 3)
    CONSOLIDATION_MIN_PIPS = 20
    CONSOLIDATION_MAX_PIPS = 150
    CONSOLIDATION_MIN_DURATION_MINUTES = 15
    CONSOLIDATION_MAX_DURATION_MINUTES = 30
    CONSOLIDATION_PERCENT_MIN = 0.002  # 0.2%
    CONSOLIDATION_PERCENT_MAX = 0.005  # 0.5%

    # ATR-based parameters (Phase 3)
    USE_ATR_CONSOLIDATION = True
    ATR_PERIOD = 14
    ATR_MULTIPLIER_MIN = 0.5
    ATR_MULTIPLIER_MAX = 2.0

    # ============================================================================
    # NO-WICK CANDLE CRITERIA
    # ============================================================================
    # Fixed parameters (will be replaced by percentile-based in Phase 3)
    NO_WICK_MAX_PIPS = 8
    NO_WICK_MAX_PERCENT = 0.20  # Max 20% of candle range
    NO_WICK_MIN_BODY_PIPS = 15
    NO_WICK_MAX_BODY_PIPS = 60

    # Percentile-based parameters (Phase 3)
    USE_PERCENTILE_NOWICK = True
    NOWICK_PERCENTILE = 90  # Wick must be in 10th percentile (smaller than 90% of candles)
    NOWICK_LOOKBACK = 100  # Candles to look back for percentile calculation

    # ============================================================================
    # LIQUIDITY DETECTION
    # ============================================================================
    # Volume confirmation
    VOLUME_SPIKE_THRESHOLD = 1.5  # Current volume > avg_volume * 1.5
    VOLUME_LOOKBACK = 50  # Candles to calculate average volume

    # Multi-factor LIQ detection (Phase 3)
    USE_ENHANCED_LIQ = True
    LIQ_CONFIDENCE_THRESHOLD = 0.6  # Composite score threshold
    LIQ_REQUIRE_VOLUME_SPIKE = False  # Make volume optional
    LIQ_REQUIRE_REJECTION = False  # Make price rejection optional
    LIQ_REQUIRE_WICK_REVERSAL = False  # Make wick reversal optional

    # ============================================================================
    # ENTRY CRITERIA
    # ============================================================================
    MAX_RETRACEMENT_PIPS = 100  # Max pips price can go up after no-wick before invalidation
    MAX_ENTRY_WAIT_CANDLES = 20  # Max candles to wait for entry trigger after LIQ #2

    # ============================================================================
    # RISK MANAGEMENT
    # ============================================================================
    INITIAL_CAPITAL = 50000  # SEK
    POSITION_SIZE_PERCENT = 0.50  # 50% of capital
    INITIAL_POSITION_PERCENT = 0.70  # 70% of position size
    ADD_ON_PERCENT = 0.30  # 30% add-on at 50% pullback

    MIN_SL_PIPS = 10
    MAX_SL_PIPS = 60
    MIN_RR = 1.5
    MAX_RR = 2.5

    MAX_TRADES_PER_DAY = 2
    MAX_DRAWDOWN_PERCENT = 0.20  # Stop trading if drawdown > 20%

    # ============================================================================
    # TRADING WINDOWS
    # ============================================================================
    # Optimal trading window
    OPTIMAL_START = "16:00"
    OPTIMAL_END = "17:30"

    # News filter times
    NEWS_BLACKOUT_START = "19:00"
    NEWS_BLACKOUT_END = "22:00"

    # ============================================================================
    # BACKTESTING
    # ============================================================================
    BACKTEST_DAYS = 30

    # ============================================================================
    # ML PARAMETERS (Phase 4)
    # ============================================================================
    ML_ENABLED = False  # Enable after Phase 4
    ML_PROBABILITY_THRESHOLD = 0.7  # Minimum probability to take trade
    ML_MODEL_PATH: Optional[str] = None

    # ============================================================================
    # DATA CACHING
    # ============================================================================
    CACHE_DIR = "data_cache"
    CACHE_TTL_M1_HOURS = 24  # M1 data cache valid for 24 hours
    CACHE_TTL_M5_DAYS = 7  # M5 data cache valid for 7 days
    USE_CACHE = True

    # ============================================================================
    # LOGGING
    # ============================================================================
    LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
    LOG_FILE = "outputs/logs/slob_backtest.log"

    @classmethod
    def from_yaml(cls, yaml_path: str):
        """
        Load configuration from YAML file (Phase 1.1)

        Args:
            yaml_path: Path to YAML configuration file

        Returns:
            SLOBConfig instance with updated parameters
        """
        # TODO: Implement YAML loading in Phase 1
        raise NotImplementedError("YAML config loading will be implemented in Phase 1")

    @classmethod
    def validate(cls) -> bool:
        """
        Validate configuration parameters

        Returns:
            True if configuration is valid

        Raises:
            ValueError: If configuration is invalid
        """
        # Validate consolidation parameters
        if cls.CONSOLIDATION_MIN_PIPS >= cls.CONSOLIDATION_MAX_PIPS:
            raise ValueError("CONSOLIDATION_MIN_PIPS must be < CONSOLIDATION_MAX_PIPS")

        if cls.CONSOLIDATION_MIN_DURATION_MINUTES >= cls.CONSOLIDATION_MAX_DURATION_MINUTES:
            raise ValueError("Min duration must be < max duration")

        # Validate risk parameters
        if not (0 < cls.POSITION_SIZE_PERCENT <= 1.0):
            raise ValueError("POSITION_SIZE_PERCENT must be between 0 and 1")

        if cls.INITIAL_POSITION_PERCENT + cls.ADD_ON_PERCENT > 1.0:
            raise ValueError("Initial + add-on positions exceed 100%")

        # Validate R:R
        if cls.MIN_RR >= cls.MAX_RR:
            raise ValueError("MIN_RR must be < MAX_RR")

        return True


# Validate config on import
SLOBConfig.validate()
