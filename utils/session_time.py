"""Trading session filter (London / New York, UTC based)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

try:
    import pytz
except ImportError:  # pragma: no cover
    pytz = None

from config.settings import settings

SESSIONS = {
    "LONDON": settings.london_session,
    "NEW YORK": settings.newyork_session,
}


def _now(now: datetime | None = None) -> datetime:
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def active_sessions(now: datetime | None = None) -> List[str]:
    n = _now(now)
    if n.weekday() >= 5:  # Sat/Sun -> forex closed
        return []
    hour = n.hour + n.minute / 60.0
    return [name for name, (start, end) in SESSIONS.items() if start <= hour < end]


def is_session_active(symbol: str | None = None, now: datetime | None = None) -> bool:
    if not settings.session_filter_enabled:
        return True
    if symbol and settings.is_crypto(symbol) and settings.crypto_ignores_session:
        return True
    return bool(active_sessions(now))


def session_label(symbol: str | None = None, now: datetime | None = None) -> str:
    names = active_sessions(now)
    if names:
        return " + ".join(names)
    if symbol and settings.is_crypto(symbol):
        return "CRYPTO 24/7"
    return "CLOSED"


def next_session_open(now: datetime | None = None) -> datetime:
    n = _now(now)
    for delta_day in range(0, 8):
        day = (n + timedelta(days=delta_day)).replace(minute=0, second=0, microsecond=0)
        if day.weekday() >= 5:
            continue
        for start, _end in sorted(SESSIONS.values()):
            candidate = day.replace(hour=start)
            if candidate > n:
                return candidate
    return n + timedelta(hours=1)


def local_time_str(now: datetime | None = None, tz_name: str = "Africa/Lagos") -> str:
    n = _now(now)
    if pytz is not None:
        try:
            return n.astimezone(pytz.timezone(tz_name)).strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            pass
    return n.strftime("%Y-%m-%d %H:%M:%S UTC")
