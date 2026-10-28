"""
Global Date & Time Formatting Utilities for FraudOps AI (Backend).
Converts any UTC datetime, naive datetime, or timestamp string into Indian Standard Time (IST / UTC+05:30)
without altering the database schema or underlying persisted storage records.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Union

# Indian Standard Time (IST) offset is UTC + 5:30
IST_OFFSET = timezone(timedelta(hours=5, minutes=30))


def ist_now() -> datetime:
    """Returns the current datetime in Indian Standard Time (IST)."""
    return datetime.now(IST_OFFSET)


def utc_to_ist(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Converts a datetime object (naive or timezone-aware UTC) into IST.
    If the datetime is naive, assumes UTC by default.
    """
    if dt is None:
        return None

    if dt.tzinfo is None:
        # Naive datetime: assume UTC
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(IST_OFFSET)


def format_to_ist(
    dt_or_str: Optional[Union[datetime, str, int, float]],
    include_time: bool = True,
    time_only: bool = False,
    date_only: bool = False,
    show_timezone: bool = False,
    fallback: str = "—"
) -> str:
    """
    Global helper function to convert any date representation to IST formatted string.
    
    Examples:
        format_to_ist(datetime.now(timezone.utc)) -> "28/10/2026, 11:00:00 AM"
        format_to_ist("2026-10-28T05:30:00Z")     -> "28/10/2026, 11:00:00 AM"
    """
    if dt_or_str is None or dt_or_str == "":
        return fallback

    dt: Optional[datetime] = None

    if isinstance(dt_or_str, datetime):
        dt = dt_or_str
    elif isinstance(dt_or_str, (int, float)):
        # Epoch timestamp
        timestamp = dt_or_str if dt_or_str > 1e11 else dt_or_str
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    elif isinstance(dt_or_str, str):
        trimmed = dt_or_str.strip()
        if not trimmed:
            return fallback
        try:
            # Handle standard ISO formats
            if trimmed.endswith("Z"):
                dt = datetime.fromisoformat(trimmed[:-1]).replace(tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(trimmed)
        except Exception:
            try:
                dt = datetime.strptime(trimmed, "%Y-%m-%d %H:%M:%S")
            except Exception:
                return fallback
    else:
        return fallback

    if dt is None:
        return fallback

    ist_dt = utc_to_ist(dt)
    if ist_dt is None:
        return fallback

    tz_suffix = " IST" if show_timezone else ""

    if time_only:
        return ist_dt.strftime("%I:%M:%S %p") + tz_suffix
    elif date_only:
        return ist_dt.strftime("%d/%m/%Y")
    elif not include_time:
        return ist_dt.strftime("%d/%m/%Y")
    else:
        return ist_dt.strftime("%d/%m/%Y, %I:%M:%S %p") + tz_suffix
