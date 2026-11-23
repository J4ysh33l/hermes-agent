"""The parts of the evening recap. Each returns ``Line``s; the recap sorts and groups them.

- Approvals: plans waiting for your yes (payslips, a payslip sheet with problems, interviews, Slack,
  meetings), read from their files without touching them. One that expired today is "missed";
  older ones are left out.
- HR mail: urgent and people mails still waiting for a reply, as the last ``/hr inbox`` sweep left them.
- To Do: tasks and bills overdue or due within ``SOON_DAYS`` (My day's lists).
- Calendar: Outlook events within ``CALENDAR_DAYS`` whose subject names a deadline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from orchestrator.brief.net import HttpError
from orchestrator.brief.sources import outlook
from orchestrator.hr import inbox
from orchestrator.hr import settings as hr_settings
from orchestrator.myday import day
from orchestrator.myday.dates import label
from orchestrator.myday.session import Session
from orchestrator.outreach import settings as outreach_settings

SOON_DAYS = 3
CALENDAR_DAYS = 7
GRAPH = "https://graph.microsoft.com/v1.0"
DEADLINE = re.compile(r"\b(deadline|due|last date|submission|submit|expir\w*|renewal|closes?|cut-?off)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Line:
    when: date  # sorts the recap; overdue and missed come first
    text: str
    waiting: bool = False  # an approval or a mail waiting on you, rather than a dated item


@dataclass(frozen=True)
class Pending:
    """A file another workflow keeps while a plan waits for your yes."""

    path: Path
    name: str
    command: str
    minutes: int


def pending_files(home: Path) -> list[Pending]:
    brief = home / "brief"
    hr_minutes = hr_settings.load(brief).preview_minutes
    out_minutes = outreach_settings.load(brief).preview_minutes
    return [
        Pending(home / "hr" / "pending.json", "Payslip batch", "/hr payslip show", hr_minutes),
        Pending(home / "hr" / "blocked.json", "Payslip sheet with problems", "/hr payslip check", hr_minutes),
        Pending(home / "hr" / "interview.json", "Interview batch", "/hr interview show", hr_minutes),
        Pending(brief / "outreach" / "pending-slack.json", "Slack messages", "/slack show", out_minutes),
        Pending(brief / "outreach" / "pending-meet.json", "Meetings", "/meet show", out_minutes),
    ]


def approvals(session: Session, home: Path) -> list[Line]:
    lines = []
    for item in pending_files(home):
        if not item.path.is_file():
            continue
        created = json.loads(item.path.read_text(encoding="utf-8"))["created"]
        ends = datetime.fromtimestamp(created + item.minutes * 60, session.tz)
        if ends <= session.local_now:
            if ends.date() != session.today:
                continue
            lines.append(Line(ends.date(), f"⌛ {item.name}: expired {ends:%-d %b %H:%M} without your yes · "
                                           "make it again to send it", waiting=True))
        else:
            lines.append(Line(ends.date(), f"✍️ {item.name}: waiting for your yes until {ends:%H:%M} · "
                                           f"{item.command}", waiting=True))
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


class RecapError(Exception):
    """A part could not be read; the recap names it and carries on."""
