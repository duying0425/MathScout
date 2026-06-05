from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_DISPLAY_TIMEZONE = "Asia/Shanghai"
UTC_PLUS_8 = timezone(timedelta(hours=8), name="UTC+08:00")


def utc_now() -> datetime:
    return datetime.now(UTC)


def display_datetime(
    value: datetime,
    *,
    timezone_name: str = DEFAULT_DISPLAY_TIMEZONE,
) -> datetime:
    source = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return source.astimezone(_display_timezone(timezone_name))


def _display_timezone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name in {DEFAULT_DISPLAY_TIMEZONE, "UTC+8", "UTC+08:00"}:
            return UTC_PLUS_8
        return UTC
