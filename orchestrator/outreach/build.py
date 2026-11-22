"""Requests → plans (numbered lines of actions). Nothing here sends anything.

- ``messages``: one DM per person (or one group DM), now or at a set time.
- ``one_on_ones``: your Outlook busy times, then ``slots.pack`` back to back from the window start;
  each line is an invite (Teams) plus a Slack note when the person has Slack.
- ``allhands``: one invite to everyone in a Slack channel, plus a post in that channel.
- ``detected``: meeting requests found in your Slack DMs/mentions and Outlook mail, ranked by the
  model, then packed like ``one_on_ones``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, UTC

from orchestrator.brief import filters
from orchestrator.brief import settings as brief_settings
from orchestrator.brief.sources import outlook, slack

from . import graph, slackapi, slots, understand
from .errors import OutreachError
from .people import Person
from .plan import Action, Line, Plan
from .session import Session
from .times import show_day, show_time

DEFAULT_TOPIC = "a quick catch-up"


def fill(template: str, **values: str) -> str:
    """str.format that leaves unknown placeholders empty instead of failing on your own drafts."""
    return template.format_map(defaultdict(str, values))


def _short(text: str, limit: int = 90) -> str:
    one = " ".join(text.split())
    return one if len(one) <= limit else one[: limit - 1] + "…"


# ------------------------------------------------------------------ Slack messages
def messages(session: Session, people: list[Person], texts: dict[str, str], *, group: bool = False,
             send_at: datetime | None = None, title: str = "", notes: list[str] | None = None) -> Plan:
    """``texts``: slack_id → text (in group mode the first person's text is used)."""
    notes = list(notes or [])
    on_slack = [p for p in people if p.slack_id]
    notes += [f"{p.name} has no Slack account; not messaged." for p in people if not p.slack_id]
    when = int(send_at.timestamp()) if send_at else 0
    kind = "scheduled" if send_at else "dm"
    later = f" (sends {show_day(send_at.date(), session.local_now.date())} {show_time(send_at)})" if send_at else ""
    if send_at and send_at.timestamp() <= session.now + 60:
        raise OutreachError("That send time has passed. Give a time at least a minute from now.")
    lines: list[Line] = []
    if group and len(on_slack) > 1:
        if len(on_slack) > 8:
            raise OutreachError("A Slack group DM takes at most 8 people. Drop 'group' to message each person.")
        text = texts[on_slack[0].slack_id]
        names = ", ".join(p.first for p in on_slack)
        lines.append(Line(f"Group DM with {names}{later}: {text}",
                          (Action(kind, text=text, user_ids=tuple(p.slack_id for p in on_slack), post_at=when),)))
    else:
        lines += [Line(f"{p.name}{later}: {texts[p.slack_id]}",
                       (Action(kind, text=texts[p.slack_id], user_ids=(p.slack_id,), post_at=when),))
                  for p in on_slack]
    return Plan("slack", title or "Slack messages", tuple(lines), session.now, tuple(notes))


# ------------------------------------------------------------------ meetings
@dataclass(frozen=True)
class Window:
    day: date
    start: time
    end: time | None
    gap: int


def _local(session: Session, day: date, at: time) -> datetime:
    return datetime.combine(day, at, session.tz)


def _bounds(session: Session, window: Window) -> tuple[datetime, datetime | None]:
    start = slots.first_start(_local(session, window.day, window.start), session.local_now)
    end = _local(session, window.day, window.end) if window.end else None
    if end is not None and start >= end:
        raise OutreachError("That window is already over. Give a later time.")
    return start, end


def _busy(session: Session, start: datetime, end: datetime | None) -> list[tuple[datetime, datetime]]:
    rows = graph.busy(session.http, session.graph_token(), start, end or start + timedelta(hours=14))
    return [(a.astimezone(session.tz), b.astimezone(session.tz)) for a, b in rows]  # slots show local time


def _meeting_line(session: Session, slot: slots.Slot[Person], topic: str, minutes: int) -> Line:
    t = session.settings.templates
    p = slot.who
    today = session.local_now.date()
    values = {"first": p.first, "name": p.name, "topic": topic or DEFAULT_TOPIC, "length": str(minutes),
              "day": show_day(slot.start.date(), today), "start": show_time(slot.start), "end": show_time(slot.end)}
    event = Action("event", subject=fill(t.meeting_subject, **values), text=fill(t.meeting_body, **values),
                   start=slot.start.astimezone(UTC).isoformat(), end=slot.end.astimezone(UTC).isoformat(),
                   attendees=((p.name, p.email),), teams=session.settings.teams)
    actions = [event]
    note = ""
    if p.slack_id:
        note = fill(t.meeting_note, **values)
        actions.append(Action("dm", text=note, user_ids=(p.slack_id,)))
    where = "" if p.slack_id else " (no Slack: invite email only)"
    label = f"{p.name} — {values['start']}–{values['end']}{where}" + (f"\n   “{_short(note)}”" if note else "")
    return Line(label, tuple(actions))


def one_on_ones(session: Session, wanted: list[tuple[Person, int]], window: Window, topics: dict[str, str],
                *, title: str, notes: list[str] | None = None) -> Plan:
    """``wanted``: (person, minutes) in the order to place them; ``topics``: email → topic."""
    notes = list(notes or [])
    notes += [f"{p.name}: no email found, so no invite." for p, _ in wanted if not p.email]
    wanted = [(p, m) for p, m in wanted if p.email]
    start, end = _bounds(session, window)
    placed, left = slots.pack(wanted, start, end, _busy(session, start, end), window.gap)
    lengths = {p.email: m for p, m in wanted}
    lines = tuple(_meeting_line(session, s, topics.get(s.who.email, ""), lengths[s.who.email]) for s in placed)
    if left:
        notes.append("Doesn't fit in the window: " + ", ".join(p.name for p in left))
    return Plan("meet", title, lines, session.now, tuple(notes))


def allhands(session: Session, channel: str, day: date, start: time, minutes: int, topic: str) -> Plan:
    token = session.slack_token
    conv = slackapi.channel(session.http, token, channel)
    me = slackapi.me(session.http, token)
    people = [p for uid in slackapi.channel_members(session.http, token, conv["id"]) if uid != me
              and (p := session.directory.by_id(uid)) is not None]
    invited = [p for p in people if p.email]
    if not invited:
        raise OutreachError(f"No one in #{conv['name']} has an email I can invite.")
    begin = _local(session, day, start)
    finish = begin + timedelta(minutes=minutes)
    if begin <= session.local_now:
        raise OutreachError("That time has passed. Give a later start.")
    t = session.settings.templates
    values = {"topic": topic or "team update", "length": str(minutes), "start": show_time(begin),
              "end": show_time(finish), "day": show_day(day, session.local_now.date()), "first": "", "name": ""}
    event = Action("event", subject=fill(t.allhands_subject, **values), text=fill(t.allhands_body, **values),
                   start=begin.astimezone(UTC).isoformat(), end=finish.astimezone(UTC).isoformat(),
                   attendees=tuple((p.name, p.email) for p in invited), teams=session.settings.teams)
    post = fill(t.allhands_post, **{**values, "join": "{join}"})
    post_action = Action("channel_post", text=post, channel_id=conv["id"])
    notes = [f"{len(people) - len(invited)} member(s) have no email in Slack and get no invite."] \
        if len(invited) < len(people) else []
    busy = _busy(session, begin, finish)
    if busy:
        notes.append("You already have something in your calendar at that time.")
    label = (f"All hands — #{conv['name']} — {values['day']} {values['start']}–{values['end']} — "
             f"{len(invited)} invited\n   Post: “{_short(post.replace('{join}', ''), 160)}”")
    return Plan("meet", f"All hands: {topic or 'team update'}", (Line(label, (event, post_action)),),
                session.now, tuple(notes))


# ------------------------------------------------------------------ meeting requests found for you
def _rows(session: Session) -> list[tuple[str, str, str, str]]:
    """(row id, sender name or email, text, kind) from the last few days of Slack and Outlook."""
    since = session.now - session.settings.detect_days * 86400
    bs = brief_settings.load(session.state_dir)
    words = session.settings.detect_words
    items = slack.fetch(session.http, "", session.slack_token, bs, since)
    items = [i for i in items if i.topic == bs.slack_dm_group]
    if session.secrets.token("microsoft"):
        items += outlook.fetch(session.http, session.graph_token(), bs, since)
    kept, _private, _ = filters.keep(items, bs, lambda _uid: False)
    rows = []
    for n, item in enumerate(kept, start=1):
        text = f"{item.title} {item.snippet}"
        if any(w in text.lower() for w in words):
            sender = item.sender.split("<")[-1].rstrip(">") if item.source == "outlook" else item.sender.split(",")[0]
            rows.append((f"r{n}", sender.strip(), text, item.source))
    return rows


def detected(session: Session, window: Window, default_minutes: int | None) -> Plan:
    rows = _rows(session)
    if not rows:
        return Plan("meet", "No meeting requests found", (), session.now,
                    (f"Nothing in the last {session.settings.detect_days} days of Slack DMs or Outlook asks to meet.",))
    picked = understand.pick_requests(session.http, session.gemini_key, [r[:3] for r in rows], session.settings)
    senders = {r[0]: r[1] for r in rows}
    me = slackapi.me(session.http, session.slack_token)
    wanted: list[tuple[Person, int]] = []
    topics: dict[str, str] = {}
    notes: list[str] = []
    for w in picked:
        hit = session.directory.find(senders[w.row])
        if hit.person is None:
            notes.append(hit.problem)
        elif hit.person.slack_id != me and hit.person.email and hit.person.email not in topics:
            wanted.append((hit.person, default_minutes or w.length))
            topics[hit.person.email] = w.reason
    if not wanted:
        return Plan("meet", "No meeting requests found", (), session.now, tuple(notes) or ("No one asked to meet.",))
    return one_on_ones(session, wanted, window, topics, title="Meetings people asked you for", notes=notes)
