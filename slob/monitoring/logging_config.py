"""
Centralized Logging Configuration for SLOB Trading System

Features:
- Daily log rotation (keeps 30 days)
- Separate error log (rotates at 10MB, keeps 5 files)
- Console output (INFO level)
- File output (DEBUG level)
- Structured log format with timestamps

Usage:
    from slob.monitoring.logging_config import setup_logging

    # In your main script:
    setup_logging(log_dir='logs/')
"""

import logging
import sys
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler, RotatingFileHandler
from datetime import datetime


def setup_logging(
    log_dir: str = 'logs/',
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    error_log_enabled: bool = True
):
    """
    Setup comprehensive logging with rotation.

    Args:
        log_dir: Directory for log files (created if doesn't exist)
        console_level: Logging level for console output
        file_level: Logging level for file output
        error_log_enabled: Whether to create separate error log

    Returns:
        Logger instance
    """
    # Create log directory
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything, handlers will filter

    # Remove existing handlers to avoid duplicates
    root_logger.handlers = []

    # ========================================================================
    # Console Handler (INFO and above)
    # ========================================================================
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(simple_formatter)
    root_logger.addHandler(console_handler)

    # ========================================================================
    # Main Log File Handler (Daily rotation, 30 days retention)
    # ========================================================================
    main_log_file = log_path / 'trading.log'

    file_handler = TimedRotatingFileHandler(
        filename=str(main_log_file),
        when='midnight',       # Rotate at midnight
        interval=1,            # Every 1 day
        backupCount=30,        # Keep 30 days of logs
        encoding='utf-8',
        delay=False,
        utc=False
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(detailed_formatter)

    # Add date suffix to rotated files
    file_handler.suffix = "%Y-%m-%d"
    file_handler.extMatch = r"^\d{4}-\d{2}-\d{2}$"

    root_logger.addHandler(file_handler)

    # ========================================================================
    # Error Log File Handler (Size-based rotation, 10MB, 5 backups)
    # ========================================================================
    if error_log_enabled:
        error_log_file = log_path / 'errors.log'

        error_handler = RotatingFileHandler(
            filename=str(error_log_file),
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,              # Keep 5 backup files
            encoding='utf-8',
            delay=False
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(detailed_formatter)

        root_logger.addHandler(error_handler)

    # ========================================================================
    # Log startup message
    # ========================================================================
    root_logger.info("=" * 70)
    root_logger.info("SLOB Trading System - Logging Initialized")
    root_logger.info(f"Log Directory: {log_path.absolute()}")
    root_logger.info(f"Main Log: {main_log_file} (daily rotation, 30-day retention)")
    if error_log_enabled:
        root_logger.info(f"Error Log: {error_log_file} (10MB rotation, 5 backups)")
    root_logger.info(f"Console Level: {logging.getLevelName(console_level)}")
    root_logger.info(f"File Level: {logging.getLevelName(file_level)}")
    root_logger.info("=" * 70)

    return root_logger


def cleanup_old_logs(log_dir: str = 'logs/', days_to_keep: int = 30):
    """
    Manually cleanup log files older than specified days.

    This is a backup to the automatic rotation cleanup.

    Args:
        log_dir: Directory containing log files
        days_to_keep: Number of days to keep
    """
    import os
    import time

    log_path = Path(log_dir)
    if not log_path.exists():
        return

    cutoff_time = time.time() - (days_to_keep * 24 * 60 * 60)
    removed_count = 0

    for log_file in log_path.glob('*.log*'):
        # Skip main log files (without date suffix)
        if log_file.name in ['trading.log', 'errors.log']:
            continue

        # Check file modification time
        if log_file.stat().st_mtime < cutoff_time:
            try:
                log_file.unlink()
                removed_count += 1
            except Exception as e:
                logging.error(f"Failed to remove old log file {log_file}: {e}")

    if removed_count > 0:
        logging.info(f"Cleaned up {removed_count} old log files (older than {days_to_keep} days)")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    # Setup logging
    logger = setup_logging(log_dir='logs/')

    # Test different log levels
    logger.debug("This is a DEBUG message")
    logger.info("This is an INFO message")
    logger.warning("This is a WARNING message")
    logger.error("This is an ERROR message")
    logger.critical("This is a CRITICAL message")

    # Test module-specific logger
    module_logger = get_logger(__name__)
    module_logger.info("This is from a module-specific logger")

    # Test log rotation cleanup
    cleanup_old_logs(days_to_keep=30)

    print("\n✅ Logging configuration test complete!")
    print(f"Check logs/ directory for output files")
