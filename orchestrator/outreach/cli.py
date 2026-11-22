"""``python -m orchestrator.outreach <command> <words>``.

draft  — what Hermes' agent runs for "tell Priya…" / "set up 1:1s…": saves a plan, prints it.
         It cannot send; you approve in Telegram with /slack yes or /meet yes.
slack, meet — the same as the Telegram commands (for testing on the host).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import chat

RUN = {"draft": chat.draft, "slack": chat.handle_slack, "meet": chat.handle_meet}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.outreach")
    parser.add_argument("--state-dir", type=Path, default=None, help="default: $HERMES_HOME/brief")
    parser.add_argument("command", choices=sorted(RUN))
    parser.add_argument("words", nargs="+")
    args = parser.parse_args(argv)
    print(RUN[args.command](" ".join(args.words), args.state_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
