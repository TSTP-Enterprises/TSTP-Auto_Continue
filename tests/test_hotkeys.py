import pytest

from app.controls.hotkeys import HotkeyError, normalize_hotkey


def test_normalize_escape():
    assert normalize_hotkey("esc") == "<esc>"


def test_normalize_combo():
    assert normalize_hotkey("Ctrl+Shift+S") == "<ctrl>+<shift>+s"


def test_normalize_windows_combo():
    assert normalize_hotkey("win+q") == "<cmd>+q"


def test_invalid_hotkey_raises():
    with pytest.raises(HotkeyError):
        normalize_hotkey("ctrl+unknownkey")

