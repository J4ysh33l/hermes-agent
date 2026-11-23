"""Points, levels and the streak, kept in ``$HERMES_HOME/myday/state.json``.

The streak counts days on which every task due that day (or overdue) was done. It grows the moment
the last one is ticked off (the celebration), and resets when a day closes with tasks still
pending (the morning card the next day shows that). A day with nothing due neither grows nor
breaks it. Every award has a key, so the same task, bill or log never scores twice.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from orchestrator.brief.store import default_state_dir as brief_state_dir

from .settings import load

KEEP_DAYS = 21


@dataclass(frozen=True)
class Level:
    number: int
    name: str
    floor: int  # points where this level starts
    next_at: int  # points where the next one starts


def level_for(points: int, names: tuple[str, ...]) -> Level:
    """Level n starts at 50·n·(n−1) points: 0, 100, 300, 600, 1000, 1500, 2100, …"""
    n = 1
    while 50 * (n + 1) * n <= points:
        n += 1
    name = names[n - 1] if n <= len(names) else f"{names[-1]} {n - len(names) + 1}"
    return Level(n, name, 50 * n * (n - 1), 50 * (n + 1) * n)


def progress_bar(done: int, total: int, width: int = 10) -> str:
    filled = 0 if total <= 0 else min(width, round(width * done / total))
    return "▰" * filled + "▱" * (width - filled)


@dataclass(frozen=True)
class Event:
    """Something worth an animation: ``clear`` (all done, streak grew) or ``broken``."""

    kind: str
    streak: int  # the streak after a clear, or the one that was lost


class State:
    """The JSON state. Writes are atomic; one process at a time is assumed (cron tick and a
    command can overlap, so every writer re-reads first via ``State.load``)."""

    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self.path = path
        self.data = data
        self.data.setdefault("points", 0)
        self.data.setdefault("streak", 0)
        self.data.setdefault("best", 0)
        for key in ("days", "awarded", "day_points", "sent", "listing", "top"):
            self.data.setdefault(key, {})

    @classmethod
    def load(cls, state_dir: Path) -> State:
        path = state_dir / "state.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        return cls(path, data)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=1, ensure_ascii=False)
        tmp.replace(self.path)

    # ---- points -------------------------------------------------------------------------------

    @property
    def points(self) -> int:
        return int(self.data["points"])

    @property
    def streak(self) -> int:
        return int(self.data["streak"])

    @property
    def best(self) -> int:
        return int(self.data["best"])

    def award(self, key: str, points: int, today: date) -> int:
        """Add ``points`` once per ``key``; returns what was added (0 if already awarded)."""
        if key in self.data["awarded"]:
            return 0
        self.data["awarded"][key] = today.isoformat()
        self.data["points"] = max(0, self.points + points)
        day = today.isoformat()
        self.data["day_points"][day] = self.data["day_points"].get(day, 0) + points
        return points

    def points_on(self, day: date) -> int:
        return int(self.data["day_points"].get(day.isoformat(), 0))

    # ---- what was last shown, so "/day done 2" means the 2nd line you saw --------------------

    def remember(self, kind: str, keys: list[str]) -> None:
        self.data["listing"][kind] = keys

    def pick(self, kind: str, numbers: list[int]) -> list[str]:
        shown = self.data["listing"].get(kind) or []
        bad = [n for n in numbers if not 1 <= n <= len(shown)]
        if bad:
            raise ValueError(f"No item {bad[0]} on the last list (it had {len(shown)}). Show it again first.")
        return [shown[n - 1] for n in numbers]

    # ---- top picks, once-only sends ------------------------------------------------------------

    def top_for(self, day: date) -> list[str]:
        return list(self.data["top"].get(day.isoformat(), []))

    def set_top(self, day: date, ids: list[str]) -> None:
        self.data["top"] = {day.isoformat(): ids}

    def once(self, key: str) -> bool:
        """True the first time ``key`` is seen (a reminder, a wrap-up); then False."""
        if key in self.data["sent"]:
            return False
        self.data["sent"][key] = True
        return True

    # ---- the streak ----------------------------------------------------------------------------

    def day(self, day: date) -> dict[str, Any]:
        return self.data["days"].setdefault(day.isoformat(), {"seen": [], "pending": [], "cleared": False})

    def observe(self, today: date, pending: list[str], done: list[str], all_clear_points: int) -> Event | None:
        """Record what is due today (or overdue): still open, and done today. Grows the streak
        the moment nothing is open any more."""
        record = self.day(today)
        record["seen"] = sorted(set(record["seen"]) | set(pending) | set(done))
        record["pending"] = sorted(pending)
        if pending or not record["seen"] or record["cleared"]:
            return None
        record["cleared"] = True
        self.data["streak"] = self.streak + 1
        self.data["best"] = max(self.best, self.streak)
        self.award(f"clear:{today.isoformat()}", all_clear_points, today)
        return Event("clear", self.streak)

    def close_days(self, today: date) -> Event | None:
        """Close every recorded day before ``today``: one left with pending tasks breaks the streak."""
        broken: Event | None = None
        for key in sorted(self.data["days"]):
            record = self.data["days"][key]
            if key >= today.isoformat() or record.get("closed"):
                continue
            record["closed"] = True
            if record["pending"]:
                broken = Event("broken", max(self.streak, broken.streak if broken else 0))
                self.data["streak"] = 0
        self._trim(today)
        return broken

    def _trim(self, today: date) -> None:
        cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
        for key in ("days", "day_points"):
            self.data[key] = {k: v for k, v in self.data[key].items() if k >= cutoff}
        self.data["awarded"] = {k: v for k, v in self.data["awarded"].items() if v >= cutoff}
        self.data["sent"] = {k: v for k, v in self.data["sent"].items() if k.rsplit(":", 1)[-1] >= cutoff}


def badge(state_dir: Path | None = None) -> str:
    """The line under every Telegram message: streak and level. Empty before My day is set up.
    Reads two local files; never the network."""
    state_dir = state_dir or brief_state_dir().parent / "myday"
    if not (state_dir / "state.json").is_file():
        return ""
    state = State.load(state_dir)
    level = level_for(state.points, load(state_dir).level_names)
    flame = "🔥" if state.streak else "🧊"
    return f"{flame} {state.streak} · Lv {level.number} {level.name} · {state.points} pts"


def with_badge(text: str, state_dir: Path | None = None) -> str:
    line = badge(state_dir)
    return f"{text}\n\n{line}" if text and line else text


@dataclass(frozen=True)
class Reply:
    """What a command answers: text, plus events that earn an animation."""

    text: str
    events: tuple[Event, ...] = ()
