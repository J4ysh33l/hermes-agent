"""Goals, work and personal, as Microsoft To Do tasks in two lists ("Goals · Work",
"Goals · Personal"). A goal's target date is its due date; its milestones are the task's steps,
so progress is steps ticked / steps. Edit them in the To Do app or here; both count.
"""

from __future__ import annotations

from .dates import label, split_trailing
from .errors import MyDayError
from .game import Reply, progress_bar
from .session import Session
from .todo import Task, split_key

KINDS = ("work", "personal")


def _list(session: Session, kind: str) -> str:
    names = session.settings.lists
    return session.todo.list_id(names.work_goals if kind == "work" else names.personal_goals)


def _goals(session: Session) -> list[tuple[str, Task]]:
    found = []
    for kind in KINDS:
        tasks = session.todo.open_tasks(_list(session, kind))
        found += [(kind, t) for t in sorted(tasks, key=lambda t: (t.due is None, t.due, t.title.lower()))]
    return found


def show(session: Session) -> Reply:
    goals = _goals(session)
    session.state.remember("goals", [t.key for _, t in goals])
    if not goals:
        return Reply("No goals yet.\n/goals add work Sign 3 hospitals by 31 dec\n/goals add personal Run 10k by 15 jan")
    lines, current = [], ""
    for n, (kind, task) in enumerate(goals, 1):
        if kind != current:
            lines.append("**💼 Work**" if kind == "work" else "**🌱 Personal**")
            current = kind
        steps = session.todo.steps(task.list_id, task.id)
        done = sum(s.done for s in steps)
        bar = f" {progress_bar(done, len(steps), 8)} {done}/{len(steps)}" if steps else " (no steps yet)"
        lines.append(f"{n}. {task.title} — {label(task.due, session.today)}{bar}")
    lines.append("/goals show 1 · /goals step 1 <milestone> · /goals tick 1.2 · /goals done 1")
    return Reply("\n".join(lines))


def add(session: Session, words: list[str]) -> Reply:
    if not words or words[0].lower() not in KINDS or len(words) < 2:
        raise MyDayError("Use: /goals add work|personal <goal> [by <date>], e.g. /goals add work Sign 3 hospitals by 31 dec")
    kind = words[0].lower()
    title, due = split_trailing(" ".join(words[1:]), session.today, None)
    session.todo.add(_list(session, kind), title, due)
    return Reply(f"🎯 {kind.title()} goal: {title} — {label(due, session.today)}\nAdd milestones: /goals step <n> …\n"
                 + show(session).text)


def _goal(session: Session, number: str) -> Task:
    try:
        key = session.state.pick("goals", [int(number)])[0]
    except ValueError as exc:
        raise MyDayError(str(exc) if "No item" in str(exc) else "Give the goal's number from /goals.") from None
    task = session.todo.get(*split_key(key))
    if task is None:
        raise MyDayError("That goal was deleted. Show /goals again.")
    return task


def detail(session: Session, words: list[str]) -> Reply:
    if not words:
        raise MyDayError("Use: /goals show 1")
    task = _goal(session, words[0])
    steps = session.todo.steps(task.list_id, task.id)
    lines = [f"**{task.title}** — {label(task.due, session.today)}"]
    lines += [f"{words[0]}.{i} {'✅' if s.done else '▫️'} {s.title}" for i, s in enumerate(steps, 1)]
    return Reply("\n".join(lines) if steps else lines[0] + f"\nNo steps yet: /goals step {words[0]} <milestone>")


def step(session: Session, words: list[str]) -> Reply:
    if len(words) < 2:
        raise MyDayError("Use: /goals step 1 Call Apollo's procurement head")
    task = _goal(session, words[0])
    session.todo.add_step(task.list_id, task.id, " ".join(words[1:]))
    return detail(session, words[:1])


def tick(session: Session, words: list[str]) -> Reply:
    goal_no, _, step_no = (words[0] if words else "").partition(".")
    if not step_no.isdigit():
        raise MyDayError("Use: /goals tick 1.2 (goal 1, step 2; see /goals show 1)")
    task = _goal(session, goal_no)
    steps = session.todo.steps(task.list_id, task.id)
    if not 1 <= int(step_no) <= len(steps):
        raise MyDayError(f"Goal {goal_no} has {len(steps)} steps.")
    chosen = steps[int(step_no) - 1]
    session.todo.check_step(task.list_id, task.id, chosen.id)
    got = session.state.award(f"step:{chosen.id}", session.settings.points.goal_step, session.today)
    done = sum(s.done for s in steps) + (0 if chosen.done else 1)
    return Reply(f"✅ {chosen.title} +{got}\n{task.title}: {progress_bar(done, len(steps), 8)} {done}/{len(steps)}")


def complete(session: Session, words: list[str]) -> Reply:
    if not words:
        raise MyDayError("Use: /goals done 1")
    task = _goal(session, words[0])
    session.todo.complete(task.list_id, task.id)
    got = session.state.award(f"goal:{task.id}", session.settings.points.goal_done, session.today)
    return Reply(f"🏆 Goal reached: {task.title} +{got}")


def review(session: Session) -> str:
    """The weekly review (with the wrap-up on ``goals_review`` day): every goal with its progress."""
    listing = show(session).text
    if not _goals(session):
        return "🎯 Weekly goals review: no goals yet.\n" + listing
    return (f"🎯 **Weekly goals review**\n{listing}\n"
            "Plan a step for next week: /goals step 1 … · done one? /goals tick 1.1")
