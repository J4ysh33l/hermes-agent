"""``/hr interview``: one Teams link for a block of interviews; each candidate is invited to their own slot.

One message, one row per line (or ``;`` between rows)::

    Date: 25/11/2026                       (also today, tomorrow, mon, 2026-11-25)
    Panel: rishabh@co.com, nidhi@co.com    (optional: the interviewers; they get the whole schedule)
    Asha Verma, Backend Engineer, 11:00, 11:30, asha@gmail.com

A row is Name, Position, Start, End, Email; the position may itself contain commas. Making the plan
calls no model and sends nothing. ``/hr interview yes`` then creates:

1. one Teams event on your calendar for the whole block, with the panel invited: that is the link;
2. one Outlook event per candidate for their slot only, carrying that link. Outlook emails each
   invite from your mailbox, with Accept/Decline. Candidates never see each other's names or emails.

Every slot shares the link, so candidates must not overlap: the check refuses overlapping slots.
External guests wait in the Teams lobby until someone on the panel admits them.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http
from orchestrator.outreach import graph, times
from orchestrator.outreach.build import fill
from orchestrator.outreach.errors import OutreachError

from .payroll import EMAIL
from .settings import Settings

ROW_HELP = "Name, Position, Start, End, Email (End is optional)"


@dataclass(frozen=True)
class Candidate:
    name: str
    position: str
    start: datetime
    end: datetime
    email: str

    @property
    def first(self) -> str:
        return self.name.split()[0]

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass(frozen=True)
class Parsed:
    day: date | None
    panel: tuple[str, ...]
    candidates: tuple[Candidate, ...]  # sorted by start
    problems: tuple[str, ...]  # any → nothing is saved


def _day(word: str, today: date) -> date | None:
    try:
        return datetime.strptime(word.strip(), "%d/%m/%Y").date()
    except ValueError:
        return times.day(word, today)


HEADERS = {"name": "name", "candidate": "name", "candidate name": "name", "position": "position", "role": "position",
           "email": "email", "email id": "email", "date": "date", "interview date": "date", "day": "date",
           "start": "start", "start time": "start", "from": "start", "end": "end", "end time": "end", "to": "end"}
TIMEISH = re.compile(r"\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)?", re.IGNORECASE)
TABLE_NEEDS = ("name", "position", "email", "start")  # date may be a 'Date:' line instead; end defaults


def _comma_row(line: str) -> dict[str, str] | None:
    """Name, Position, Start[, End], Email; the position may contain commas."""
    fields = [f.strip() for f in line.split(",")]
    if len(fields) < 4:
        return None
    has_end = len(fields) >= 5 and TIMEISH.fullmatch(fields[-3]) is not None  # '25:00' is a bad time, not a role
    cut = -3 if has_end else -2
    return {"name": fields[0], "position": ", ".join(fields[1:cut]).strip(), "start": fields[cut],
            "end": fields[-2] if has_end else "", "email": fields[-1], "date": ""}


def _check_row(who: str, row: dict[str, str]) -> list[str]:
    problems = [f"{who}: {label} '{row[label]}' is not a time like 11:00 or 3:30pm"
                for label in ("start", "end") if row[label] and times.clock(row[label]) is None]
    problems += [f"{who}: {field} is missing" for field in ("name", "position", "start") if not row[field]]
    if not EMAIL.match(row["email"]):
        problems.append(f"{who}: '{row['email']}' is not an email address")
    return problems


def _lines(text: str) -> tuple[list[str], list[tuple[int, dict[str, str]]], list[str]]:
    """(the Date:/Panel: lines, candidate rows with their line number, problems)."""
    settings_lines, rows, problems, header = [], [], [], None
    split = [part for line in text.split("\n") for part in ([line] if "\t" in line else line.split(";"))]
    for n, line in enumerate((l.rstrip() for l in split if l.strip()), start=1):
        key = line.partition(":")[0].strip().lower()
        if "\t" not in line and key in ("date", "panel") and ":" in line:
            settings_lines.append(line)
        elif "\t" in line and header is None:
            header = [HEADERS.get(" ".join(h.lower().split()), "") for h in line.split("\t")]
            problems += [f"The table needs a column '{c.title()}'" for c in TABLE_NEEDS if c not in header]
        elif "\t" in line:
            cells = [c.strip() for c in line.split("\t")]
            rows.append((n, {k: cells[i] if i < len(cells) else "" for i, k in enumerate(header) if k}))
        elif (row := _comma_row(line)) is not None:
            rows.append((n, row))
        else:
            problems.append(f"Line {n}: needs {ROW_HELP}")
    return settings_lines, [(n, {f: r.get(f, "") for f in ("name", "position", "email", "date", "start", "end")})
                            for n, r in rows], problems


def parse(text: str, now: datetime, max_candidates: int, default_minutes: int = 30) -> Parsed:
    """Every problem at once, so the list is fixed in one pass. ``now`` is aware, in your time zone.
    Rows come as 'Name, Position, Start[, End], Email' lines or a pasted table (tabs) with a header."""
    settings_lines, rows, problems = _lines(text)
    day, panel = None, []
    for line in settings_lines:
        key, _, rest = line.partition(":")
        if key.strip().lower() == "date":
            day = _day(rest, now.date())
            if day is None:
                problems.append(f"'{rest.strip()}' is not a date (use dd/mm/yyyy)")
            continue
        for email in (e.lower() for e in re.split(r"[,\s]+", rest) if e):
            if EMAIL.match(email):
                panel.append(email)
            else:
                problems.append(f"Panel: '{email}' is not an email")
    people, days = [], set()
    for n, row in rows:
        who = f"Line {n} ({row['name'] or 'no name'})"
        found = _check_row(who, row)
        row_day = _day(row["date"], now.date()) if row["date"] else day
        if row["date"] and row_day is None:
            found.append(f"{who}: date '{row['date']}' is not a date (use dd/mm/yyyy)")
        problems += found
        if found or row_day is None:
            continue
        days.add(row_day)
        start = datetime.combine(row_day, times.clock(row["start"]), now.tzinfo)
        end = (datetime.combine(row_day, times.clock(row["end"]), now.tzinfo) if row["end"]
               else start + timedelta(minutes=default_minutes))
        people.append(Candidate(row["name"], row["position"], start, end, row["email"].lower()))
    if day is None and not any(r["date"] for _, r in rows) and rows:
        problems.append("Add a line 'Date: dd/mm/yyyy', or a Date column, for the day of the interviews")
    if len(days) > 1:
        problems.append("One day per batch (one Teams link): found " + ", ".join(f"{d:%d/%m}" for d in sorted(days))
                        + ". Send one message per day.")
    if not rows and not problems:
        problems.append(f"Add one line per candidate: {ROW_HELP}")
    people.sort(key=lambda c: c.start)
    problems += _clashes(people, now, max_candidates)
    return Parsed(min(days) if days else day, tuple(panel), tuple(people), tuple(problems))


def _clashes(people: list[Candidate], now: datetime, max_candidates: int) -> list[str]:
    out = [f"{c.name}: ends {c.end:%H:%M}, not after the start {c.start:%H:%M}" for c in people if c.end <= c.start]
    out += [f"{c.name}: {c.start:%d/%m %H:%M} has already passed" for c in people if c.start <= now]
    out += [f"{a.name} ({a.start:%H:%M}–{a.end:%H:%M}) overlaps {b.name} ({b.start:%H:%M}–{b.end:%H:%M}): "
            "one link, so slots can't overlap" for a, b in zip(people, people[1:]) if a.end > b.start]
    seen: dict[str, str] = {}
    for c in people:
        if c.email in seen:
            out.append(f"{c.email} is on two lines ({seen[c.email]} and {c.name})")
        seen[c.email] = c.name
    if len(people) > max_candidates:
        out.append(f"{len(people)} candidates is over hr.max_interviews ({max_candidates})")
    return out


def busy_warnings(http: Http, secrets: Secrets, parsed: Parsed) -> list[str]:
    """Your own calendar during each slot: a warning, not a stop (you may be on the panel or not)."""
    first, last = parsed.candidates[0].start, parsed.candidates[-1].end
    try:
        busy = graph.busy(http, graph.access(http, secrets), first, last)
    except OutreachError as exc:
        return [f"Couldn't check your calendar: {exc}"]
    return [f"{c.name} {c.start:%H:%M}–{c.end:%H:%M}: you have something else then" for c in parsed.candidates
            if any(b0 < c.end and c.start < b1 for b0, b1 in busy)]


def plan(parsed: Parsed, warnings: list[str], now: float) -> dict[str, Any]:
    return {"created": now, "day": parsed.day.isoformat(), "panel": list(parsed.panel), "warnings": warnings,
            "candidates": [{"name": c.name, "position": c.position, "start": c.start.isoformat(),
                            "end": c.end.isoformat(), "email": c.email} for c in parsed.candidates]}


def _people(saved: dict[str, Any]) -> list[Candidate]:
    return [Candidate(c["name"], c["position"], datetime.fromisoformat(c["start"]), datetime.fromisoformat(c["end"]),
                      c["email"]) for c in saved["candidates"]]


def preview(saved: dict[str, Any], expires_min: int) -> str:
    people = _people(saved)
    day = date.fromisoformat(saved["day"])
    lines = [f"**Interviews, {day:%a %d %b}**: one Teams link, {people[0].start:%H:%M}–{people[-1].end:%H:%M} IST", ""]
    lines += [f"{n}. {c.start:%H:%M}–{c.end:%H:%M} {c.name}, {c.position}, {c.email}" for n, c in enumerate(people, 1)]
    lines += ["", "Panel: " + (", ".join(saved["panel"]) or "only you")]
    lines += [f"⚠️ {w}" for w in saved["warnings"]]
    return "\n".join([*lines, "", "Nothing is sent yet. /hr interview yes · /hr interview no",
                      f"(expires in {expires_min} min)"])


def _values(c: Candidate, settings: Settings, join: str) -> dict[str, str]:
    t = settings.interview
    return {"first": c.first, "name": c.name, "position": c.position, "day": f"{c.start:%a %d %b}",
            "start": f"{c.start:%H:%M}", "end": f"{c.end:%H:%M}", "length": str(c.minutes), "join": join,
            "sender": settings.sender_name or t.company, "company": t.company}


def send(http: Http, secrets: Secrets, saved: dict[str, Any], settings: Settings,
         log: Callable[[str, bool, str], None]) -> str:
    """The panel event first (it makes the link); then one invite per candidate. ``log(to, ok, note)``."""
    people, t = _people(saved), settings.interview
    token = graph.access(http, secrets)
    stamp = int(saved["created"])
    schedule = "<br>".join(f"{c.start:%H:%M}–{c.end:%H:%M} {c.name}, {c.position}" for c in people)
    shared = {"day": f"{people[0].start:%a %d %b}", "sender": settings.sender_name or t.company, "company": t.company,
              "positions": ", ".join(dict.fromkeys(c.position for c in people)), "schedule": schedule}
    _, join = graph.create_event(http, token, subject=fill(t.panel_subject, **shared),
                                 body_html=fill(t.panel_body, **shared), start=people[0].start, end=people[-1].end,
                                 attendees=[{"email": e} for e in saved["panel"]], teams=True,
                                 transaction_id=f"hr-interview-{stamp}-panel")
    if not join:
        raise OutreachError("Teams gave no link, so no candidate was invited. The panel event is on your "
                            "calendar; delete it and try again.")
    failed = []
    for n, c in enumerate(people, 1):
        v = _values(c, settings, join)
        try:
            graph.create_event(http, token, subject=fill(t.candidate_subject, **v),
                               body_html=fill(t.candidate_body, **v), start=c.start, end=c.end,
                               attendees=[{"email": c.email, "name": c.name}], teams=False,
                               transaction_id=f"hr-interview-{stamp}-{n}", location="Microsoft Teams Meeting")
            log(c.email, True, "")
        except OutreachError as exc:
            log(c.email, False, str(exc))
            failed.append(f"{c.name}: {exc}")
    head = f"Invited {len(people) - len(failed)} of {len(people)} candidates to their slot, all on one Teams link."
    return "\n".join([head, *failed, f"Panel: {', '.join(saved['panel']) or 'only you'} got the whole schedule."])

