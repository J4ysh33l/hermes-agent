"""Clock words for the fixed commands: ``15:00``, ``3pm``, ``3:30pm``, ``15:00-18:00``, ``30m``,
``1h``, ``today``, ``tomorrow``, ``mon``, ``2026-11-25``. Anything else goes to the model."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

CLOCK = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", re.IGNORECASE)
LENGTH = re.compile(r"^(?:(\d+)\s*h)?\s*(?:(\d+)\s*(?:m|min|mins)?)?$", re.IGNORECASE)
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
FULL_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def clock(word: str) -> time | None:
    """'15:00', '3pm', '3:30 pm'. A bare '3' is refused: it could be 3 am or 3 pm."""
    m = CLOCK.match(word.strip())
    if not m or (m.group(2) is None and m.group(3) is None):
        return None
    hour, minute, half = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if half:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if half == "pm" else 0)
    return time(hour, minute) if hour < 24 and minute < 60 else None


def window(word: str) -> tuple[time, time] | None:
    """'15:00-18:00' or '3pm-6pm' (an end without am/pm borrows the start's)."""
    start, sep, end = word.partition("-")
    if not sep:
        return None
    half = re.search(r"(am|pm)$", start.strip(), re.IGNORECASE)
    if half is None and (h := re.search(r"(am|pm)$", end.strip(), re.IGNORECASE)) and ":" not in start:
        start += h.group(1)
    a, b = clock(start), clock(end)
    return (a, b) if a and b and b > a else None


def length(word: str) -> int | None:
    """'15m', '30min', '1h', '1h30m' → minutes. Needs a unit so names and numbers don't mix."""
    if not re.search(r"\d\s*(h|m|min|mins)$", word.strip(), re.IGNORECASE):
        return None
    m = LENGTH.match(word.strip())
    if not m:
        return None
    minutes = int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    return minutes if 5 <= minutes <= 480 else None


def day(word: str, today: date) -> date | None:
    low = word.strip().lower()
    if low == "today":
        return today
    if low == "tomorrow":
        return today + timedelta(days=1)
    if low in WEEKDAYS or low in FULL_DAYS:
        ahead = (WEEKDAYS.index(low[:3]) - today.weekday()) % 7
        return today + timedelta(days=ahead)
    try:
        return date.fromisoformat(low)
    except ValueError:
        return None


def show_time(when: datetime) -> str:
    return when.strftime("%I:%M %p").lstrip("0")


def show_day(when: date, today: date) -> str:
    if when == today:
        return "today"
    if when == today + timedelta(days=1):
        return "tomorrow"
    return when.strftime("%a %d %b")
