"""The ``watch:`` section of ``$HERMES_HOME/brief/brief.yaml`` → frozen Settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from orchestrator.brief.settings import EXAMPLE


@dataclass(frozen=True)
class Settings:
    every_hours: float = 12  # a new watch is checked this often (/watch every <n> <hours> changes one)
    claude: bool = True  # Claude researches a new plain page for a steadier source, through the handoff repo
    notes: bool = True  # Gemini adds a note to each change: which new items matter to you and why
    handoff_repo: str = ""  # owner/name; "" = notes.handoff_repo (one private repo for every handoff)
    about: str = ""  # one or two lines on you and what matters to you; Gemini reads it with every change
    fail_after: int = 3  # failed checks in a row before you are told (once)
    max_lines: int = 15  # new items listed in one message; the rest are counted


def parse(raw: dict[str, Any]) -> Settings:
    watch = raw.get("watch") or {}
    base = Settings()
    unknown = set(watch) - set(Settings.__dataclass_fields__)
    if unknown:
        raise ValueError(f"brief.yaml: unknown key {min(unknown)!r} under watch")
    return Settings(
        every_hours=float(watch.get("every_hours", base.every_hours)),
        claude=bool(watch.get("claude", base.claude)),
        notes=bool(watch.get("notes", base.notes)),
        handoff_repo=str(watch.get("handoff_repo") or (raw.get("notes") or {}).get("handoff_repo") or ""),
        about=str(watch.get("about", base.about)).strip(),
        fail_after=int(watch.get("fail_after", base.fail_after)),
        max_lines=int(watch.get("max_lines", base.max_lines)),
    )


def load(state_dir: Path) -> Settings:
    """``state_dir`` is ``$HERMES_HOME/brief`` (where brief.yaml lives)."""
    path = state_dir / "brief.yaml"
    raw = yaml.safe_load((path if path.is_file() else EXAMPLE).read_text(encoding="utf-8")) or {}
    return parse(raw)
