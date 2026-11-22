"""``/slack`` and ``/meet`` in Telegram, and ``draft`` for Hermes' agent.

Fixed forms are read by the script (no model). Anything else is one model call
(``understand.read_request``) and always ends in a plan you approve. Only a command you type
(``/slack yes``, ``/meet yes``) sends a plan; ``draft`` can only save one.

Sent at once, without a plan: ``/slack send``, ``/slack schedule`` (your exact words), and
``/meet <time> <one person>`` when that exact time is free.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, time, timezone, UTC
from pathlib import Path

from orchestrator.brief.net import Http, HttpError
from orchestrator.brief.store import default_state_dir

from . import build, execute, times, understand
from .errors import OutreachError
from .people import Person, clean
from .plan import Kind, Line, Plan, picks, preview
from .session import Session

SLACK_HELP = """**/slack** — send Slack messages as you (sends go out under your name)
/slack send @priya @rahul: Please send the Q3 numbers by 5 — sends now, your exact words
/slack send group @priya @rahul: … — one group DM instead of one DM each
/slack schedule tomorrow 9am @priya: … — Slack delivers it at that time
/slack draft @priya @rahul @amit: ask each for their Q3 numbers by Friday — the model writes one
   professional message per person; you see them first
/slack tell Priya and Rahul the review moves to Friday — any sentence: the model reads it, you see drafts
/slack yes · /slack yes 1,3 · /slack edit 2 <new text> · /slack no · /slack show
Names: @handle, display name, first name or email. A name that fits two people stops; nothing goes to a guess.
Max outreach.daily_cap sends a day (default 50); every send is logged. /menu — all your commands"""

MEET_HELP = """**/meet** — book Outlook meetings (Teams link) and tell people on Slack
/meet 15:00 30m @priya: vendor contract — booked at once if you are free then
/meet 15:00-18:00 15m @a @b @c …: Q3 reviews — 1:1s back to back from 15:00, each 15 min + 5 min break
/meet tomorrow 3pm-6pm 15m gap 10m @a, @b: … — day, length and break are optional
/meet 15:00-17:00 — finds who asked you to meet (Slack DMs, Outlook mail, last 3 days)
/meet allhands 16:00 60m #home: Q3 review — one invite to everyone in #home + a post there
/meet set up 1:1s with Priya, Rahul and Amit from 3 to 6, 15 minutes each — any sentence (model reads it)
/meet yes · /meet yes 1-4 · /meet no · /meet show
Plans wait for your yes; one person at an exact free time is booked at once. /menu — all your commands"""

COLON = re.compile(r":(?!\d)")  # the colon before your text, not the one inside 15:00


def _split(arg: str) -> tuple[str, str]:
    m = COLON.search(arg)
    return (arg[: m.start()].strip(), arg[m.end():].strip()) if m else (arg.strip(), "")


def _names(words: str) -> list[str]:
    parts = words.split(",") if "," in words else words.split()
    words = (p.strip().strip(",.;:").strip() for p in parts)
    return [w for w in words if clean(w) and w.lower() != "and"]


def _fixed_names(rest: str) -> list[str] | None:
    """Names in a fixed /meet form: @handles, emails, or a comma-separated list. Anything else
    (\"with Priya about…\") is a sentence for the model."""
    if "," in rest:
        return _names(rest)
    words = rest.split()
    return _names(rest) if words and all("@" in w for w in words) else None


def _find(session: Session, words: list[str], *, at_once: bool = False) -> list[Person]:
    """``at_once``: the command sends without a preview, so only exact names count."""
    people, problems = session.directory.find_all(words, exact_only=at_once)
    if problems:
        raise OutreachError("Nothing sent. " + " ".join(problems))
    if not people:
        raise OutreachError("Name at least one person, e.g. @priya.")
    return people


def _save(session: Session, plan: Plan) -> str:
    if plan.lines:
        session.store.save(plan)
    return preview(plan, session.settings.preview_minutes)


# ------------------------------------------------------------------ time words at the front
class Head:
    """Leading time words of a fixed command, then the names."""

    def __init__(self, head: str, today: date) -> None:
        self.day: date | None = None
        self.start: time | None = None
        self.end: time | None = None
        self.length: int | None = None
        self.gap: int | None = None
        self.channel = ""
        words = head.split()
        i = 0
        while i < len(words):
            word = words[i]
            if word.lower() == "gap" and i + 1 < len(words) and (g := times.length(words[i + 1])):
                self.gap, i = g, i + 2
                continue
            if (w := times.window(word)) and self.start is None:
                self.start, self.end = w
            elif (c := times.clock(word)) and self.start is None:
                self.start = c
            elif (d := times.day(word, today)) and self.day is None:
                self.day = d
            elif (n := times.length(word)) and self.length is None:
                self.length = n
            elif word.startswith("#") and not self.channel:
                self.channel = word[1:]
            else:
                break
            i += 1
        self.rest = " ".join(words[i:])


# ------------------------------------------------------------------ /slack
def _send(session: Session, arg: str, scheduled: bool) -> str:
    head, text = _split(arg)
    if not text:
        raise OutreachError("Put your message after a colon: /slack send @priya: Hello")
    group = head.lower().startswith("group ")
    if group:
        head = head[6:]
    send_at = None
    if scheduled:
        h = Head(head, session.local_now.date())
        if h.start is None:
            raise OutreachError("Give a time: /slack schedule tomorrow 9am @priya: …")
        send_at = datetime.combine(h.day or session.local_now.date(), h.start, session.tz)
        head = h.rest
    people = _find(session, _names(head), at_once=True)
    plan = build.messages(session, people, {p.slack_id: text for p in people}, group=group, send_at=send_at)
    if not plan.lines:
        return "Nothing sent. " + " ".join(plan.notes)
    report = execute.run(session, plan, list(range(len(plan.lines))))
    return "\n".join([report, *(f"⚠️ {n}" for n in plan.notes)])


def _draft(session: Session, arg: str) -> str:
    head, text = _split(arg)
    if not text:
        raise OutreachError("Say what to tell them after a colon: /slack draft @priya @rahul: …")
    group = head.lower().startswith("group ")
    people = _find(session, _names(head[6:] if group else head))
    on_slack = [p for p in people if p.slack_id] or people
    if group:
        texts = understand.write_messages(session.http, session.gemini_key, on_slack[:1], text, session.settings)
        texts = {p.slack_id: texts[on_slack[0].slack_id] for p in on_slack}
    else:
        texts = understand.write_messages(session.http, session.gemini_key, on_slack, text, session.settings)
    return _save(session, build.messages(session, people, texts, group=group, title="Slack drafts"))


def _edit(session: Session, arg: str) -> str:
    plan = session.store.waiting("slack", session.now, session.settings.preview_minutes)
    number, _, text = arg.strip().partition(" ")
    if plan is None:
        return "No Slack drafts are waiting."
    if not number.isdigit() or not 1 <= int(number) <= len(plan.lines) or not text.strip():
        return "Usage: /slack edit 2 <new text>"
    old = plan.lines[int(number) - 1]
    who = old.label.split(":", 1)[0]
    actions = tuple(type(a)(**{**a.__dict__, "text": text.strip()}) for a in old.actions)
    lines = list(plan.lines)
    lines[int(number) - 1] = Line(f"{who}: {text.strip()}", actions)
    return _save(session, Plan(plan.kind, plan.title, tuple(lines), session.now, plan.notes))


# ------------------------------------------------------------------ /meet
def _meet_fixed(session: Session, h: Head, topic: str) -> str | None:
    """None when the words aren't a fixed /meet form (the model reads it instead)."""
    if h.start is None:
        return None
    s = session.settings
    window = build.Window(h.day or session.local_now.date(), h.start, h.end, h.gap or s.gap_minutes)
    if not h.rest:
        if h.end is None:
            return None
        return _save(session, build.detected(session, window, h.length))
    names = _fixed_names(h.rest)
    if names is None:
        return None
    people = _find(session, names, at_once=len(names) == 1 and h.end is None)
    minutes = h.length or s.default_length
    plan = build.one_on_ones(session, [(p, minutes) for p in people], window, {p.email: topic for p in people},
                             title=f"1:1s: {topic or build.DEFAULT_TOPIC}")
    exact = datetime.combine(window.day, h.start, session.tz)
    instant = (len(people) == 1 and h.end is None and len(plan.lines) == 1 and not plan.notes
               and plan.lines[0].actions[0].start == exact.astimezone(UTC).isoformat())
    if instant:
        return execute.run(session, plan, [0]) + "\n" + plan.lines[0].label
    if len(people) == 1 and h.end is None and plan.lines:
        plan = Plan(plan.kind, plan.title, plan.lines, plan.created,
                    (*plan.notes, f"You are busy at {times.show_time(exact)}; this is the next free time."))
    return _save(session, plan)


def _allhands(session: Session, arg: str) -> str | None:
    head, topic = _split(arg)
    h = Head(head, session.local_now.date())
    if h.start is None or not h.channel:
        return None
    plan = build.allhands(session, h.channel, h.day or session.local_now.date(), h.start,
                          h.length or session.settings.allhands_length, topic)
    return _save(session, plan)


def from_sentence(session: Session, text: str) -> str:
    """Any sentence → one model call → a saved plan and its preview. Never sends."""
    req = understand.read_request(session.http, session.gemini_key, text, session.settings, session.local_now)
    s = session.settings
    day = req.day or session.local_now.date()
    if req.kind == "messages":
        people = _find(session, list(req.people))
        said = {clean(to).lower(): body for to, body in req.messages}
        first = req.messages[0][1] if req.messages else ""
        texts = {}
        for word in req.people:
            person = session.directory.find(word).person
            body = first if req.group else said.get(clean(word).lower(), "")
            if person is None or not body:
                raise OutreachError(f"The model wrote nothing for {word}. Try /slack draft.")
            texts.setdefault(person.slack_id, body)
        send_at = req.send_at.replace(tzinfo=session.tz) if req.send_at else None
        return _save(session, build.messages(session, people, texts, group=req.group, send_at=send_at,
                                             title="Slack drafts"))
    if req.start is None:
        raise OutreachError("Say a start time, e.g. 'from 3 to 6' or 'at 4pm'.")
    if req.kind == "allhands":
        if not req.channel:
            raise OutreachError("Which channel? e.g. 'put it on #home'.")
        return _save(session, build.allhands(session, req.channel, day, req.start,
                                             req.length or s.allhands_length, req.topic))
    window = build.Window(day, req.start, req.end, req.gap or s.gap_minutes)
    if not req.people:
        return _save(session, build.detected(session, window, req.length or None))
    people = _find(session, list(req.people))
    minutes = req.length or s.default_length
    return _save(session, build.one_on_ones(session, [(p, minutes) for p in people], window,
                                            {p.email: req.topic for p in people},
                                            title=f"1:1s: {req.topic or build.DEFAULT_TOPIC}"))


# ------------------------------------------------------------------ yes / no / show
def _yes(session: Session, kind: Kind, arg: str) -> str:
    plan = session.store.waiting(kind, session.now, session.settings.preview_minutes)
    if plan is None:
        return f"Nothing is waiting (plans expire after {session.settings.preview_minutes} min)."
    chosen = picks(arg, len(plan.lines))
    if chosen is None:
        return f"Pick line numbers between 1 and {len(plan.lines)}, e.g. /{kind} yes 1,3"
    session.store.drop(kind)
    return execute.run(session, plan, chosen)


def _no(session: Session, kind: Kind, _arg: str) -> str:
    return "Cancelled. Nothing was sent." if session.store.drop(kind) else "Nothing was waiting."


def _show(session: Session, kind: Kind, _arg: str) -> str:
    plan = session.store.waiting(kind, session.now, session.settings.preview_minutes)
    return preview(plan, session.settings.preview_minutes) if plan else "Nothing is waiting."


Handler = Callable[[Session, str], str]
PLAN_WORDS: dict[str, Callable[[Session, Kind, str], str]] = {"yes": _yes, "no": _no, "cancel": _no, "show": _show}
SLACK: dict[str, Handler] = {
    "send": lambda s, a: _send(s, a, scheduled=False),
    "schedule": lambda s, a: _send(s, a, scheduled=True),
    "draft": _draft,
    "edit": _edit,
}


def _slack(session: Session, raw: str) -> str:
    word, _, arg = raw.strip().partition(" ")
    if word.lower() in PLAN_WORDS:
        return PLAN_WORDS[word.lower()](session, "slack", arg)
    if word.lower() in SLACK:
        return SLACK[word.lower()](session, arg)
    return from_sentence(session, raw)


def _meet(session: Session, raw: str) -> str:
    word, _, arg = raw.strip().partition(" ")
    if word.lower() in PLAN_WORDS:
        return PLAN_WORDS[word.lower()](session, "meet", arg)
    if word.lower() in ("allhands", "all-hands"):
        return _allhands(session, arg) or from_sentence(session, "all hands " + arg)
    head, topic = _split(raw)
    return _meet_fixed(session, Head(head, session.local_now.date()), topic) or from_sentence(session, raw)


def _guarded(run: Callable[[Session, str], str], raw: str, state_dir: Path | None, http: Http | None,
             now: float | None) -> str:
    try:
        return run(Session(state_dir or default_state_dir(), http, now), raw)
    except OutreachError as exc:
        return str(exc)
    except HttpError as exc:
        return f"Network problem, nothing more was sent: {exc}"


def handle_slack(raw: str, state_dir: Path | None = None, http: Http | None = None, now: float | None = None) -> str:
    return _guarded(_slack, raw, state_dir, http, now)


def handle_meet(raw: str, state_dir: Path | None = None, http: Http | None = None, now: float | None = None) -> str:
    return _guarded(_meet, raw, state_dir, http, now)


def draft(sentence: str, state_dir: Path | None = None, http: Http | None = None, now: float | None = None) -> str:
    """For Hermes' agent: saves a plan from a sentence. It cannot send; you approve in Telegram."""
    return _guarded(from_sentence, sentence, state_dir, http, now)
