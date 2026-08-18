"""Clock abstraction so reservation/redelivery logic is testable without real sleeps."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class RealClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeClock:
    """Test clock with an explicitly advanceable current time."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime.now(timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._now += timedelta(seconds=seconds)

    def set(self, when: datetime) -> None:
        self._now = when
