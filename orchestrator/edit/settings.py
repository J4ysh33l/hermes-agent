"""The ``edit:`` section of ``$HERMES_HOME/brief/brief.yaml`` → frozen Settings for editing your footage.

The studio's own settings (its Python venv, models folder, Claude route, handoff repo, encoder quality) are
read from the same file's ``studio:`` section and reused, so the editor and the studio share one install.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from orchestrator.brief.settings import EXAMPLE
from orchestrator.studio import settings as studio_settings


@dataclass(frozen=True)
class Settings:
    style: str = "mine"  # the style used unless one is named (/edit styles)
    asr_model: str = "large-v3-turbo"  # faster-whisper model or a converted folder (e.g. a Hinglish fine-tune)
    asr_language: str = "en"  # en writes Hinglish in Latin letters; hi writes Devanagari; "" = Whisper guesses
    asr_prompt: str = ("Okay so, umm, matlab, ye SIP aapko rich nahi banayega. Uh, basically, dekho, "
                       "toh, actually, you know, haan.")  # biases Whisper to Latin Hinglish and to keep fillers
    threads: int = 2  # CPU threads for transcription and encoding
    fps: int = 30
    crf: int = 18  # the finished video (lower = sharper, bigger)
    preset: str = "medium"  # x264 for the finished video
    mezzanine_crf: int = 14  # the normalised copy every step reads (near lossless)
    approve: bool = True  # the cut list and plan come to you on Telegram before the render
    plan_retries: int = 2  # a plan that fails its checks goes back to the editor this many times
    max_minutes: float = 15.0  # longer uploads are refused (a 2-core host renders ~1 min in ~3–6 min)


def parse(raw: dict[str, Any]) -> Settings:
    edit = raw.get("edit") or {}
    base = Settings()
    unknown = set(edit) - set(Settings.__dataclass_fields__)
    if unknown:
        raise ValueError(f"brief.yaml: unknown key {min(unknown)!r} under edit")
    preset = str(edit.get("preset", base.preset))
    if preset not in studio_settings.PRESETS:
        raise ValueError(f"brief.yaml: edit.preset must be one of {', '.join(studio_settings.PRESETS)}")
    return Settings(
        style=str(edit.get("style", base.style)),
        asr_model=str(edit.get("asr_model", base.asr_model)),
        asr_language=str(edit.get("asr_language", base.asr_language) or ""),
        asr_prompt=str(edit.get("asr_prompt", base.asr_prompt)),
        threads=max(1, int(edit.get("threads", base.threads))),
        fps=int(edit.get("fps", base.fps)) if int(edit.get("fps", base.fps)) in (24, 25, 30, 60) else base.fps,
        crf=min(35, max(10, int(edit.get("crf", base.crf)))),
        preset=preset,
        mezzanine_crf=min(30, max(0, int(edit.get("mezzanine_crf", base.mezzanine_crf)))),
        approve=bool(edit.get("approve", base.approve)),
        plan_retries=min(5, max(0, int(edit.get("plan_retries", base.plan_retries)))),
        max_minutes=float(edit.get("max_minutes", base.max_minutes)),
    )


def load(state_dir: Path) -> tuple[Settings, studio_settings.Settings]:
    """``state_dir`` is ``$HERMES_HOME/brief``. Returns (edit settings, studio settings)."""
    path = state_dir / "brief.yaml"
    raw = yaml.safe_load((path if path.is_file() else EXAMPLE).read_text(encoding="utf-8")) or {}
    return parse(raw), studio_settings.parse(raw)
