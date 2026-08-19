"""Structured JSON logging configuration."""

from __future__ import annotations

import logging
import sys
from typing import Any

from pythonjsonlogger import jsonlogger


def configure_logging(level: str = "INFO") -> None:
    """Configure structured JSON logging for production observability.
    
    Args:
        level: Log level (INFO, DEBUG, WARNING, ERROR)
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove default handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # JSON stdout handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(timestamp)s %(level)s %(name)s %(message)s",
        timestamp=True,
    )
    stdout_handler.setFormatter(formatter)
    root_logger.addHandler(stdout_handler)

    # Set library log levels to WARNING
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.LoggerAdapter:
    """Get a logger with structured context support.
    
    Args:
        name: Logger name (typically __name__)
    
    Returns:
        LoggerAdapter for structured logging
    """
    logger = logging.getLogger(name)
    return logger
