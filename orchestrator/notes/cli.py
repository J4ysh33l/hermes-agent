"""``python -m orchestrator.notes run`` (the ``notes`` cron, every 15 minutes): the calendar check at
its hours, then the queue. ``check`` asks now whatever the hour. Anything else is ``/notes`` itself.
Prints nothing when there is nothing to say, so the cron sends nothing."""

from __future__ import annotations

import sys

from orchestrator.brief.store import default_state_dir

from . import chat, work
from .errors import NotesError


def main(argv: list[str] | None = None) -> int:
    words = sys.argv[1:] if argv is None else argv
    home = default_state_dir().parent
    if words in (["run"], ["check"]):
        try:
            text = work.run(work.context(home), force_check=words == ["check"])
        except NotesError as exc:
            text = f"⚠️ Smriti: {exc}"
    else:
        text = chat.handle(" ".join(words), home)
    if text:
        print(text)
    return 0
