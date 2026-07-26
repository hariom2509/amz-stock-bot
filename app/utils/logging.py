"""
Structured logging setup for Amazon Stock Watcher.

Provides consistent, readable logs with key=value pairs.
Sensitive values (tokens, credentials) must NEVER be passed to logger.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    """
    Configure application-wide logging.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional path to log file. If None, logs to console only.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # ── Formatter ────────────────────────────────────────────────────────────
    fmt = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=date_fmt)

    # ── Root logger ──────────────────────────────────────────────────────────
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Clear any existing handlers
    root_logger.handlers.clear()

    # ── Console handler ──────────────────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(numeric_level)
    root_logger.addHandler(console_handler)

    # ── File handler (optional) ──────────────────────────────────────────────
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(numeric_level)
        root_logger.addHandler(file_handler)

    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger."""
    return logging.getLogger(name)
