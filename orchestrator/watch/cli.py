"""``python -m orchestrator.watch run`` (the ``watch`` cron, every 30 minutes): checks what is due and
collects Claude's answers; prints nothing when there is nothing to say, so the cron sends nothing.
Anything else is ``/watch`` itself."""

from __future__ import annotations

import sys

from orchestrator.brief.store import default_state_dir

from . import chat, work


def main(argv: list[str] | None = None) -> int:
    words = sys.argv[1:] if argv is None else argv
    home = default_state_dir().parent
    if words == ["run"]:
        ctx = work.context(home)
        with work.one_at_a_time(home) as mine:
            text = work.tick(ctx) if mine else ""
    else:
        text = chat.handle(" ".join(words), home)
    if text:
        print(text)
    return 0
