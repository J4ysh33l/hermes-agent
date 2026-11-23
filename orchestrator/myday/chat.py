"""``/day``, ``/bills``, ``/goals`` and ``/health`` in Telegram. Every form is read by script: no
model call. Numbers refer to the last list shown (``/day now``, ``/bills``, ``/goals``)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import bills, card, celebrate, day, goals, health
from .errors import MyDayError
from .game import Reply
from .session import Session

DAY_HELP = """**/day** — today's tasks (Microsoft To Do), points and your streak
/day now — today's card: due and overdue tasks, numbered
/day done 2 · /day done 1 3 4 — tick off (+10, top picks +20, all clear +50 🔥)
/day add Call Apollo about the pilot by fri — due today if no date; add ! to make it a top pick
/day top 1 3 5 — today's top 3
/day snooze 2 [tomorrow|fri|25 nov] — move one later (−5)
/day move all [when] — every open task to tomorrow (−5 each; bills stay)
/day later — tasks with no date · /day pick 2 [when] — bring one to today
/day stats — level, points, streak
Dates: today, tomorrow, mon…sun, 25 nov, 25/11, +3, someday. The streak grows when everything due
today is done and resets when a day closes with tasks open. /menu — all your commands"""

BILLS_HELP = """**/bills** — monthly bills: generated date → due date, reminders, paid or not
/bills show — the timeline, numbered
/bills add HDFC card 5 25 4500 — name, generated day, due day, amount (optional)
/bills paid 2 — mark this cycle paid (+15 on time, +5 late); ticking it in To Do counts too
/bills amount 2 5200 · /bills remove 2
Each generated bill becomes a To Do task in your Bills list with a phone reminder; Telegram
reminds you 3 days before and on the day (bill_remind_days in myday.yaml). /menu — all your commands"""

GOALS_HELP = """**/goals** — work and personal goals (To Do lists "Goals · Work" and "Goals · Personal")
/goals show — every goal with its progress, numbered · /goals show 2 — its steps
/goals add work Sign 3 hospitals by 31 dec · /goals add personal Run 10k by 15 jan
/goals step 2 Call Apollo's procurement head — add a milestone
/goals tick 2.1 — milestone done (+25) · /goals done 2 — goal reached (+100)
/menu — all your commands"""

HEALTH_HELP = """**/health** — your health log (kept on the host only, never sent to a model)
/health show — today and the last 7 days
/health weight 82.4 · /health food dal, rice, salad · /health water 2
/health workout 30m walk · /health sleep 7.5 — each +5 (food: first 3 a day)
Nudges (times in myday.yaml): Monday 09:00 weigh-in; food 14:00, 18:00, 22:00. /menu — all your commands"""

Handler = Callable[[Session, list[str]], Reply]

DAY: dict[str, Handler] = {
    "now": lambda s, w: Reply(card.board_text(s, day.scan(s)[0])),
    "card": lambda s, w: card.morning(s),
    "done": day.done,
    "add": lambda s, w: day.add(s, " ".join(w)),
    "top": day.top,
    "snooze": day.snooze,
    "move": lambda s, w: day.move_all(s, w[1:] if w[:1] == ["all"] else w),
    "later": lambda s, w: day.later(s),
    "pick": day.pick,
    "stats": lambda s, w: day.stats(s),
}

BILLS: dict[str, Handler] = {
    "show": lambda s, w: bills.timeline(s),
    "add": bills.add,
    "paid": bills.paid,
    "amount": bills.amount,
    "remove": bills.remove,
}

GOALS: dict[str, Handler] = {
    "show": lambda s, w: goals.detail(s, w) if w else goals.show(s),
    "add": goals.add,
    "step": goals.step,
    "tick": goals.tick,
    "done": goals.complete,
}

def _health_log(kind: str) -> Handler:
    return lambda s, w: health.log(s, kind, w)


HEALTH: dict[str, Handler] = {"show": lambda s, w: health.summary(s)} | {kind: _health_log(kind) for kind in health.KINDS}


def run(table: dict[str, Handler], help_text: str, raw_args: str, state_dir: Path | None = None,
        session: Session | None = None) -> str:
    words = (raw_args or "").split()
    handler = table.get(words[0].lower()) if words else None
    if handler is None:
        return help_text
    session = session or Session(state_dir)
    try:
        reply = handler(session, words[1:])
    except (MyDayError, ValueError) as exc:  # ValueError: a date or number the script could not read
        return f"⚠️ {exc}"
    session.save()
    notes = celebrate.send(session, reply.events)
    return "\n".join([reply.text, *notes])


def handle_day(raw_args: str, state_dir: Path | None = None) -> str:
    return run(DAY, DAY_HELP, raw_args, state_dir)


def handle_bills(raw_args: str, state_dir: Path | None = None) -> str:
    return run(BILLS, BILLS_HELP, raw_args, state_dir)


def handle_goals(raw_args: str, state_dir: Path | None = None) -> str:
    return run(GOALS, GOALS_HELP, raw_args, state_dir)


def handle_health(raw_args: str, state_dir: Path | None = None) -> str:
    return run(HEALTH, HEALTH_HELP, raw_args, state_dir)
