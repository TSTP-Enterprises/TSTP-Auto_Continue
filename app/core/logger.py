import logging
import os
from logging.handlers import RotatingFileHandler


LOG_DIR = r"C:\TSTP\AutoClickerV2"
LOG_FILE = "autoclicker_v2.log"


def get_log_path() -> str:
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(LOG_DIR, LOG_FILE)


def configure_logging() -> None:
    log_path = get_log_path()
    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(logging.INFO)

    rotating_handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    rotating_handler.setFormatter(formatter)
    root.addHandler(rotating_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

