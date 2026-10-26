"""Structured logging configuration with token and secret masking."""

import logging
import re
import sys
from typing import Optional

# Regex pattern to sanitize tokens, keys, and secrets from logs
SECRET_PATTERN = re.compile(
    r"(Bearer\s+[\w\.\-]+|X-API-KEY[:=]\s*[\w\.\-]+|api[-_]?key[:=]\s*[\w\.\-]+|secret[:=]\s*[\w\.\-]+|token[:=]\s*[\w\.\-]+)",
    re.IGNORECASE,
)


class SafeFormatter(logging.Formatter):
    """Custom formatter that redacts sensitive keys and bearer tokens."""

    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        return SECRET_PATTERN.sub("[REDACTED]", original)


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure structured and secure logging."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers on re-initialization
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(numeric_level)
        formatter = SafeFormatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] [%(filename)s:%(lineno)d] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    logger = logging.getLogger("forager_hubspot")
    logger.setLevel(numeric_level)
    return logger
