import pytest

from app.core.time_units import from_seconds, to_seconds


def test_to_seconds_ms():
    assert to_seconds(10, "ms") == pytest.approx(0.01)


def test_to_seconds_minutes():
    assert to_seconds(2, "min") == pytest.approx(120.0)


def test_from_seconds_ms():
    assert from_seconds(0.25, "ms") == pytest.approx(250.0)


def test_invalid_unit_raises():
    with pytest.raises(ValueError):
        to_seconds(1, "hour")

