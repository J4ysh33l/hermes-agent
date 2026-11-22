"""Plans waiting for your approval, the send log and the daily cap.

A plan is numbered lines; each line holds the actions for one person or one event (an invite and
the Slack note that goes with it). ``/slack yes`` runs the waiting Slack plan, ``/meet yes`` the
waiting meeting plan; ``yes 1,3`` runs only those lines. A plan expires after
``preview_minutes``. One waiting plan per kind: a new draft replaces the old one.

Files in ``$HERMES_HOME/brief/outreach/``: ``pending-slack.json``, ``pending-meet.json``, and
``sent.jsonl`` (one line per message, invite or post actually sent, with its time).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

Kind = Literal["slack", "meet"]
ActionKind = Literal["dm", "scheduled", "channel_post", "event"]


@dataclass(frozen=True)
class Action:
    """One thing sent. ``dm``: user_ids + text (several ids = one group DM). ``scheduled``: same,
    plus post_at. ``channel_post``: channel_id + text ({join} is filled from the event before it).
    ``event``: subject, body, start/end (ISO, UTC), attendees [{name, email}]."""

    kind: ActionKind
    text: str = ""
    user_ids: tuple[str, ...] = ()
    channel_id: str = ""
    post_at: int = 0
    subject: str = ""
    start: str = ""
    end: str = ""
    attendees: tuple[tuple[str, str], ...] = ()  # (name, email)
    teams: bool = True

    @classmethod
    def load(cls, raw: dict[str, Any]) -> Action:
        tuples = {"user_ids": tuple(raw.get("user_ids", ())),
                  "attendees": tuple(tuple(a) for a in raw.get("attendees", ()))}
        return cls(**{**raw, **tuples})


@dataclass(frozen=True)
class Line:
    label: str  # what you read in the preview: "Priya — 3:00–3:15 PM — <note>"
    actions: tuple[Action, ...]


@dataclass(frozen=True)
class Plan:
    kind: Kind
    title: str
    lines: tuple[Line, ...]
    created: float
    notes: tuple[str, ...] = ()  # shown under the lines: names not found, meetings that don't fit

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def load(cls, raw: dict[str, Any]) -> Plan:
        lines = tuple(Line(l["label"], tuple(Action.load(a) for a in l["actions"])) for l in raw["lines"])
        return cls(raw["kind"], raw["title"], lines, raw["created"], tuple(raw.get("notes", ())))

    def sends(self, picked: list[int] | None = None) -> int:
        return sum(len(self.lines[i].actions) for i in (picked if picked is not None else range(len(self.lines))))


def preview(plan: Plan, minutes: int) -> str:
    out = [f"**{plan.title}**", ""]
    out += [f"{n}. {line.label}" for n, line in enumerate(plan.lines, start=1)]
    if plan.notes:
        out += [""] + [f"⚠️ {n}" for n in plan.notes]
    if plan.lines:
        cmd = "/" + plan.kind
        edit = f" · {cmd} edit 2 <new text>" if plan.kind == "slack" else ""
        out += ["", f"Nothing is sent yet. {cmd} yes · {cmd} yes 1,3{edit} · {cmd} no",
                f"(expires in {minutes} min)"]
    return "\n".join(out)


def picks(arg: str, count: int) -> list[int] | None:
    """'' → all lines; '1,3' / '1-4' / '2 5' → those (0-based). None when a number is out of range."""
    if not arg.strip():
        return list(range(count))
    chosen: list[int] = []
    for part in re.split(r"[,\s]+", arg.strip()):
        a, _, b = part.partition("-")
        if not a.isdigit() or (b and not b.isdigit()):
            return None
        for n in range(int(a), int(b or a) + 1):
            if not 1 <= n <= count:
                return None
            if n - 1 not in chosen:
                chosen.append(n - 1)
    return chosen


@dataclass
class Store:
    state_dir: Path
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo("Asia/Kolkata"))

    @property
    def dir(self) -> Path:
        return self.state_dir / "outreach"

    def _pending(self, kind: Kind) -> Path:
        return self.dir / f"pending-{kind}.json"

    def save(self, plan: Plan) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._pending(plan.kind)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(plan.to_json(), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    def waiting(self, kind: Kind, now: float, minutes: int) -> Plan | None:
        path = self._pending(kind)
        if not path.is_file():
            return None
        plan = Plan.load(json.loads(path.read_text(encoding="utf-8")))
        if now - plan.created > minutes * 60:
            path.unlink()
            return None
        return plan

    def drop(self, kind: Kind) -> bool:
        path = self._pending(kind)
        found = path.is_file()
        if found:
            path.unlink()
        return found

    # -- send log and cap ---------------------------------------------------------------------
    def log(self, now: float, what: str, to: str, detail: str, ok: bool, note: str = "") -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        row = {"ts": datetime.fromtimestamp(now, self.tz).isoformat(timespec="seconds"), "what": what,
               "to": to, "detail": detail[:300], "ok": ok, "note": note[:200]}
        fd = os.open(self.dir / "sent.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def sent_today(self, now: float) -> int:
        path = self.dir / "sent.jsonl"
        if not path.is_file():
            return 0
        today = datetime.fromtimestamp(now, self.tz).date().isoformat()
        rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        return sum(1 for r in rows if r.get("ok") and r.get("ts", "").startswith(today))
