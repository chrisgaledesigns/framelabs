"""Centralized logging setup for FrameLabs.

Every module in the application should get its logger from here,
so that all logs share the same format and destination.
"""

import logging
from pathlib import Path

LOG_DIR = Path.home() / ".framelabs" / "logs"
LOG_FILE = LOG_DIR / "framelabs.log"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure application-wide logging.

    Call this once, at application startup.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger("framelabs")
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger for a specific module.

    Example:
        logger = get_logger(__name__)
        logger.info("Project opened")
    """
    return logging.getLogger(f"framelabs.{name}")