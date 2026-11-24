"""The ``notes:`` section of ``$HERMES_HOME/brief/brief.yaml`` → frozen Settings (Smriti, meeting notes)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from orchestrator.brief.settings import EXAMPLE

AUDIO_MODELS = ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite")  # Gemma takes no audio


@dataclass(frozen=True)
class Settings:
    check_hours: tuple[int, ...] = (10, 12, 14, 16, 18, 20)  # calendar checks (20:00: evening meetings)
    chunk_minutes: float = 45  # audio sent to Gemini per call
    gap_seconds: int = 70  # at least this long between two audio calls
    tokens_per_minute: int = 250_000  # your Gemini limit; a call waits until it fits the last 60 s
    daily_audio_minutes: int = 180  # beyond this, transcription waits for the next day
    models: tuple[str, ...] = AUDIO_MODELS
    handoff_repo: str = ""  # owner/name of the private repo Claude's scheduled task watches
    max_attempts: int = 3  # a request that fails this often is reported, not retried every run


def parse(raw: dict[str, Any]) -> Settings:
    notes = raw.get("notes") or {}
    base = Settings()
    unknown = set(notes) - set(Settings.__dataclass_fields__)
    if unknown:
        raise ValueError(f"brief.yaml: unknown key {min(unknown)!r} under notes")
    return Settings(
        check_hours=tuple(int(h) for h in notes.get("check_hours", base.check_hours)),
        chunk_minutes=float(notes.get("chunk_minutes", base.chunk_minutes)),
        gap_seconds=int(notes.get("gap_seconds", base.gap_seconds)),
        tokens_per_minute=int(notes.get("tokens_per_minute", base.tokens_per_minute)),
        daily_audio_minutes=int(notes.get("daily_audio_minutes", base.daily_audio_minutes)),
        models=tuple(str(m) for m in notes.get("models", base.models)),
        handoff_repo=str(notes.get("handoff_repo", base.handoff_repo)),
        max_attempts=int(notes.get("max_attempts", base.max_attempts)),
    )


def load(state_dir: Path) -> Settings:
    """``state_dir`` is ``$HERMES_HOME/brief`` (where brief.yaml lives)."""
    path = state_dir / "brief.yaml"
    raw = yaml.safe_load((path if path.is_file() else EXAMPLE).read_text(encoding="utf-8")) or {}
    return parse(raw)
