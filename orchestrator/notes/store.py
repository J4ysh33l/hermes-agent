"""What Smriti remembers: every Teams meeting you organised that has ended, what you asked for and
what was delivered. ``$HERMES_HOME/notes/meetings.json`` (0600); each meeting's transcript and
documents live in ``$HERMES_HOME/notes/<date>-<subject>/`` (0700).

You name a meeting by words from its subject (``/notes onboarding prd``) or ``last``; two matches are
listed, never guessed.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

Kind = Literal["summary", "tasks", "prd", "doc", "transcript"]
KINDS: tuple[Kind, ...] = ("summary", "tasks", "prd", "doc", "transcript")
Model = Literal["gemini", "claude"]
KEEP_DAYS = 60  # meetings older than this are forgotten (their folders stay on disk)


@dataclass(frozen=True)
class Meeting:
    key: str  # the Outlook event id (each occurrence of a recurring meeting has its own)
    subject: str
    start: datetime
    end: datetime
    join: str  # Teams join URL: finds the online meeting, its transcripts and recordings


class Store:
    def __init__(self, home: Path) -> None:
        self.root = home / "notes"
        self.path = self.root / "meetings.json"
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}
        self.meetings: dict[str, dict] = self.data.setdefault("meetings", {})

    def save(self) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=1)
        tmp.replace(self.path)

    # ---- meetings ---------------------------------------------------------------------------------

    def add(self, meeting: Meeting) -> bool:
        """Remember an ended meeting; False if already known."""
        if meeting.key in self.meetings:
            return False
        self.meetings[meeting.key] = {"subject": meeting.subject, "start": meeting.start.isoformat(),
                                      "end": meeting.end.isoformat(), "join": meeting.join, "asked": False,
                                      "skipped": False, "requests": [], "transcript": "", "source": ""}
        return True

    def prune(self, now: datetime) -> None:
        oldest = (now - timedelta(days=KEEP_DAYS)).isoformat()
        for key in [k for k, m in self.meetings.items() if m["end"] < oldest]:
            del self.meetings[key]

    def folder(self, key: str) -> Path:
        m = self.meetings[key]
        slug = re.sub(r"[^a-z0-9]+", "-", m["subject"].lower()).strip("-")[:40] or "meeting"
        path = self.root / f"{m['start'][:10]}-{slug}-{key[-6:].lower()}"
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        return path

    def recent(self, now: datetime, days: int = 7) -> list[tuple[str, dict]]:
        oldest = (now - timedelta(days=days)).isoformat()
        rows = [(k, m) for k, m in self.meetings.items() if m["end"] >= oldest]
        return sorted(rows, key=lambda kv: kv[1]["start"], reverse=True)

    def find(self, words: str, now: datetime) -> list[str]:
        """Meeting keys whose subject holds every word (any case), newest first; ``last`` = the latest."""
        rows = self.recent(now, KEEP_DAYS)
        if words.strip().lower() == "last":
            return [rows[0][0]] if rows else []
        wanted = words.lower().split()
        return [k for k, m in rows if wanted and all(w in m["subject"].lower() for w in wanted)]

    # ---- requests ---------------------------------------------------------------------------------

    def request(self, key: str, kind: Kind, model: Model, what: str = "") -> dict:
        """Queue one thing to make; the same kind and description asked again is not queued twice."""
        m = self.meetings[key]
        m["asked"] = True
        for req in m["requests"]:
            if req["kind"] == kind and req["what"] == what and req["status"] != "failed":
                return req
        req = {"id": uuid.uuid4().hex[:8], "kind": kind, "what": what, "model": model, "status": "queued",
               "attempts": 0, "note": "", "issue": 0}
        m["requests"].append(req)
        return req

    def open_requests(self) -> list[tuple[str, dict]]:
        return [(k, r) for k, m in self.meetings.items() for r in m["requests"] if r["status"] in ("queued", "claude")]

    def unasked(self) -> list[str]:
        return [k for k, m in self.meetings.items() if not m["asked"] and not m["skipped"]]

    # ---- the daily audio budget ------------------------------------------------------------------

    def audio_used(self, day: str) -> float:
        return float(self.data.get("audio_minutes", {}).get(day, 0))

    def add_audio(self, day: str, minutes: float) -> None:
        used = self.data.setdefault("audio_minutes", {})
        used[day] = round(used.get(day, 0) + minutes, 1)
        for old in sorted(used)[:-14]:
            del used[old]


def label(m: dict) -> str:
    start = datetime.fromisoformat(m["start"])
    return f"{start:%a %-d %b %H:%M} {m['subject']}"


def status_line(m: dict) -> str:
    if m["skipped"]:
        return "skipped"
    if not m["requests"]:
        return "not asked yet"
    marks = {"done": "✓", "queued": "…", "claude": "… Claude", "failed": "✗"}
    return " · ".join(f"{r['kind'] if r['kind'] != 'doc' else r['what'][:24]} {marks[r['status']]}"
                      for r in m["requests"])
