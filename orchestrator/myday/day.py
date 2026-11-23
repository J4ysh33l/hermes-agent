"""Tasks for today: Microsoft To Do is the store, this module adds the top picks, points and
streak. No model: every form is read by script.

"Due now" means due today or overdue, in your tasks list and your Bills list. Tasks with no due
date are "later" (shown as a count; ``/day later`` lists them, ``/day pick`` brings one to today).
A task completed in the To Do app counts too: each scan compares what was open with what is open
now, and asks To Do about each one that vanished (done, or deleted).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from . import dates
from .errors import MyDayError
from .game import Event, Reply, level_for, progress_bar
from .session import Session
from .todo import Task, split_key


@dataclass(frozen=True)
class Board:
    due: list[Task]  # due today or overdue: these decide the streak
    later: list[Task]  # no due date (tasks list only)
    soon: list[Task]  # due in the next 7 days

    @property
    def keys(self) -> list[str]:
        return [t.key for t in self.due]


def list_ids(session: Session) -> tuple[str, str]:
    lists = session.settings.lists
    return session.todo.list_id(lists.tasks), session.todo.list_id(lists.bills)


def board(session: Session) -> Board:
    tasks_id, bills_id = list_ids(session)
    today = session.today
    open_tasks = session.todo.open_tasks(tasks_id) + session.todo.open_tasks(bills_id)
    due = [t for t in open_tasks if t.due and t.due <= today]
    later = [t for t in open_tasks if t.due is None and t.list_id == tasks_id]
    soon = [t for t in open_tasks if t.due and today < t.due <= today + timedelta(days=7)]
    top = session.state.top_for(today)
    due.sort(key=lambda t: (t.key not in top, t.list_id == bills_id, t.due, not t.important, t.title.lower()))
    soon.sort(key=lambda t: (t.due, t.title.lower()))
    return Board(due, later, soon)


def task_points(session: Session, task: Task) -> int:
    """Points for finishing ``task`` today (bills score on time or late, top picks score more)."""
    pts = session.settings.points
    if task.list_id == list_ids(session)[1]:
        return pts.bill_on_time if task.due is None or task.due >= session.today else pts.bill_late
    return pts.top if task.key in session.state.top_for(session.today) else pts.task


def credit(session: Session, task: Task) -> int:
    return session.state.award(f"task:{task.id}", task_points(session, task), session.today)


def scan(session: Session, *, close: bool = True) -> tuple[Board, list[Event]]:
    """Close past days (``close``), credit tasks finished in the To Do app, update the streak."""
    events: list[Event] = []
    state, today = session.state, session.today
    if close and (broken := state.close_days(today)):
        events.append(broken)
    now = board(session)
    open_keys = set(now.keys)
    done: list[str] = []
    for key in state.day(today)["pending"]:
        if key in open_keys:
            continue
        task = session.todo.get(*split_key(key))
        if task is None:  # deleted: forget it rather than count it
            state.day(today)["seen"] = [k for k in state.day(today)["seen"] if k != key]
            continue
        if task.done:
            credit(session, task)
            done.append(key)
    if clear := state.observe(today, now.keys, done, session.settings.points.all_clear):
        events.append(clear)
    return now, events


# ---- commands -----------------------------------------------------------------------------------


def numbers(words: list[str]) -> list[int]:
    try:
        found = [int(w) for w in " ".join(words).replace(",", " ").split()]
    except ValueError:
        raise MyDayError("Give the numbers from the list, e.g. /day done 1 3") from None
    if not found:
        raise MyDayError("Give the numbers from the list, e.g. /day done 1 3")
    return found


def _pick(session: Session, kind: str, words: list[str]) -> list[str]:
    try:
        return session.state.pick(kind, numbers(words))
    except ValueError as exc:
        raise MyDayError(str(exc)) from None


def _titles(session: Session, keys: list[str], shown: Board) -> dict[str, Task]:
    found = {t.key: t for t in shown.due + shown.later + shown.soon}
    missing = [k for k in keys if k not in found]
    for key in missing:
        task = session.todo.get(*split_key(key))
        if task:
            found[key] = task
    return found


def done(session: Session, words: list[str]) -> Reply:
    keys = _pick(session, "day", words)
    shown = board(session)
    tasks = _titles(session, keys, shown)
    lines, gained = [], 0
    for key in keys:
        task = tasks.get(key)
        if task is None or task.done:
            lines.append("· already done or deleted")
            continue
        session.todo.complete(task.list_id, task.id)
        got = credit(session, task)
        gained += got
        lines.append(f"✅ {task.title}  +{got}")
    _, events = scan(session)
    left = len(session.state.day(session.today)["pending"])
    tail = "All clear for today!" if not left else f"{left} left today."
    return Reply("\n".join(lines) + f"\n{tail} (+{gained} pts)", tuple(events))


def add(session: Session, text: str) -> Reply:
    important = "!" in text.split()
    words = " ".join(w for w in text.split() if w != "!")
    if not words:
        raise MyDayError("What is the task? e.g. /day add Call Apollo about the pilot by fri")
    title, due = dates.split_trailing(words, session.today, session.today)
    tasks_id, _ = list_ids(session)
    task = session.todo.add(tasks_id, title, due, important=important)
    if important and due == session.today:
        top = session.state.top_for(session.today)
        if len(top) < session.settings.top_count:
            session.state.set_top(session.today, [*top, task.key])
    scan(session)
    star = " ★ top" if task.key in session.state.top_for(session.today) else ""
    return Reply(f"➕ {title} — {dates.label(due, session.today)}{star}")


def top(session: Session, words: list[str]) -> Reply:
    keys = _pick(session, "day", words)
    limit = session.settings.top_count
    if len(keys) > limit:
        raise MyDayError(f"Pick at most {limit} (top_count in myday.yaml).")
    session.state.set_top(session.today, keys)
    tasks = _titles(session, keys, board(session))
    lines = [f"★ {tasks[k].title}" for k in keys if k in tasks]
    return Reply("Today's top:\n" + "\n".join(lines) + f"\nEach is worth {session.settings.points.top} pts.")


def _move(session: Session, keys: list[str], when: date | None, penalise: bool) -> list[str]:
    tasks = _titles(session, keys, board(session))
    moved = []
    for key in keys:
        task = tasks.get(key)
        if task is None:
            continue
        session.todo.set_due(task.list_id, task.id, when)
        if penalise:
            session.state.award(f"snooze:{task.id}:{session.today.isoformat()}", session.settings.points.snooze,
                                session.today)
        moved.append(task.title)
    session.state.set_top(session.today, [k for k in session.state.top_for(session.today) if k not in keys])
    return moved


def _when(words: list[str], session: Session, default: date | None) -> date | None:
    return dates.parse(" ".join(words), session.today) if words else default


def snooze(session: Session, words: list[str]) -> Reply:
    nums = [w for w in words if w.replace(",", "").isdigit()]
    rest = [w for w in words if not w.replace(",", "").isdigit()]
    when = _when(rest, session, session.today + timedelta(days=1))
    if when is not None and when <= session.today:
        raise MyDayError("Snooze moves a task to a later day, e.g. /day snooze 2 fri")
    moved = _move(session, _pick(session, "day", nums), when, penalise=True)
    scan(session)
    pts = session.settings.points.snooze
    return Reply("\n".join(f"⏭ {t} → {dates.label(when, session.today)}" for t in moved) + f"  ({pts} each)")


def move_all(session: Session, words: list[str]) -> Reply:
    when = _when(words, session, session.today + timedelta(days=1))
    tasks_id, _ = list_ids(session)
    keys = [t.key for t in board(session).due if t.list_id == tasks_id]
    if not keys:
        return Reply("Nothing to move: no open tasks due today.")
    moved = _move(session, keys, when, penalise=True)
    scan(session)
    return Reply(f"⏭ Moved {len(moved)} to {dates.label(when, session.today)} "
                 f"({session.settings.points.snooze} each). Bills stay where they are.")


def later(session: Session) -> Reply:
    tasks = board(session).later
    session.state.remember("later", [t.key for t in tasks])
    if not tasks:
        return Reply("Nothing in later (tasks with no due date).")
    lines = [f"{i}. {t.title}" for i, t in enumerate(tasks[:30], 1)]
    return Reply("**Later**\n" + "\n".join(lines) + "\n/day pick 2 [when] — bring one to today (or a date)")


def pick(session: Session, words: list[str]) -> Reply:
    nums = [w for w in words if w.replace(",", "").isdigit()]
    rest = [w for w in words if not w.replace(",", "").isdigit()]
    when = _when(rest, session, session.today)
    keys = _pick(session, "later", nums)
    moved = _move(session, keys, when, penalise=False)
    scan(session)
    return Reply("\n".join(f"📌 {t} — {dates.label(when, session.today)}" for t in moved))


def stats(session: Session) -> Reply:
    state, today = session.state, session.today
    level = level_for(state.points, session.settings.level_names)
    span = level.next_at - level.floor
    week = sum(state.points_on(today - timedelta(days=i)) for i in range(today.weekday() + 1))
    return Reply("\n".join([
        f"**Level {level.number} · {level.name}**",
        f"{progress_bar(state.points - level.floor, span)} {state.points}/{level.next_at} pts",
        f"🔥 Streak {state.streak} days · best {state.best}",
        f"Today +{state.points_on(today)} · this week +{week}",
    ]))
