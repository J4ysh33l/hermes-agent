"""Due-date words, read by script (no model): today, tomorrow, mon…sun, 25 nov, 25/11,
2026-11-25, +3 / 3d (days from today), next week (next Monday), someday (no date)."""

from __future__ import annotations

import re
from datetime import date, timedelta

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
SOMEDAY = "someday"
FILLERS = {"by", "on", "due", "for"}


class NoDate(ValueError):
    pass


def _day_month(day: int, month: int, today: date) -> date:
    when = date(today.year, month, day)
    return when if when >= today else date(today.year + 1, month, day)


def _relative(text: str, today: date) -> date | None:
    fixed = {"today": 0, "tod": 0, "tonight": 0, "tomorrow": 1, "tmrw": 1, "tmr": 1}
    if text in fixed:
        return today + timedelta(days=fixed[text])
    if text in ("next week", "nextweek"):
        return today + timedelta(days=7 - today.weekday())
    if m := re.fullmatch(r"\+?(\d{1,3})d?", text):
        return today + timedelta(days=int(m.group(1))) if text[0] == "+" or text.endswith("d") else None
    if text[:3] in WEEKDAYS and (len(text) == 3 or text.rstrip(".") in _long_weekdays()):
        return today + timedelta(days=(WEEKDAYS.index(text[:3]) - today.weekday()) % 7)
    return None


def _long_weekdays() -> set[str]:
    return {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "tues", "thur",
            "thurs", "wednes"}


def _absolute(text: str, today: date) -> date | None:
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text):
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?", text):
        day, month = int(m.group(1)), int(m.group(2))
        if m.group(3):
            year = int(m.group(3))
            return date(year + 2000 if year < 100 else year, month, day)
        return _day_month(day, month, today)
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3})[a-z]*|([a-z]{3})[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?", text)
    if m:
        day, mon = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        if mon in MONTHS:
            return _day_month(int(day), MONTHS.index(mon) + 1, today)
    return None


def parse(text: str, today: date) -> date | None:
    """A due date, or None for ``someday``. Raises NoDate when the words are not a date."""
    words = " ".join(text.lower().replace(",", " ").split())
    if words == SOMEDAY:
        return None
    try:
        found = _relative(words, today) or _absolute(words, today)
    except ValueError:  # 31/02 and friends
        found = None
    if found is None:
        raise NoDate(f"{text!r} is not a date. Try today, tomorrow, fri, 25 nov, 25/11, +3 or someday.")
    return found


def split_trailing(text: str, today: date, default: date | None) -> tuple[str, date | None]:
    """``"Call Apollo by fri"`` → ("Call Apollo", Friday). No date words at the end → default."""
    words = text.split()
    for take in (2, 1):
        if len(words) <= take:
            continue
        try:
            when = parse(" ".join(words[-take:]), today)
        except NoDate:
            continue
        head = words[:-take]
        if head and head[-1].lower() in FILLERS:
            head = head[:-1]
        if head:
            return " ".join(head), when
    return text.strip(), default


def label(when: date | None, today: date) -> str:
    if when is None:
        return "someday"
    delta = (when - today).days
    names = {0: "today", 1: "tomorrow", -1: "yesterday"}
    if delta in names:
        return names[delta]
    if delta < 0:
        return f"{-delta}d overdue"
    if delta < 7:
        return when.strftime("%a")
    return when.strftime("%-d %b")
