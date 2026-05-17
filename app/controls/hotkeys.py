import logging
import re
from typing import Callable, Optional


try:
    from pynput import keyboard
except Exception:  # pragma: no cover
    keyboard = None


class HotkeyError(Exception):
    pass


MODIFIER_MAP = {
    "ctrl": "<ctrl>",
    "control": "<ctrl>",
    "alt": "<alt>",
    "shift": "<shift>",
    "meta": "<cmd>",
    "cmd": "<cmd>",
    "win": "<cmd>",
    "windows": "<cmd>",
}

KEY_MAP = {
    "escape": "<esc>",
    "esc": "<esc>",
    "enter": "<enter>",
    "return": "<enter>",
    "space": "<space>",
    "tab": "<tab>",
}


def normalize_hotkey(raw_hotkey: str) -> str:
    if not raw_hotkey:
        raise HotkeyError("Hotkey cannot be empty.")

    cleaned = raw_hotkey.strip()
    if cleaned.startswith("<") and cleaned.endswith(">") and "+" not in cleaned:
        return cleaned.lower()
    if cleaned.startswith("<") and "+" in cleaned:
        return cleaned.lower()

    tokens = [token.strip().lower() for token in re.split(r"\+", cleaned) if token.strip()]
    if not tokens:
        raise HotkeyError("Hotkey cannot be empty.")

    normalized = []
    for token in tokens:
        if token in MODIFIER_MAP:
            normalized.append(MODIFIER_MAP[token])
            continue
        if token in KEY_MAP:
            normalized.append(KEY_MAP[token])
            continue
        if re.fullmatch(r"f([1-9]|1[0-2])", token):
            normalized.append(f"<{token}>")
            continue
        if len(token) == 1 and (token.isalpha() or token.isdigit()):
            normalized.append(token)
            continue
        raise HotkeyError(f"Unsupported key token: {token}")

    modifiers = [token for token in normalized if token in MODIFIER_MAP.values()]
    keys = [token for token in normalized if token not in MODIFIER_MAP.values()]
    if not keys:
        raise HotkeyError("Hotkey must include a non-modifier key.")
    return "+".join(modifiers + keys)


class GlobalHotkeyService:
    def __init__(self, callback: Callable[[], None]):
        self._callback = callback
        self._listener: Optional[object] = None
        self._hotkey = ""

    @property
    def active_hotkey(self) -> str:
        return self._hotkey

    def register(self, raw_hotkey: str) -> str:
        if keyboard is None:
            raise HotkeyError("pynput is not installed; global hotkeys are unavailable.")

        normalized = normalize_hotkey(raw_hotkey)
        self.stop()
        try:
            self._listener = keyboard.GlobalHotKeys({normalized: self._callback})
            self._listener.start()
            self._hotkey = normalized
            logging.info(f"Global emergency hotkey registered: {normalized}")
            return normalized
        except Exception as exc:
            self._listener = None
            self._hotkey = ""
            raise HotkeyError(f"Failed to register hotkey {normalized}: {exc}")

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception as exc:
                logging.error(f"Failed to stop global hotkey listener: {exc}")
            self._listener = None
            self._hotkey = ""

