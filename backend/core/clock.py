"""System-local clock helpers shared by the scheduler and audit logs.

The console reports times in the server's system timezone.  Database columns
receive naive local datetimes so the stored wall clock and the displayed wall
clock are the same value.  When a datetime is serialised, a local offset is
attached so a browser in another timezone still renders the server's local
time rather than silently converting it.
"""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo
from functools import lru_cache

try:  # APScheduler already depends on tzlocal on supported deployments.
    from tzlocal import get_localzone
except ImportError:  # pragma: no cover - exercised only on minimal installs.
    get_localzone = None


@lru_cache(maxsize=1)
def local_zone() -> tzinfo:
    """Return the system's local timezone, including its DST rules."""
    if get_localzone is not None:
        try:
            return get_localzone()
        except Exception:
            pass
    return datetime.now().astimezone().tzinfo or timezone.utc


def local_now() -> datetime:
    """Current system-local time as a naive datetime for database storage."""
    return datetime.now()


def as_local(value: datetime | None) -> datetime | None:
    """Attach the system-local timezone to a stored/handled datetime.

    Naive values are already local (the storage convention); aware values are
    converted to local first.  The returned value carries an offset, so JSON
    clients can both sort it correctly and show the server's wall clock.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=local_zone())
    return value.astimezone(local_zone())


def utc_naive_to_local(value: datetime) -> datetime:
    """Convert a legacy naive-UTC scheduler timestamp to naive local time."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(local_zone()).replace(tzinfo=None)


__all__ = ["as_local", "local_now", "local_zone", "utc_naive_to_local"]
