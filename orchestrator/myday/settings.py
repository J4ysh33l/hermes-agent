"""``$HERMES_HOME/myday/myday.yaml`` (hand-edited) → frozen Settings. Every key is optional; a
missing file means the defaults below (``myday.example.yaml`` shows them all)."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import time
from pathlib import Path
from typing import Any

import yaml

EXAMPLE = Path(__file__).resolve().parent / "myday.example.yaml"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class Points:
    task: int = 10
    top: int = 20  # a task you picked for your top 3 (instead of ``task``)
    all_clear: int = 50  # every task due today done
    bill_on_time: int = 15
    bill_late: int = 5
    snooze: int = -5
    health_log: int = 5  # at most once per nudge slot
    goal_step: int = 25
    goal_done: int = 100


@dataclass(frozen=True)
class Lists:
    """Microsoft To Do list names. An empty ``tasks`` means your default list ("Tasks")."""

    tasks: str = ""
    bills: str = "Bills"
    work_goals: str = "Goals · Work"
    personal_goals: str = "Goals · Personal"


@dataclass(frozen=True)
class Nudge:
    name: str
    at: time
    days: tuple[str, ...]  # subset of DAYS
    text: str


DEFAULT_NUDGES = (
    Nudge("weigh-in", time(9, 0), ("mon",), "⚖️ Monday weigh-in. Reply /health weight 82.4"),
    Nudge("lunch", time(14, 0), DAYS, "🍽 What did you eat? /health food dal, rice, salad"),
    Nudge("snack", time(18, 0), DAYS, "🍎 Evening check-in. /health food … or /health water 2"),
    Nudge("dinner", time(22, 0), DAYS, "🌙 Dinner and workout? /health food … · /health workout 30m walk"),
)

LEVEL_NAMES = ("Starter", "Mover", "Doer", "Finisher", "Closer", "Machine", "Legend")


@dataclass(frozen=True)
class Settings:
    timezone: str = "Asia/Kolkata"
    morning: time = time(7, 30)
    wrap: time = time(21, 30)  # evening wrap-up: what is left, before the day closes at midnight
    top_count: int = 3
    bill_remind_days: tuple[int, ...] = (3, 0)  # days before the due date
    bill_reminder_hour: int = 10  # To Do phone reminder time on those days
    calendar: bool = True  # today's Outlook meetings on the morning card
    points: Points = field(default_factory=Points)
    lists: Lists = field(default_factory=Lists)
    nudges: tuple[Nudge, ...] = DEFAULT_NUDGES
    level_names: tuple[str, ...] = LEVEL_NAMES


def _clock(value: Any) -> time:
    if isinstance(value, int):  # YAML reads 07:30 as a sexagesimal int (450)
        return time(value // 60, value % 60)
    hour, minute = str(value).strip().split(":")
    return time(int(hour), int(minute))


def _days(value: Any) -> tuple[str, ...]:
    if value in (None, "daily", "every day"):
        return DAYS
    words = [str(w).strip().lower()[:3] for w in (value if isinstance(value, list) else str(value).split(","))]
    bad = [w for w in words if w not in DAYS]
    if bad:
        raise ValueError(f"myday.yaml: unknown day {bad[0]!r} (use mon … sun or daily)")
    return tuple(words)


def _nudges(raw: list[dict[str, Any]]) -> tuple[Nudge, ...]:
    return tuple(Nudge(str(n["name"]), _clock(n["at"]), _days(n.get("days")), str(n["text"])) for n in raw)


def _sub(cls, raw: dict[str, Any] | None):
    names = {f.name for f in fields(cls)}
    unknown = set(raw or {}) - names
    if unknown:
        raise ValueError(f"myday.yaml: unknown key {min(unknown)!r} under {cls.__name__.lower()}")
    return cls(**(raw or {}))


def from_dict(raw: dict[str, Any]) -> Settings:
    base = Settings()
    return Settings(
        timezone=raw.get("timezone", base.timezone),
        morning=_clock(raw.get("morning", "07:30")),
        wrap=_clock(raw.get("wrap", "21:30")),
        top_count=int(raw.get("top_count", base.top_count)),
        bill_remind_days=tuple(int(d) for d in raw.get("bill_remind_days", base.bill_remind_days)),
        bill_reminder_hour=int(raw.get("bill_reminder_hour", base.bill_reminder_hour)),
        calendar=bool(raw.get("calendar", base.calendar)),
        points=_sub(Points, raw.get("points")),
        lists=_sub(Lists, raw.get("lists")),
        nudges=_nudges(raw["nudges"]) if "nudges" in raw else base.nudges,
        level_names=tuple(raw.get("level_names", base.level_names)),
    )


def load(state_dir: Path) -> Settings:
    path = state_dir / "myday.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
    return from_dict(raw or {})
