SUPPORTED_UNITS = ("ms", "s", "min")


def to_seconds(value: float, unit: str) -> float:
    if unit not in SUPPORTED_UNITS:
        raise ValueError(f"Unsupported unit: {unit}")
    if value < 0:
        raise ValueError("Time value cannot be negative")
    if unit == "ms":
        return value / 1000.0
    if unit == "min":
        return value * 60.0
    return value


def from_seconds(seconds: float, unit: str) -> float:
    if unit not in SUPPORTED_UNITS:
        raise ValueError(f"Unsupported unit: {unit}")
    if seconds < 0:
        raise ValueError("Seconds cannot be negative")
    if unit == "ms":
        return seconds * 1000.0
    if unit == "min":
        return seconds / 60.0
    return seconds

