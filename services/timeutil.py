"""Timezone helpers. Servers (Vercel) run in UTC; appointments are local time."""
from datetime import datetime, timezone

from flask import current_app

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


def _tz():
    name = current_app.config.get("APP_TIMEZONE", "Asia/Kolkata")
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return timezone.utc


def now_local():
    """Current wall-clock time (naive) in the configured appointment timezone."""
    return datetime.now(_tz()).replace(tzinfo=None)


def today_str():
    return now_local().strftime("%Y-%m-%d")


def now_time_str():
    return now_local().strftime("%H:%M")


def now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
