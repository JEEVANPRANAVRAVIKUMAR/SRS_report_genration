"""Injected Clock abstraction enforcing Asia/Kolkata timezone.

Non-negotiable rule from docs/SPEC.md:
All business logic uses the fixed zone Asia/Kolkata whatever timezone the host is set to.
An injected Clock supplies 'now' and 'today'; nothing else in domain/services may call now().
"""

from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


class Clock(ABC):
    """Abstract Clock interface."""

    @property
    @abstractmethod
    def timezone(self) -> ZoneInfo:
        """The timezone associated with this clock."""
        pass

    @abstractmethod
    def now(self) -> datetime:
        """Return the current time in the clock's timezone."""
        pass

    def today(self) -> date:
        """Return the current calendar date in the clock's timezone."""
        return self.now().date()


class SystemClock(Clock):
    """System clock pinned to Asia/Kolkata."""

    def __init__(self, tz: ZoneInfo = KOLKATA_TZ) -> None:
        self._tz = tz

    @property
    def timezone(self) -> ZoneInfo:
        return self._tz

    def now(self) -> datetime:
        return datetime.now(self._tz)


class FakeClock(Clock):
    """Controllable test clock that can be stepped, advanced, or frozen."""

    def __init__(self, current: datetime | None = None, tz: ZoneInfo = KOLKATA_TZ) -> None:
        self._tz = tz
        if current is None:
            self._current = datetime(2026, 5, 22, 12, 0, 0, tzinfo=tz)
        elif current.tzinfo is None:
            self._current = current.replace(tzinfo=tz)
        else:
            self._current = current.astimezone(tz)

    @property
    def timezone(self) -> ZoneInfo:
        return self._tz

    def now(self) -> datetime:
        return self._current

    def set_datetime(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            self._current = dt.replace(tzinfo=self._tz)
        else:
            self._current = dt.astimezone(self._tz)

    def set_date(self, d: date, hour: int = 12, minute: int = 0, second: int = 0) -> None:
        self._current = datetime(d.year, d.month, d.day, hour, minute, second, tzinfo=self._tz)

    def advance(self, td: timedelta) -> None:
        self._current += td
