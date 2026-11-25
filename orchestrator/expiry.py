"""Expired approvals stay remembered until you act, so the evening recap can remind you.

A workflow keeps a waiting plan in a file (``pending.json``, ``pending-slack.json`` …). When it expires
unapproved, ``expire`` renames it to ``<name>.expired.json`` instead of deleting it; ``clear`` removes
that marker when you make the plan again or say ``no``; ``resume`` puts it back to wait for your yes
with a fresh clock (``/resume``). ``orchestrator/recap`` reads both.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def marker(path: Path) -> Path:
    return path.with_name(path.stem + ".expired.json")


def expire(path: Path) -> None:
    path.replace(marker(path))


def clear(path: Path) -> bool:
    """Forget an expired plan; True if there was one."""
    found = marker(path).is_file()
    marker(path).unlink(missing_ok=True)
    return found


def resume(path: Path, now: float) -> None:
    """The expired plan waits again, its clock restarted (the file stays private, 0600)."""
    data = json.loads(marker(path).read_text(encoding="utf-8"))
    data["created"] = now
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    marker(path).unlink()
