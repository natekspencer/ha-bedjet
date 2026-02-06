"""BedJet limiter classes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

DEFAULT_TEMPERATURE_DELTA = 1.0
DEFAULT_TEMPERATURE_TIME = timedelta(seconds=15)
DEFAULT_DELTA_SECONDS = 5


@dataclass
class TemperatureLimiter:
    """Limit how often a temperature value is allowed to change.

    This class suppresses small, rapid fluctuations ("jitter") from fast-reporting
    temperature sensors. A new temperature is accepted only if at least one of the
    following conditions is met:

    - The temperature changed by at least ``min_delta`` degrees.
    - At least ``min_time`` has passed since the last accepted update.

    If the incoming temperature is exactly the same as the current value, the
    internal timer is reset to prevent a forced update due only to elapsed time.
    """

    min_delta: float = DEFAULT_TEMPERATURE_DELTA
    min_time: timedelta = DEFAULT_TEMPERATURE_TIME

    temperature: float | None = None
    last_updated: datetime | None = None

    def update(self, temperature: float, now: datetime | None = None) -> float:
        """Process a new temperature reading and return the value to report.

        Args:
            temperature: The newly received temperature reading.
            now: Optional timestamp for the reading. If not provided, the current
                 UTC time will be used. Supplying this is useful for testing or when
                 multiple values should share the same timestamp.

        Returns:
            The temperature value that should be reported after applying the
            limiter rules. This will be either the new temperature (if accepted)
            or the previously accepted value (if suppressed).
        """
        if now is None:
            now = datetime.now(UTC)

        def _accept() -> float:
            self.temperature = temperature
            self.last_updated = now
            return temperature

        if self.last_updated is None or self.temperature is None:
            return _accept()

        if self.temperature == temperature:
            return _accept()  # reset timer to further reduce jitter

        if (
            abs(temperature - self.temperature) >= self.min_delta
            or (now - self.last_updated) >= self.min_time
        ):
            return _accept()

        return self.temperature


@dataclass
class EndTimeLimiter:
    """Stabilize a calculated end time derived from remaining time.

    This suppresses small fluctuations in remaining time reports that would
    otherwise cause the computed end time to jitter and trigger unnecessary
    Home Assistant state updates.

    Rules:
    - If no time is remaining and the timer is not running, do not update.
    - If this is the first meaningful time, set the end time.
    - If a new timer starts after expiration, set the end time.
    - Otherwise, only update if the end time shifts by at least ``min_delta_seconds`` seconds.
    """

    min_delta_seconds: float = DEFAULT_DELTA_SECONDS

    _end_time: datetime | None = None

    def update(
        self, time_remaining: timedelta, now: datetime | None = None
    ) -> datetime | None:
        """Update and return the stabilized end time.

        Args:
            time_remaining: Remaining time reported by the device.
            now: Timestamp to use as the reference point. Defaults to current UTC.

        Returns:
            The stabilized end time, or ``None`` if no active time is present.
        """
        if now is None:
            now = datetime.now(UTC)

        old = self._end_time
        remaining = time_remaining.total_seconds()

        # Nothing running and nothing to update
        if remaining == 0 and (old is None or old <= now):
            return old

        new = now + time_remaining

        if (
            old is None
            or (old <= now and remaining > 0)  # new run after expiration
            or abs((new - old).total_seconds()) >= self.min_delta_seconds
        ):
            self._end_time = new

        return self._end_time
