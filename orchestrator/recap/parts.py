"""The parts of the evening recap. Each returns ``Line``s; the recap sorts and groups them.

- Approvals: plans waiting for your yes (payslips, a payslip sheet with problems, interviews, Slack,
  meetings), read from their files without touching them. One that expired unapproved stays in the
  recap every evening until you make it again or say ``no`` (``orchestrator.expiry``).
- HR mail: urgent and people mails still waiting for a reply, as the last ``/hr inbox`` sweep left them.
- To Do: tasks and bills overdue or due within ``SOON_DAYS`` (My day's lists).
- Calendar: Outlook events within ``CALENDAR_DAYS`` whose subject names a deadline.
- Meetings (Smriti): ended meetings you have not answered yet, and documents asked for but not delivered.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

from orchestrator import expiry
from orchestrator.brief.net import HttpError
from orchestrator.brief.sources import outlook
from orchestrator.hr import inbox
from orchestrator.notes import store as notes_store
from orchestrator.notes.work import ref
from orchestrator.hr import settings as hr_settings
from orchestrator.myday import day
from orchestrator.myday.dates import label
from orchestrator.myday.session import Session
from orchestrator.outreach import settings as outreach_settings

IST = ZoneInfo("Asia/Kolkata")  # interview slots are saved in IST
SOON_DAYS = 3
CALENDAR_DAYS = 7
GRAPH = "https://graph.microsoft.com/v1.0"
DEADLINE = re.compile(r"\b(deadline|due|last date|submission|submit|expir\w*|renewal|closes?|cut-?off)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Line:
    when: date  # sorts the recap; overdue and missed come first
    text: str
    waiting: bool = False  # an approval or a mail waiting on you, rather than a dated item


Check = Callable[[dict, float], list[str]]  # (the saved plan, now) → why it can no longer be resumed


def _files_exist(data: dict, _now: float) -> list[str]:
    return [f"{Path(i['file']).name} is gone" for i in data.get("items", []) if not Path(i["file"]).is_file()]


def _sheet_exists(data: dict, _now: float) -> list[str]:
    return [] if Path(data.get("sheet", "")).is_file() else ["the sheet file is gone"]


def _still_unanswered(home: Path) -> Check:
    def check(data: dict, _now: float) -> list[str]:
        items = inbox.Store(home / "hr" / "inbox.json").items
        return [f"{i['name']}'s mail was answered meanwhile" for i in data.get("items", [])
                if items.get(i["key"], {}).get("done") == "replied"]
    return check


def _ist(stamp: str) -> datetime:
    when = datetime.fromisoformat(stamp)
    return when if when.tzinfo else when.replace(tzinfo=IST)


def _slots_ahead(data: dict, now: float) -> list[str]:
    return [f"{c['name']}'s slot ({_ist(c['start']):%-d %b %H:%M}) has passed"
            for c in data.get("candidates", []) if _ist(c["start"]).timestamp() <= now]


def _times_ahead(data: dict, now: float) -> list[str]:
    late = []
    for line in data.get("lines", []):
        for act in line.get("actions", []):
            when = act.get("post_at") or (datetime.fromisoformat(act["start"][:19]).replace(tzinfo=UTC).timestamp()
                                          if act.get("start") else 0)
            if when and when <= now:
                late.append(f"{line['label'].split(' — ')[0]}: its time has passed")
    return late


@dataclass(frozen=True)
class Pending:
    """A file another workflow keeps while a plan waits for your yes."""

    path: Path
    name: str
    command: str  # where to look while it waits
    cancel: str  # drops it, waiting or expired
    minutes: int
    check: Check  # before /resume: what makes it unsafe to send now
    show: tuple[str, str] | None  # the command (name, words) whose answer previews it after /resume


def pending_files(home: Path) -> list[Pending]:
    brief = home / "brief"
    hr_minutes = hr_settings.load(brief).preview_minutes
    out_minutes = outreach_settings.load(brief).preview_minutes
    return [
        Pending(home / "hr" / "pending.json", "Payslip batch", "/hr payslip show", "/hr payslip no", hr_minutes,
                _files_exist, ("hr", "payslip show")),
        Pending(home / "hr" / "blocked.json", "Payslip sheet with problems", "/hr payslip skip", "/hr payslip no",
                hr_minutes, _sheet_exists, None),
        Pending(home / "hr" / "interview.json", "Interview batch", "/hr interview show", "/hr interview no",
                hr_minutes, _slots_ahead, ("hr", "interview show")),
        Pending(home / "hr" / "reply.json", "HR reply", "/hr reply show", "/hr reply no", hr_minutes,
                _still_unanswered(home), ("hr", "reply show")),
        Pending(home / "hr" / "offer.json", "Offer letter", "/hr offer show", "/hr offer no", hr_minutes,
                _files_exist, ("hr", "offer show")),
        Pending(brief / "outreach" / "pending-slack.json", "Slack messages", "/slack show", "/slack no", out_minutes,
                _times_ahead, ("slack", "show")),
        Pending(brief / "outreach" / "pending-meet.json", "Meetings", "/meet show", "/meet no", out_minutes,
                _times_ahead, ("meet", "show")),
    ]


def listing_path(home: Path) -> Path:
    """The expired plans the last recap numbered, for ``/resume <n>``."""
    return home / "recap" / "listing.json"


def approvals(session: Session, home: Path) -> list[Line]:
    lines, numbered = [], []
    for item in pending_files(home):
        source = item.path if item.path.is_file() else expiry.marker(item.path)
        if not source.is_file():
            continue
        created = json.loads(source.read_text(encoding="utf-8"))["created"]
        ends = datetime.fromtimestamp(created + item.minutes * 60, session.tz)
        if ends <= session.local_now:
            numbered.append(str(item.path))
            n = len(numbered)
            lines.append(Line(ends.date(), f"⌛ {n}. {item.name}: expired {ends:%-d %b %H:%M} without your yes · "
                                           f"/resume {n} to bring it back, or {item.cancel} to drop it", waiting=True))
        else:
            lines.append(Line(ends.date(), f"✍️ {item.name}: waiting for your yes until {ends:%H:%M} · "
                                           f"{item.command}", waiting=True))
    listing_path(home).parent.mkdir(parents=True, exist_ok=True)
    listing_path(home).write_text(json.dumps(numbered), encoding="utf-8")
    return lines


def hr_mail(session: Session, home: Path) -> list[Line]:
    store = inbox.Store(home / "hr" / "inbox.json")
    lines = []
    for _, item in store.open_items():
        waited = inbox.age(item["received"], session.local_now)
        mark = inbox.BY_KEY[item["cat"]].label.split()[0]
        lines.append(Line(date.fromisoformat(item["received"][:10]),
                          f"{mark} HR: {item['name']} — {item['subject']} ({waited}, no reply) · /hr inbox show",
                          waiting=True))
    return lines


def tasks(session: Session) -> list[Line]:
    board = day.board(session)
    bills_list = day.list_ids(session)[1]
    today, lines = session.today, []
    for task in board.due + [t for t in board.soon if (t.due - today).days <= SOON_DAYS]:
        mark = "💳" if task.list_id == bills_list else "▫️"
        lines.append(Line(task.due, f"{mark} {task.title} — {label(task.due, today)}"))
    return lines


def calendar(session: Session) -> list[Line]:
    start = datetime.combine(session.today, time.min, tzinfo=session.tz)
    params = {"startDateTime": start.isoformat(),
              "endDateTime": (start + timedelta(days=CALENDAR_DAYS + 1)).isoformat(),
              "$select": "subject,start,isCancelled,isAllDay", "$orderby": "start/dateTime", "$top": 100}
    headers = {"Authorization": f"Bearer {session.token(outlook.MEETING_SCOPES)}",
               "Prefer": 'outlook.timezone="India Standard Time"'}
    try:
        rows = session.http.request("GET", GRAPH + "/me/calendarView", params=params, headers=headers).json()
    except HttpError as exc:
        raise RecapError(f"HTTP {exc.status}") from None
    lines = []
    for row in rows.get("value") or []:
        subject = row.get("subject") or ""
        if row.get("isCancelled") or not DEADLINE.search(subject):
            continue
        when = datetime.fromisoformat(row["start"]["dateTime"][:19])
        at = "" if row.get("isAllDay") else f" {when:%H:%M}"
        lines.append(Line(when.date(), f"🗓 {subject} — {label(when.date(), session.today)}{at}"))
    return lines


def meetings(session: Session, home: Path) -> list[Line]:
    """Read only: Smriti's own cron asks and makes; the recap reminds."""
    store = notes_store.Store(home)
    lines = []
    for key, m in store.recent(session.local_now):
        when = datetime.fromisoformat(m["start"]).date()
        if not m["asked"] and not m["skipped"]:
            lines.append(Line(when, f"🎙 {notes_store.label(m)}: what do you need? /notes {ref(m['subject'])} "
                                    "summary tasks prd · or skip", waiting=True))
        for req in m["requests"]:
            name = req["what"] if req["kind"] == "doc" else req["kind"]
            if req["status"] in ("queued", "claude"):
                lines.append(Line(when, f"📝 {name} for {notes_store.label(m)}: {req['note'] or 'in the queue'}",
                                  waiting=True))
            elif req["status"] == "failed":
                lines.append(Line(when, f"⚠️ {name} for {notes_store.label(m)} failed: {req['note']} · ask again "
                                        f"with /notes {ref(m['subject'])} {req['kind']}", waiting=True))
    return lines


class RecapError(Exception):
    """A part could not be read; the recap names it and carries on."""
