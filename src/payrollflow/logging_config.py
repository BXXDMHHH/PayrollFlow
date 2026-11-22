"""Consistent local logging setup."""

import logging
from logging.handlers import RotatingFileHandler

from payrollflow.paths import LOG_DIR


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure console and rotating-file logging without employee payloads."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("payrollflow")
    logger.setLevel(level)
    logger.propagate = False
    if logger.handlers:
        return logger
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        LOG_DIR / "payrollflow.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger
