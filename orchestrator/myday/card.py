"""The morning card (07:30), the evening wrap-up and the 15-minute tick. Each returns text for
Hermes to deliver (empty = nothing to send) plus streak events for the animations.

A part that fails (To Do, the calendar) is named on the card; the rest still arrives.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from orchestrator.brief.net import HttpError
from orchestrator.brief.sources import outlook

from . import billmail, bills, dates, goals
from .day import Board, scan
from .errors import MyDayError
from .game import Event, Reply, level_for, progress_bar
from .session import Session

GRAPH = "https://graph.microsoft.com/v1.0"
WINDOW = timedelta(minutes=45)  # a wrap-up missed by more than this (host was off) is skipped, not sent late


def meetings(session: Session) -> list[str]:
    day = session.today
    start = datetime.combine(day, time.min, tzinfo=session.tz)
    params = {"startDateTime": start.isoformat(), "endDateTime": (start + timedelta(days=1)).isoformat(),
              "$select": "subject,start,end,isCancelled,isAllDay", "$orderby": "start/dateTime", "$top": 30}
    headers = {"Authorization": f"Bearer {session.token(outlook.MEETING_SCOPES)}",
               "Prefer": f'outlook.timezone="{_windows_zone(session.settings.timezone)}"'}
    try:
        rows = session.http.request("GET", GRAPH + "/me/calendarView", params=params, headers=headers).json()
    except HttpError as exc:
        raise MyDayError(f"calendar: HTTP {exc.status}") from None
    lines = []
    for row in rows.get("value") or []:
        if row.get("isCancelled"):
            continue
        when = "all day" if row.get("isAllDay") else row["start"]["dateTime"][11:16]
        lines.append(f"🗓 {when} {row.get('subject') or '(no title)'}")
    return lines


def _windows_zone(iana: str) -> str:
    return {"Asia/Kolkata": "India Standard Time", "Asia/Calcutta": "India Standard Time"}.get(iana, "UTC")


def _header(session: Session) -> str:
    state = session.state
    level = level_for(state.points, session.settings.level_names)
    bar = progress_bar(state.points - level.floor, level.next_at - level.floor, 8)
    return (f"☀️ **{session.local_now:%A, %-d %b}**\n"
            f"🔥 {state.streak}-day streak (best {state.best}) · Lv {level.number} {level.name} {bar}")


def task_lines(session: Session, shown: Board) -> list[str]:
    today = session.today
    top = session.state.top_for(today)
    bills_list = session.todo.list_id(session.settings.lists.bills)
    session.state.remember("day", shown.keys)
    lines = []
    for n, task in enumerate(shown.due, 1):
        mark = "★" if task.key in top else ("💳" if task.list_id == bills_list else "▫️")
        late = f" ({dates.label(task.due, today)})" if task.due and task.due < today else ""
        lines.append(f"{n}. {mark} {task.title}{late}")
    return lines


def _section(title: str, build) -> list[str]:
    try:
        lines = build()
    except MyDayError as exc:
        return [f"⚠️ {title}: {exc}"]
    return lines


def board_text(session: Session, shown: Board) -> str:
    """The task part of the card, also what /day now shows."""
    lines = task_lines(session, shown)
    top_n = session.settings.top_count
    if not lines:
        body = ["Nothing due today. 🎈 Add one: /day add <task> [when]"]
    else:
        body = ["**Today**", *lines]
        if not session.state.top_for(session.today):
            body.append(f"Pick your top {top_n}: /day top 1 2 3 (+{session.settings.points.top} each)")
    if shown.later:
        body.append(f"🗂 {len(shown.later)} in later · /day later")
    if shown.soon:
        nxt = ", ".join(f"{t.title} ({dates.label(t.due, session.today)})" for t in shown.soon[:3])
        body.append(f"🔜 {nxt}")
    return "\n".join(body)


def morning(session: Session) -> Reply:
    shown, events = scan(session)
    parts = [_header(session)]
    if any(e.kind == "broken" for e in events):
        parts.append("🧊 Yesterday closed with tasks open: streak reset. Today is day 1.")
    parts.append(board_text(session, shown))
    extra: list[str] = []
    if session.settings.calendar:
        extra += _section("calendar", lambda: meetings(session))
    extra += _section("bills from Gmail", lambda: billmail.scan(session))
    extra += _section("bills", lambda: _bill_glance(session))
    if extra:
        parts.append("\n".join(extra))
    parts.append("/day now · /day done 2 · /day add … · /bills · /goals")
    return Reply("\n\n".join(parts), tuple(events))


def _bill_glance(session: Session) -> list[str]:
    rows, today = bills.load(session.state_dir), session.today
    due = [(st.name, st.amount, st.due) for st in bills.statements(session) if (st.due - today).days <= 7]
    if rows:
        bills.sync(session, rows)
        due += [(c.bill.name, c.bill.amount, c.due) for c in bills.open_cycles(session, rows)
                if c.generated <= today and (c.due - today).days <= 7]
    return [f"💳 {name}{bills.money(amount)} due {dates.label(when, today)}"
            for name, amount, when in sorted(due, key=lambda row: row[2])]


def wrap(session: Session, shown: Board) -> str:
    state, today = session.state, session.today
    left = [t.title for t in shown.due]
    gained = state.points_on(today)
    if not left:
        return f"🌙 Wrap-up: all clear today, +{gained} pts. 🔥 {state.streak}"
    names = "\n".join(f"· {t}" for t in left[:8])
    keep = f"keep your 🔥 {state.streak}" if state.streak else "start a streak"
    return (f"🌙 Wrap-up: +{gained} pts today. {len(left)} still open:\n{names}\n"
            f"Finish them before midnight to {keep}, or /day move all (to tomorrow, "
            f"{session.settings.points.snooze} each).")


def tick(session: Session) -> Reply:
    """Every 15 minutes: credit To Do completions, then bill reminders, the wrap-up
    and, on ``goals_review`` day, the weekly goals review.
    Days are closed only by the morning card or a command, so a broken streak is never announced
    at midnight."""
    now = session.local_now
    lines: list[str] = []
    events: list[Event] = []
    shown: Board | None = None
    try:
        shown, events = scan(session, close=False)
    except MyDayError as exc:
        if session.state.once(f"todo-error:{session.today.isoformat()}"):
            lines.append(f"⚠️ My day: {exc}")
    lines += _section("bills", lambda: bills.reminders(session))
    wrap_at = datetime.combine(now.date(), session.settings.wrap, tzinfo=session.tz)
    if wrap_at <= now < wrap_at + WINDOW:
        if shown is not None and session.state.once(f"wrap:{now.date().isoformat()}"):
            lines.append(wrap(session, shown))
        if now.strftime("%a").lower() == session.settings.goals_review and \
                session.state.once(f"goals-review:{now.date().isoformat()}"):
            lines += _section("goals", lambda: [goals.review(session)])
    return Reply("\n\n".join(lines), tuple(events))
