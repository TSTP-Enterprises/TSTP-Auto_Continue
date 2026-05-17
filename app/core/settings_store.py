import json
import logging
import os

from app.core.logger import LOG_DIR
from app.core.models import AppConfig


SETTINGS_FILE = "settings_v2.json"


class SettingsStore:
    def __init__(self, settings_path: str | None = None):
        os.makedirs(LOG_DIR, exist_ok=True)
        self._settings_path = settings_path or os.path.join(LOG_DIR, SETTINGS_FILE)

    @property
    def settings_path(self) -> str:
        return self._settings_path

    def load(self) -> AppConfig:
        if not os.path.exists(self._settings_path):
            return AppConfig()
        try:
            with open(self._settings_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, dict):
                logging.error("Settings file content was invalid. Defaults loaded.")
                return AppConfig()
            return AppConfig.from_dict(data)
        except Exception as exc:
            logging.error(f"Failed to load settings: {exc}")
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        try:
            with open(self._settings_path, "w", encoding="utf-8") as file:
                json.dump(config.to_dict(), file, indent=2)
        except Exception as exc:
            logging.error(f"Failed to save settings: {exc}")
            raise

