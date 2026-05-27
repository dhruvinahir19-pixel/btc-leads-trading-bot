"""
logging_setup.py — Structured JSON logging for production deployment.
Writes to both stdout (Docker-friendly) and rotating log files.
Replaces bare print() calls with structured, level-based logging.
"""
import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


class JSONFormatter(logging.Formatter):
    """Format log records as JSON lines for machine parsing."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def setup_logging(
    log_dir: Optional[Path] = None,
    log_level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
) -> logging.Logger:
    """
    Configure structured JSON logging.

    - stdout handler: JSON lines (for Docker logs, journald, etc.)
    - file handler: Rotating JSON files (for local debugging)
    - Returns the root 'trading_bot' logger.

    Call this once at application startup.
    """
    root_logger = logging.getLogger("trading_bot")
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Prevent duplicate handlers on re-initialization
    if root_logger.handlers:
        return root_logger

    json_formatter = JSONFormatter()

    # --- Handler 1: stdout (Docker / CLI) ---
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.setFormatter(json_formatter)
    root_logger.addHandler(stdout_handler)

    # --- Handler 2: Rotating file (local) ---
    if log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "trading_bot.log"

        file_handler = RotatingFileHandler(
            filename=str(log_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(json_formatter)
        root_logger.addHandler(file_handler)
        root_logger.info(f"Logging to file: {log_path}")

    return root_logger


def get_logger(name: str = "trading_bot") -> logging.Logger:
    """Get a named child logger of the root trading_bot logger."""
    return logging.getLogger(f"trading_bot.{name}")


# Convenience aliases matching the existing codebase style
logger = get_logger
