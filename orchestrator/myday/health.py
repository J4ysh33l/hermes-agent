"""Health nudges and a private log. Nudges are fixed texts at fixed times (myday.yaml); your
replies go to ``$HERMES_HOME/myday/health.jsonl`` on the host only: never to To Do, never to a
model."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

from .errors import MyDayError
from .game import Reply
from .session import Session

KINDS = ("weight", "food", "water", "workout", "sleep")
WINDOW = timedelta(minutes=45)  # a nudge missed by more than this (host was off) is skipped, not sent late
FOOD_SCORED = 3  # food logs that earn points per day


def _path(session: Session):
    return session.state_dir / "health.jsonl"


def entries(session: Session, since: date) -> list[dict]:
    path = _path(session)
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r["day"] >= since.isoformat()]


def _number(text: str, kind: str) -> float:
    m = re.search(r"\d+(?:\.\d+)?", text)
    if not m:
        raise MyDayError(f"/health {kind} needs a number, e.g. /health {kind} {'82.4' if kind == 'weight' else '2'}")
    return float(m.group())


def log(session: Session, kind: str, words: list[str]) -> Reply:
    text = " ".join(words).strip()
    if not text:
        raise MyDayError(f"What to log? e.g. /health {kind} " + {"weight": "82.4", "food": "dal, rice, salad",
                         "water": "2 (litres)", "workout": "30m walk", "sleep": "7.5 (hours)"}[kind])
    value: float | str = _number(text, kind) if kind in ("weight", "water", "sleep") else text
    today = session.today
    row = {"day": today.isoformat(), "at": session.local_now.strftime("%H:%M"), "kind": kind, "value": value}
    path = _path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    count = sum(1 for r in entries(session, today) if r["kind"] == kind and r["day"] == today.isoformat())
    got = 0
    if kind != "food" or count <= FOOD_SCORED:
        slot = f"food{count}" if kind == "food" else kind
        got = session.state.award(f"health:{slot}:{today.isoformat()}", session.settings.points.health_log, today)
    return Reply(f"📝 {kind}: {value}" + (f"  +{got}" if got else "") + "\n" + _today_line(session))


def _today_line(session: Session) -> str:
    rows = [r for r in entries(session, session.today)]
    food = sum(r["kind"] == "food" for r in rows)
    water = sum(float(r["value"]) for r in rows if r["kind"] == "water")
    moved = any(r["kind"] == "workout" for r in rows)
    return f"Today: 🍽 {food} meals · 💧 {water:g} L · {'🏃 moved' if moved else '🏃 not yet'}"


def summary(session: Session) -> Reply:
    today = session.today
    week = entries(session, today - timedelta(days=6))
    weights = [(r["day"], float(r["value"])) for r in entries(session, today - timedelta(days=60)) if r["kind"] == "weight"]
    lines = ["**Health**", _today_line(session)]
    if weights:
        last = weights[-1][1]
        trend = ""
        if len(weights) > 1:
            delta = last - weights[-2][1]
            trend = f" ({'+' if delta >= 0 else ''}{delta:.1f} since {weights[-2][0][5:]})"
        lines.append(f"⚖️ {last:g} kg{trend}")
    workouts = sum(r["kind"] == "workout" for r in week)
    days_water = {r["day"] for r in week if r["kind"] == "water"}
    lines.append(f"Last 7 days: {workouts} workouts · water logged on {len(days_water)} days")
    lines.append("/health weight 82.4 · food … · water 2 · workout 30m walk · sleep 7.5")
    return Reply("\n".join(lines))


def nudges(session: Session) -> list[str]:
    """Nudge texts due now (once per slot). One missed by more than WINDOW is dropped."""
    now = session.local_now
    day = now.strftime("%a").lower()[:3]
    due = []
    for nudge in session.settings.nudges:
        at = datetime.combine(now.date(), nudge.at, tzinfo=session.tz)
        if day in nudge.days and at <= now < at + WINDOW and \
                session.state.once(f"nudge-{nudge.name}:{now.date().isoformat()}"):
            due.append(nudge.text)
    return due
