"""Shared helpers: dates (DD/MM/YYYY), decimals, normalisation, hashing."""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from functools import lru_cache
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings

DISPLAY_DATE = "%d/%m/%Y"
DISPLAY_DATETIME = "%d/%m/%Y %H:%M"
TWO = Decimal("0.01")


# Used when the operating system has no time-zone database (Windows) and the `tzdata` package is missing.
_FIXED_OFFSETS = {"Asia/Kolkata": timedelta(hours=5, minutes=30), "Asia/Calcutta": timedelta(hours=5, minutes=30),
                  "UTC": timedelta(0)}


@lru_cache
def _zone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        if name in _FIXED_OFFSETS:
            return timezone(_FIXED_OFFSETS[name], name)
        raise


def tz() -> tzinfo:
    return _zone(get_settings().timezone)


def now() -> datetime:
    """Current time in the configured company timezone (naive, for DATETIME columns)."""
    return datetime.now(tz()).replace(tzinfo=None, microsecond=0)


def today() -> date:
    return now().date()


def add_months(d: date, months: int) -> date:
    import calendar
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def fmt_date(v: Any) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, datetime):
        return v.strftime(DISPLAY_DATETIME) if (v.hour or v.minute) else v.strftime(DISPLAY_DATE)
    if isinstance(v, date):
        return v.strftime(DISPLAY_DATE)
    return str(v)


_DATE_PATTERNS = [
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y", "%d-%b-%Y", "%d-%b-%y",
    "%d %b %Y", "%d/%b/%Y", "%Y/%m/%d", "%m/%d/%Y",
]
_DT_PATTERNS = [
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M",
    "%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y %I:%M %p",
]


def parse_date(v: Any, fmt: str | None = None) -> date | None:
    """Parse a date from ISO, DD/MM/YYYY and common Indian statement formats.

    Ambiguous day/month values are always read day-first (Indian convention)
    unless an explicit template format says otherwise.
    """
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)):  # Excel serial date
        from datetime import timedelta
        return date(1899, 12, 30) + timedelta(days=int(v))
    s = str(v).strip()
    if not s:
        return None
    patterns = [fmt] if fmt else []
    patterns += _DATE_PATTERNS
    for p in patterns:
        try:
            return datetime.strptime(s, p).date()
        except (ValueError, TypeError):
            continue
    dt = parse_datetime(s)
    if dt:
        return dt.date()
    raise ValueError(f"Invalid date '{s}' (expected DD/MM/YYYY)")


def parse_datetime(v: Any, fmt: str | None = None) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, date):
        return datetime.combine(v, time())
    s = str(v).strip()
    patterns = ([fmt] if fmt else []) + _DT_PATTERNS
    for p in patterns:
        try:
            return datetime.strptime(s, p)
        except (ValueError, TypeError):
            continue
    for p in _DATE_PATTERNS:
        try:
            return datetime.strptime(s, p)
        except ValueError:
            continue
    return None


def parse_time(v: Any) -> time | None:
    if v in (None, ""):
        return None
    if isinstance(v, time):
        return v
    if isinstance(v, datetime):
        return v.time()
    s = str(v).strip()
    for p in ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"):
        try:
            return datetime.strptime(s, p).time()
        except ValueError:
            continue
    raise ValueError(f"Invalid time '{s}'")


_CURRENCY_RE = re.compile(r"[₹$€£,\s]|INR|Rs\.?", re.I)


def to_decimal(v: Any, places: str | None = None) -> Decimal | None:
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        d = v
    elif isinstance(v, (int, float)):
        d = Decimal(str(v))
    else:
        s = _CURRENCY_RE.sub("", str(v)).strip()
        neg = False
        if s.startswith("(") and s.endswith(")"):
            s, neg = s[1:-1], True
        if s.upper().endswith("CR"):
            s = s[:-2].strip()
        elif s.upper().endswith("DR"):
            s, neg = s[:-2].strip(), True
        if s in ("", "-"):
            return None
        try:
            d = Decimal(s)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid number '{v}'") from exc
        if neg:
            d = -d
    if places:
        d = d.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return d


def money(v: Any) -> Decimal:
    d = to_decimal(v)
    return (d or Decimal("0")).quantize(TWO, rounding=ROUND_HALF_UP)


_VEH_RE = re.compile(r"[^A-Z0-9]")


def normalize_vehicle_number(v: Any) -> str:
    """'TN-01 AB 1234' / 'tn01ab1234' / 'TN 01 AB-1234' -> 'TN01AB1234'."""
    if v is None:
        return ""
    return _VEH_RE.sub("", str(v).upper())


def normalize_text(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().upper()


def sha256_of(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        if isinstance(p, Decimal):
            p = format(p.normalize(), "f")
        elif isinstance(p, (date, datetime)):
            p = p.isoformat()
        h.update(("" if p is None else str(p)).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jsonable(v: Any) -> Any:
    """Convert ORM/DB values to JSON-safe primitives (ISO dates, str decimals)."""
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, (date, time)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v
