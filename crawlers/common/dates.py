from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .text import clean_text


VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

DATETIME_FORMATS = [
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y-%m-%d",
]


def try_parse_datetime(raw: Optional[Any]) -> Optional[datetime]:
    raw_text = clean_text(raw)
    if not raw_text:
        return None

    if raw_text.endswith("Z"):
        raw_text = raw_text[:-1] + "+0000"

    for fmt in DATETIME_FORMATS:
        try:
            parsed = datetime.strptime(raw_text, fmt)
        except ValueError:
            continue

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=VN_TZ)
        return parsed.astimezone(VN_TZ)

    return None


def format_datetime(raw: Optional[Any]) -> Optional[str]:
    parsed = try_parse_datetime(raw)
    if not parsed:
        return None
    return parsed.strftime("%Y-%m-%d %H:%M")


def get_cutoff_datetime(days: Optional[int], now: Optional[datetime] = None) -> Optional[datetime]:
    if days is None:
        return None
    current = now or datetime.now(VN_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=VN_TZ)
    return current.astimezone(VN_TZ) - timedelta(days=days)


def is_within_days(
    published_at: Optional[str],
    days: Optional[int],
    now: Optional[datetime] = None,
) -> bool:
    if days is None:
        return True

    parsed = try_parse_datetime(published_at)
    if not parsed:
        return True

    cutoff = get_cutoff_datetime(days, now=now)
    return cutoff is None or parsed >= cutoff
