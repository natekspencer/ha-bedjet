"""BedJet helper functions."""

from __future__ import annotations

from datetime import timedelta

# Table: (temperature_threshold, [(fan_limit, hours), ...])
RUNTIME_TABLE = [
    (33.5, [(100, 12)]),
    (34.0, [(70, 12), (100, 4)]),
    (34.5, [(60, 12), (100, 4)]),
    (35.5, [(50, 12), (100, 4)]),
    (36.5, [(20, 12), (40, 6), (100, 4)]),
    (37.5, [(30, 6), (50, 4), (100, 2)]),
    (38.5, [(20, 6), (30, 4), (50, 2), (100, 1)]),
    (39.5, [(20, 6), (30, 4), (40, 2), (100, 1)]),
    (float("inf"), [(20, 4), (40, 2), (100, 1)]),
]


def calculate_maximum_runtime(temperature: float, fan_percent: int) -> timedelta:
    """Return maximum runtime as timedelta based on temperature (°C) and fan percent.

    This is for BedJet V2 only as BedJet 3 returns the maximum runtime in notifications.
    """
    for temperature_threshold, fan_rules in RUNTIME_TABLE:
        if temperature <= temperature_threshold:
            for fan_limit, hours in fan_rules:
                if fan_percent <= fan_limit:
                    return timedelta(hours=hours)
    return timedelta(hours=1)
