"""Packs meetings back to back from the start of the window: each one's own length, then the gap.
It never spreads meetings across the free window; time left at the end stays free.

A busy event in your calendar is kept the gap away on both sides. A meeting that would run past
the window's end is listed as not fitting; later, shorter ones may still fit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Slot(Generic[T]):
    who: T
    start: datetime
    end: datetime


def first_start(start: datetime, now: datetime) -> datetime:
    """The window start, or the next 5-minute mark if the start already passed."""
    if start >= now:
        return start
    late = now.replace(second=0, microsecond=0)
    if late < now:
        late += timedelta(minutes=1)
    return late + timedelta(minutes=(5 - late.minute % 5) % 5)


def _clash(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]], gap: timedelta) -> datetime | None:
    """End of the first busy block too close to [start, end), plus the gap; None if clear."""
    for b_start, b_end in busy:
        if b_start < end + gap and b_end + gap > start:
            return b_end + gap
    return None


def pack(wanted: list[tuple[T, int]], start: datetime, end: datetime | None,
         busy: list[tuple[datetime, datetime]], gap_minutes: int) -> tuple[list[Slot[T]], list[T]]:
    """``wanted``: (who, minutes) in the order to place them. Returns (slots, who didn't fit)."""
    gap = timedelta(minutes=gap_minutes)
    cursor = start
    placed: list[Slot[T]] = []
    left: list[T] = []
    for who, minutes in wanted:
        length = timedelta(minutes=minutes)
        at = cursor
        while (later := _clash(at, at + length, busy, gap)) is not None:
            at = later
        if end is not None and at + length > end:
            left.append(who)
            continue
        placed.append(Slot(who, at, at + length))
        cursor = at + length + gap
    return placed, left
