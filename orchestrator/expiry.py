"""Expired approvals stay remembered until you act, so the evening recap can remind you.

A workflow keeps a waiting plan in a file (``pending.json``, ``pending-slack.json`` …). When it expires
unapproved, ``expire`` renames it to ``<name>.expired.json`` instead of deleting it; ``clear`` removes
that marker when you make the plan again or say ``no``. ``orchestrator/recap`` reads both.
"""

from __future__ import annotations

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
