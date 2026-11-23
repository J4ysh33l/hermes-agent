"""``python -m orchestrator.myday <command>``.

morning — the 07:30 card (Hermes cron, no agent): prints it, sends any streak animation.
tick    — every 15 minutes: To Do completions, bill reminders, the wrap-up, the Sunday goals review.
          Prints nothing when nothing is due, so Hermes sends nothing.
day, bills, goals — the same as the Telegram commands (for testing on the host).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import card, celebrate, chat
from .errors import MyDayError
from .game import with_badge
from .session import Session

CHAT = {"day": chat.handle_day, "bills": chat.handle_bills, "goals": chat.handle_goals}
SCHEDULED = {"morning": card.morning, "tick": card.tick}


def scheduled(name: str, state_dir: Path | None) -> int:
    session = Session(state_dir)
    try:
        reply = SCHEDULED[name](session)
    except MyDayError as exc:
        session.save()
        print(with_badge(f"⚠️ My day: {exc}", session.state_dir))
        return 0
    session.save()
    notes = celebrate.send(session, reply.events)
    text = "\n".join(x for x in [reply.text, *notes] if x)
    if text:
        print(with_badge(text, session.state_dir))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.myday")
    parser.add_argument("--state-dir", type=Path, default=None, help="default: $HERMES_HOME/myday")
    parser.add_argument("command", choices=sorted([*CHAT, *SCHEDULED]))
    parser.add_argument("words", nargs="*")
    args = parser.parse_args(argv)
    if args.command in SCHEDULED:
        return scheduled(args.command, args.state_dir)
    print(with_badge(CHAT[args.command](" ".join(args.words), args.state_dir), args.state_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
