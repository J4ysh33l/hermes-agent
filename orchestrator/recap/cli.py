"""``python -m orchestrator.recap now`` (the 20:00 cron, and ``/recap now`` in Telegram).

Prints nothing when nothing is waiting, so the cron sends nothing.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from orchestrator.brief.store import default_state_dir
from orchestrator.myday.errors import MyDayError
from orchestrator.myday.session import Session

from . import parts
from .parts import Line, RecapError

HELP = """**/recap** — what is waiting on you, by script (also every evening at 20:00)
/recap now — approvals waiting for your yes, or expired without it (until you make them again or
say no to them), HR mail with no reply, To Do tasks
and bills overdue or due in the next 3 days, and Outlook events this week named as deadlines
(deadline, due, last date, submission, expiry, renewal). /menu — all your commands"""

Part = Callable[[Session, Path], list[Line]]
PARTS: dict[str, Part] = {
    "approvals": parts.approvals,
    "HR mail": parts.hr_mail,
    "To Do": lambda session, _home: parts.tasks(session),
    "calendar": lambda session, _home: parts.calendar(session),
}


def recap(session: Session, home: Path) -> str:
    found: list[Line] = []
    failed: list[str] = []
    for name, part in PARTS.items():
        try:
            found += part(session, home)
        except (MyDayError, RecapError, OSError, ValueError) as exc:
            failed.append(f"⚠️ {name}: {exc}")
    if not found and not failed:
        return ""
    today = session.today
    overdue = sorted((l for l in found if not l.waiting and l.when < today), key=lambda l: l.when)
    soon = sorted((l for l in found if not l.waiting and l.when >= today), key=lambda l: l.when)
    waiting = [l for l in found if l.waiting]  # approvals, then HR mail urgent first (as each part orders them)
    out = [f"⏰ **Deadline recap** — {session.local_now:%a %-d %b}"]
    for title, rows in (("Waiting on you", waiting), ("Overdue", overdue), ("Coming up", soon)):
        if rows:
            out += ["", f"**{title}**", *(l.text for l in rows)]
    if failed:
        out += ["", *failed]
    return "\n".join(out)


def handle(raw: str, home: Path | None = None, session: Session | None = None) -> str:
    if (raw or "").strip().lower() != "now":
        return HELP
    home = home or default_state_dir().parent
    return recap(session or Session(home / "myday"), home) or "Nothing is waiting on you. 🎈"


def main(argv: list[str] | None = None) -> int:
    words = sys.argv[1:] if argv is None else argv
    if words != ["now"]:
        print(HELP)
        return 0
    home = default_state_dir().parent
    text = recap(Session(home / "myday"), home)
    if text:  # silent when nothing is waiting, so the cron sends nothing
        print(text)
    return 0
