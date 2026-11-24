"""``/resume <n>``: bring back an approval that expired without your yes, numbered by the last recap.

It waits for your yes again with a fresh clock, after a check that sending it now is still safe
(an interview slot or a scheduled message whose time has passed, or a payslip PDF that is gone,
refuses: make it again instead). Then you see its usual preview.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from orchestrator import commands, expiry
from orchestrator.brief.store import default_state_dir

from .parts import listing_path, pending_files

HELP = """**/resume** — bring back an approval that expired without your yes
/resume 2 — number from the ⌛ lines of the last recap (/recap now). It waits for your yes again,
unless its time has passed (an interview slot, a scheduled message) or its files are gone; then make
it again. /slack no, /meet no, /hr payslip no, /hr interview no, /hr reply no drop one instead. /menu — all your commands"""


def handle(raw: str, home: Path | None = None, now: float | None = None) -> str:
    word = (raw or "").strip()
    if not word.isdigit():
        return HELP
    home = home or default_state_dir().parent
    now = time.time() if now is None else now
    listing = listing_path(home)
    shown = json.loads(listing.read_text(encoding="utf-8")) if listing.is_file() else []
    if not 1 <= int(word) <= len(shown):
        return f"No ⌛ item {word} on the last recap. See /recap now."
    item = next((p for p in pending_files(home) if str(p.path) == shown[int(word) - 1]), None)
    if item is None:
        return "That item is no longer known. See /recap now."
    if item.path.is_file():
        data = json.loads(item.path.read_text(encoding="utf-8"))
        if now - data["created"] <= item.minutes * 60:
            return f"{item.name} is already waiting for your yes: {item.command}"
        expiry.expire(item.path)  # expired but not yet noticed by its workflow
    if not expiry.marker(item.path).is_file():
        return f"{item.name} is no longer expired (made again or dropped). See /recap now."
    problems = item.check(json.loads(expiry.marker(item.path).read_text(encoding="utf-8")), now)
    if problems:
        return "\n".join([f"Can't bring back the {item.name.lower()}: " + "; ".join(problems) + ".",
                          f"Make it again, or {item.cancel} to drop it."])
    expiry.resume(item.path, now)
    head = f"▶️ {item.name} is back, waiting for your yes for {item.minutes} min."
    if item.show is None:
        return f"{head} {item.command} to go on."
    return f"{head}\n\n" + commands.dispatch(*item.show)
