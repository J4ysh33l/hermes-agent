"""Monthly bills: when each is generated and when it is due, as a timeline, with reminders.

Your bills live in ``$HERMES_HOME/myday/bills.json`` (edited by ``/bills add|amount|remove``).
Each has a generation day and a due day of the month; a due day before the generation day means
the next month (a card generated on the 5th, due on the 25th, or generated on the 20th, due on
the 10th of the next month). Days past a month's end mean its last day.

On the generation day each cycle gets a To Do task in your Bills list ("💳 Pay …"), due on the due
date with a phone reminder ``bill_remind_days[0]`` days before. Ticking it off — in To Do or with
``/bills paid`` — marks it paid and scores (on time or late). Telegram reminds you on each of
``bill_remind_days`` before the due date until it is paid. No bank access, no model.

Bills found in Gmail (``billmail``) are one-off "statements" with an exact amount and due date,
kept in state.json; they get the same To Do task, reminders and points.
"""

from __future__ import annotations

import calendar
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import MyDayError
from .game import Reply
from .session import Session
from .todo import reminder_at, split_key

if TYPE_CHECKING:
    from .billmail import Found

STATEMENT = "mail:"  # listing prefix for a bill found in Gmail


@dataclass(frozen=True)
class Bill:
    id: str
    name: str
    generated: int  # day of month
    due: int  # day of month
    amount: float = 0  # 0 = varies / not set
    since: str = ""  # ISO date it was added: cycles due before it are not yours to pay here


@dataclass(frozen=True)
class Cycle:
    bill: Bill
    generated: date
    due: date

    @property
    def key(self) -> str:
        return f"{self.bill.id}:{self.due.isoformat()}"


def _clamp(year: int, month: int, day: int) -> date:
    while month > 12:
        year, month = year + 1, month - 12
    while month < 1:
        year, month = year - 1, month + 12
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def cycle(bill: Bill, year: int, month: int) -> Cycle:
    """The cycle generated in ``year``-``month``."""
    gen = _clamp(year, month, bill.generated)
    due = _clamp(year, month + (1 if bill.due < bill.generated else 0), bill.due)
    return Cycle(bill, gen, due)


def cycles_around(bill: Bill, today: date) -> list[Cycle]:
    return [cycle(bill, today.year, today.month + delta) for delta in (-2, -1, 0, 1)]


def money(amount: float) -> str:
    if not amount:
        return ""
    whole = f"{amount:,.0f}" if amount == int(amount) else f"{amount:,.2f}"
    return f" ₹{whole}"


# ---- the bills file -------------------------------------------------------------------------------


def path(state_dir: Path) -> Path:
    return state_dir / "bills.json"


def load(state_dir: Path) -> list[Bill]:
    file = path(state_dir)
    rows = json.loads(file.read_text(encoding="utf-8")) if file.is_file() else []
    return [Bill(**r) for r in rows]


def save(state_dir: Path, bills: list[Bill]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    tmp = path(state_dir).with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(b) for b in bills], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path(state_dir))


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "bill"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


# ---- status ---------------------------------------------------------------------------------------


def _tasks(session: Session) -> dict[str, str]:
    return session.state.data.setdefault("bill_tasks", {})


def is_paid(session: Session, cyc: Cycle) -> bool:
    paid = session.state.data.setdefault("bills_paid", {})
    if cyc.key in paid:
        return True
    key = _tasks(session).get(cyc.key)
    if not key:
        return False
    task = session.todo.get(*split_key(key))
    if task is None or task.done:
        paid[cyc.key] = session.today.isoformat()
        return True
    return False


def open_cycles(session: Session, bills: list[Bill]) -> list[Cycle]:
    """Generated and unpaid (overdue first), then the next cycle of each bill not yet generated."""
    today, found = session.today, []
    for bill in bills:
        cycles = cycles_around(bill, today)
        oldest = max(bill.since, (today - timedelta(days=60)).isoformat())
        unpaid = [c for c in cycles if c.generated <= today and c.due.isoformat() >= oldest
                  and not is_paid(session, c)]
        upcoming = next(c for c in cycles if c.generated > today)
        found += unpaid or [upcoming]
    return sorted(found, key=lambda c: (c.due, c.bill.name.lower()))


def sync(session: Session, bills: list[Bill]) -> int:
    """Create the To Do task for every generated, unpaid cycle that has none. Returns how many."""
    created = 0
    bills_list = session.todo.list_id(session.settings.lists.bills)
    hour, first = session.settings.bill_reminder_hour, max(session.settings.bill_remind_days, default=0)
    for cyc in open_cycles(session, bills):
        if cyc.generated > session.today or cyc.key in _tasks(session):
            continue
        remind = reminder_at(max(session.today, cyc.due - timedelta(days=first)), hour, session.tz)
        task = session.todo.add(bills_list, f"💳 Pay {cyc.bill.name}{money(cyc.bill.amount)}", cyc.due, remind=remind,
                                note=f"Generated {cyc.generated:%-d %b}, due {cyc.due:%-d %b}. Tick when paid.")
        _tasks(session)[cyc.key] = task.key
        created += 1
    return created


def _status(session: Session, cyc: Cycle) -> str:
    today = session.today
    if cyc.generated > today:
        return f"📄 generates {cyc.generated:%-d %b}"
    days = (cyc.due - today).days
    if days < 0:
        return f"⚠️ {-days}d overdue"
    return "⏰ due today" if days == 0 else f"⏳ due in {days}d"


def timeline(session: Session) -> Reply:
    bills, mailed = load(session.state_dir), statements(session)
    if not bills and not mailed:
        return Reply("No bills yet. Add one: /bills add HDFC card 5 25 4500\n"
                     "(name, generated day, due day, amount optional). Bills mailed to your Gmail are added "
                     "on their own.")
    sync(session, bills)
    rows = open_cycles(session, bills)
    session.state.remember("bills", [c.bill.id for c in rows] + [STATEMENT + st.key for st in mailed])
    lines = ["**Bills**"]
    for n, cyc in enumerate(rows, 1):
        lines.append(f"{n}. {cyc.bill.name}{money(cyc.bill.amount)} — gen {cyc.generated:%-d %b} → due "
                     f"{cyc.due:%-d %b} · {_status(session, cyc)}")
    for n, st in enumerate(mailed, len(rows) + 1):
        lines.append(f"{n}. 📬 {st.name}{money(st.amount)} — due {st.due:%-d %b} · "
                     f"{_statement_status(session.today, st)}")
    lines.append("/bills paid 1 · /bills amount 1 4500 · /bills add … · /bills remove 1")
    return Reply("\n".join(lines))


# ---- statements: bills found in Gmail -------------------------------------------------------------


@dataclass(frozen=True)
class Statement:
    key: str  # "<due date>:<amount>": the bank's mail and CRED's about one bill share it
    name: str
    amount: float
    due: date
    task: str  # To Do task key


def _statements(session: Session) -> dict[str, dict]:
    return session.state.data.setdefault("statements", {})


def add_statement(session: Session, found: Found, subject: str) -> str:
    """Add a bill found in Gmail unless already known; the Telegram line, or ""."""
    key = f"{found.due.isoformat()}:{found.amount:.2f}"
    rows = _statements(session)
    if key in rows:
        return ""
    first = max(session.settings.bill_remind_days, default=0)
    remind = reminder_at(max(session.today, found.due - timedelta(days=first)), session.settings.bill_reminder_hour,
                         session.tz)
    task = session.todo.add(session.todo.list_id(session.settings.lists.bills),
                            f"💳 Pay {found.name}{money(found.amount)}", found.due, remind=remind,
                            note=f"Found in Gmail: {subject[:150]}. Tick when paid.")
    rows[key] = {"name": found.name, "amount": found.amount, "due": found.due.isoformat(), "task": task.key}
    return f"📬 New bill in Gmail: {found.name}{money(found.amount)} due {found.due:%-d %b} · added to To Do"


def statements(session: Session) -> list[Statement]:
    """Unpaid bills found in Gmail, soonest first. One ticked in To Do (or deleted) is paid; paid
    ones are forgotten 60 days after their due date."""
    rows, today, found = _statements(session), session.today, []
    for key, row in list(rows.items()):
        due = date.fromisoformat(row["due"])
        if row.get("paid"):
            if due < today - timedelta(days=60):
                del rows[key]
            continue
        task = session.todo.get(*split_key(row["task"]))
        if task is None or task.done:
            row["paid"] = today.isoformat()
            continue
        found.append(Statement(key, row["name"], row["amount"], due, row["task"]))
    return sorted(found, key=lambda st: (st.due, st.name.lower()))


def _statement_status(today: date, st: Statement) -> str:
    days = (st.due - today).days
    if days < 0:
        return f"⚠️ {-days}d overdue"
    return "⏰ due today" if days == 0 else f"⏳ due in {days}d"


def _pay_statement(session: Session, key: str) -> Reply:
    row = _statements(session).get(key)
    if row is None or row.get("paid"):
        return Reply("That bill is already paid. Show /bills again.")
    on_time = date.fromisoformat(row["due"]) >= session.today
    session.todo.complete(*split_key(row["task"]))
    row["paid"] = session.today.isoformat()
    pts = session.settings.points
    got = session.state.award(f"task:{split_key(row['task'])[1]}", pts.bill_on_time if on_time else pts.bill_late,
                              session.today)
    return Reply(f"✅ {row['name']} paid ({'on time' if on_time else 'late'}) +{got}")


# ---- commands -------------------------------------------------------------------------------------


def add(session: Session, words: list[str]) -> Reply:
    """``<name…> <generated day> <due day> [amount]``"""
    nums = []
    while words and re.fullmatch(r"[\d,.]+", words[-1]) and len(nums) < 3:
        nums.insert(0, words.pop())
    if len(nums) == 2:
        nums.append("0")
    if len(nums) != 3 or not words:
        raise MyDayError("Use: /bills add <name> <generated day> <due day> [amount], e.g. /bills add HDFC card 5 25 4500")
    gen, due, amount = int(nums[0]), int(nums[1]), float(nums[2].replace(",", ""))
    if not (1 <= gen <= 31 and 1 <= due <= 31):
        raise MyDayError("Days are days of the month, 1 to 31.")
    bills = load(session.state_dir)
    bill = Bill(_slug(" ".join(words), {b.id for b in bills}), " ".join(words), gen, due, amount,
                session.today.isoformat())
    save(session.state_dir, [*bills, bill])
    cyc = next(c for c in cycles_around(bill, session.today) if c.due >= session.today)
    return Reply(f"➕ {bill.name}{money(amount)}: generated on the {gen}, due on the {due}. "
                 f"Next due {cyc.due:%-d %b}.\n" + timeline(session).text)


def _picked(session: Session, words: list[str]) -> str:
    if not words or not words[0].isdigit():
        raise MyDayError("Give the bill's number from /bills, e.g. /bills paid 2")
    try:
        return session.state.pick("bills", [int(words[0])])[0]
    except ValueError as exc:
        raise MyDayError(str(exc)) from None


def _chosen(session: Session, words: list[str]) -> tuple[Bill, list[Bill]]:
    bill_id = _picked(session, words)
    if bill_id.startswith(STATEMENT):
        raise MyDayError("That bill came from Gmail: change or delete its task in To Do instead.")
    bills = load(session.state_dir)
    bill = next((b for b in bills if b.id == bill_id), None)
    if bill is None:
        raise MyDayError("That bill was removed. Show /bills again.")
    return bill, bills


def paid(session: Session, words: list[str]) -> Reply:
    if (picked := _picked(session, words)).startswith(STATEMENT):
        return _pay_statement(session, picked.removeprefix(STATEMENT))
    bill, bills = _chosen(session, words)
    cyc = next((c for c in open_cycles(session, bills) if c.bill.id == bill.id), None)
    if cyc is None or cyc.generated > session.today:
        return Reply(f"{bill.name}: nothing generated to pay yet.")
    pts = session.settings.points
    on_time = cyc.due >= session.today
    key = _tasks(session).get(cyc.key)
    if key:
        session.todo.complete(*split_key(key))
    session.state.data.setdefault("bills_paid", {})[cyc.key] = session.today.isoformat()
    got = session.state.award(f"task:{split_key(key)[1]}" if key else f"bill:{cyc.key}",
                              pts.bill_on_time if on_time else pts.bill_late, session.today)
    return Reply(f"✅ {bill.name} paid ({'on time' if on_time else 'late'}) +{got}")


def amount(session: Session, words: list[str]) -> Reply:
    bill, bills = _chosen(session, words)
    if len(words) < 2:
        raise MyDayError("Use: /bills amount 2 4500")
    value = float(words[1].replace(",", "").lstrip("₹"))
    save(session.state_dir, [replace(b, amount=value) if b.id == bill.id else b for b in bills])
    return Reply(f"{bill.name}: amount set to{money(value)} (new reminders show it).")


def remove(session: Session, words: list[str]) -> Reply:
    bill, bills = _chosen(session, words)
    save(session.state_dir, [b for b in bills if b.id != bill.id])
    return Reply(f"🗑 {bill.name} removed (tasks already in To Do stay there).")


# ---- reminders (tick) -----------------------------------------------------------------------------


def reminders(session: Session) -> list[str]:
    """Telegram lines due now: a bill generated today, and each reminder day before the due date."""
    bills = load(session.state_dir)
    today, lines = session.today, []
    for st in statements(session):
        days = (st.due - today).days
        if days in session.settings.bill_remind_days and session.state.once(f"bill-due:{st.key}:{today.isoformat()}"):
            when = "today" if days == 0 else f"in {days} days ({st.due:%-d %b})"
            lines.append(f"💳 {st.name}{money(st.amount)} due {when} · /bills to mark it paid")
    if not bills:
        return lines
    sync(session, bills)
    for cyc in open_cycles(session, bills):
        days = (cyc.due - today).days
        if cyc.generated == today and session.state.once(f"bill-gen:{cyc.key}:{today.isoformat()}"):
            lines.append(f"📄 {cyc.bill.name} bill generated today, due {cyc.due:%-d %b}{money(cyc.bill.amount)}")
        if cyc.generated <= today and days in session.settings.bill_remind_days \
                and session.state.once(f"bill-due:{cyc.key}:{today.isoformat()}"):
            when = "today" if days == 0 else f"in {days} days ({cyc.due:%-d %b})"
            lines.append(f"💳 {cyc.bill.name}{money(cyc.bill.amount)} due {when} · /bills to mark it paid")
    return lines
