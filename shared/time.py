from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

# --- Internal override for testing ---
_current_time_override: Optional[datetime] = None

# === Time Zone Conversion ===

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

def to_user_timezone(dt: datetime, tz_name: str = "Asia/Jerusalem") -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        print(f"[WARN] Timezone {tz_name} not found. Using UTC fallback.")
        tz = timezone.utc
    return dt.astimezone(tz)

def from_user_timezone(local_dt: datetime, tz_name: str = "Asia/Jerusalem") -> datetime:
    """Convert a local user datetime (naive or tz-aware) into UTC."""
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        print(f"[WARN] Timezone {tz_name} not found. Using UTC fallback.")
        tz = timezone.utc
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=tz)
    return local_dt.astimezone(timezone.utc)


# === Time Access ===

def utcnow() -> datetime:
    return _current_time_override or datetime.now(timezone.utc)


def set_fake_utcnow(fake_time: datetime) -> None:
    global _current_time_override
    _current_time_override = fake_time


def clear_fake_utcnow() -> None:
    global _current_time_override
    _current_time_override = None

# === Time Parsing ===

def parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 string. Supports trailing 'Z'. Returns a datetime; no timezone normalization here."""
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


# === Time Checks ===

def is_future(dt: datetime) -> bool:
    return dt > utcnow()

def is_past(dt: datetime) -> bool:
    return dt < utcnow()

def in_range(dt: datetime, start: datetime, end: datetime) -> bool:
    return start <= dt <= end

# === Utilities ===

def minutes_ago(minutes: int) -> datetime:
    return utcnow() - timedelta(minutes=minutes)

def minutes_from_now(minutes: int) -> datetime:
    return utcnow() + timedelta(minutes=minutes)

def days_ago(days: int) -> datetime:
    return utcnow() - timedelta(days=days)

def days_from_now(days: int) -> datetime:
    return utcnow() + timedelta(days=days)

# === Constants ===

ONE_MINUTE = timedelta(minutes=1)
ONE_HOUR = timedelta(hours=1)
ONE_DAY = timedelta(days=1)
ONE_WEEK = timedelta(weeks=1)
