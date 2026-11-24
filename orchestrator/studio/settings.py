"""The ``studio:`` section of ``$HERMES_HOME/brief/brief.yaml`` → frozen Settings (video, audio,
b-roll and images)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import re

import yaml

from orchestrator.brief.settings import EXAMPLE, ModelChoice

TEXT_MODELS = (ModelChoice("gemini-3.1-flash-lite"), ModelChoice("gemini-3.5-flash-lite"),
               ModelChoice("gemma-4-31b-it", False))


SCRIPT_MODELS = (ModelChoice("gemini-3.5-flash-lite"), ModelChoice("gemini-3.1-flash-lite"))
# Google Search on the free tier worked on these and not on the 3.x models (tested 2026-11-24)
RESEARCH_MODELS = (ModelChoice("gemini-2.5-flash-lite"), ModelChoice("gemini-2.5-flash"))
ENGINES = ("kokoro", "edge")
PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")


def _preset(value: str) -> str:
    if value not in PRESETS:
        raise ValueError(f"brief.yaml: studio.video_preset must be one of {', '.join(PRESETS)}")
    return value


EFFORTS = ("low", "medium", "high", "xhigh", "max")


VIAS = ("auto", "api", "handoff")


def _choice(key: str, value: str, options: tuple[str, ...]) -> str:
    if value not in options:
        raise ValueError(f"brief.yaml: studio.{key} must be one of {', '.join(options)}")
    return value


def _window(value: str) -> str:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("brief.yaml: studio.render_window is like 00:30-07:00")
    return value


def _writer(value: str) -> str:
    if value not in WRITERS:
        raise ValueError(f"brief.yaml: studio.writer must be one of {', '.join(WRITERS)}")
    return value


def _effort(value: str) -> str:
    if value not in EFFORTS:
        raise ValueError(f"brief.yaml: studio.claude_effort must be one of {', '.join(EFFORTS)}")
    return value


@dataclass(frozen=True)
class Keys:
    """API keys from $HERMES_HOME/.env (never brief.yaml)."""
    gemini: str = ""
    claude: str = ""
    pexels: str = ""  # stock b-roll (broll.py)
    pixabay: str = ""


WRITERS = ("claude", "gemini")


@dataclass(frozen=True)
class Settings:
    engine: str = "kokoro"  # kokoro (local, free, no limits) or edge (Microsoft's online voices, unofficial)
    voice_en: str = "am_puck"  # Kokoro voice for English (/studio voices); your second pick: am_fenrir
    voice_hi: str = "hm_omega"  # Kokoro voice for Hindi (Devanagari text)
    edge_voice_en: str = "en-IN-PrabhatNeural"  # Edge voice for English (/studio voices edge)
    edge_voice_hi: str = "hi-IN-MadhurNeural"  # Edge voice for Hindi (Devanagari text)
    speed: float = 1.0  # 0.5 to 2.0; a page profile's voice.speed wins (default profile: 1.15 ≈ 196 wpm on real scripts)
    pause: float = 0.15  # seconds of silence after each sentence
    profile: str = "default"  # the page profile videos use unless one is named (studio/profiles)
    threads: int = 2  # CPU threads Kokoro may use
    kokoro_model: str = "kokoro-v1.0.fp16.onnx"  # 169 MB, ~520 MB RAM; kokoro-v1.0.int8.onnx: ~410 MB, slower
    studio_python: str = ""  # "" = $HERMES_HOME/venvs/studio/bin/python (orchestrator/studio/install.sh)
    models_dir: str = ""  # "" = $HERMES_HOME/studio/models
    max_chars: int = 6000  # text spoken in one job
    # Video (1080×1920, 30 fps). Lower crf = sharper, bigger file (17 ≈ visually lossless; 23 is ffmpeg's default).
    video_crf: int = 17
    video_preset: str = "slow"  # x264: ultrafast … medium … slow … veryslow (slower = smaller file, same quality)
    video_jpeg_quality: int = 95  # frames as Chrome draws them, before encoding
    video_audio_bitrate: str = "320k"  # AAC
    video_concurrency: int = 1  # frames drawn at once; each Chrome tab needs ~0.5–1 GB
    video_browser: str = ""  # Chrome headless shell to use; "" = the one Remotion downloaded (install.sh)
    text_models: tuple[ModelChoice, ...] = TEXT_MODELS  # small text jobs (Hinglish → Devanagari)
    script_models: tuple[ModelChoice, ...] = SCRIPT_MODELS  # notes → storyboard (writer.py); a stronger model writes better
    writer: str = "claude"  # who writes storyboards: claude (default; ANTHROPIC_API_KEY, paid) or gemini (free)
    claude_model: str = "claude-opus-5-5"  # writes storyboards and builds custom scenes (~$0.10–0.25 a storyboard)
    custom_review: bool = True  # Claude looks at frames of each custom scene it built and fixes what is off
    claude_via: str = "handoff"  # handoff (your Claude plan, via the private handoff repo; default) | api | auto
    handoff_repo: str = ""  # "" = notes.handoff_repo (orchestrator/HANDOFF.md)
    direction_retries: int = 2  # a storyboard that fails its checks goes back to the director this many times
    research: bool = True  # before the script, a researcher finds current facts with Google Search (research.py)
    research_models: tuple[ModelChoice, ...] = RESEARCH_MODELS  # Gemini models that may search, tried in order
    render_window: str = "00:30-07:00"  # the queue renders only in this window (local time); /studio run = now
    hook_clips: bool = True  # also render hooks 2 and 3 as short clips, so you can pick one on Telegram
    claude_effort: str = "medium"  # low | medium | high | xhigh | max: how hard Claude thinks


def parse(raw: dict[str, Any]) -> Settings:
    studio = raw.get("studio") or {}
    base = Settings()
    unknown = set(studio) - set(Settings.__dataclass_fields__)
    if unknown:
        raise ValueError(f"brief.yaml: unknown key {min(unknown)!r} under studio")
    models = studio.get("text_models")
    script = studio.get("script_models")
    engine = str(studio.get("engine", base.engine))
    if engine not in ENGINES:
        raise ValueError(f"brief.yaml: studio.engine must be one of {', '.join(ENGINES)}")
    return Settings(
        engine=engine,
        voice_en=str(studio.get("voice_en", base.voice_en)),
        voice_hi=str(studio.get("voice_hi", base.voice_hi)),
        edge_voice_en=str(studio.get("edge_voice_en", base.edge_voice_en)),
        edge_voice_hi=str(studio.get("edge_voice_hi", base.edge_voice_hi)),
        speed=min(2.0, max(0.5, float(studio.get("speed", base.speed)))),
        pause=float(studio.get("pause", base.pause)),
        profile=str(studio.get("profile", base.profile)),
        threads=int(studio.get("threads", base.threads)),
        kokoro_model=str(studio.get("kokoro_model", base.kokoro_model)),
        studio_python=str(studio.get("studio_python", base.studio_python)),
        models_dir=str(studio.get("models_dir", base.models_dir)),
        max_chars=int(studio.get("max_chars", base.max_chars)),
        video_crf=min(51, max(0, int(studio.get("video_crf", base.video_crf)))),
        video_preset=_preset(str(studio.get("video_preset", base.video_preset))),
        video_jpeg_quality=min(100, max(1, int(studio.get("video_jpeg_quality", base.video_jpeg_quality)))),
        video_audio_bitrate=str(studio.get("video_audio_bitrate", base.video_audio_bitrate)),
        video_concurrency=max(1, int(studio.get("video_concurrency", base.video_concurrency))),
        video_browser=str(studio.get("video_browser", base.video_browser)),
        text_models=tuple(ModelChoice(str(m["id"]), bool(m.get("json_mode", True))) for m in models)
        if models else base.text_models,
        writer=_writer(str(studio.get("writer", base.writer))),
        claude_via=_choice("claude_via", str(studio.get("claude_via", base.claude_via)), VIAS),
        handoff_repo=str(studio.get("handoff_repo", "") or (raw.get("notes") or {}).get("handoff_repo", "")),
        direction_retries=min(5, max(0, int(studio.get("direction_retries", base.direction_retries)))),
        research=bool(studio.get("research", base.research)),
        research_models=tuple(ModelChoice(str(m["id"])) for m in studio["research_models"])
        if studio.get("research_models") else base.research_models,
        render_window=_window(str(studio.get("render_window", base.render_window))),
        hook_clips=bool(studio.get("hook_clips", base.hook_clips)),
        custom_review=bool(studio.get("custom_review", base.custom_review)),
        claude_model=str(studio.get("claude_model", base.claude_model)),
        claude_effort=_effort(str(studio.get("claude_effort", base.claude_effort))),
        script_models=tuple(ModelChoice(str(m["id"]), bool(m.get("json_mode", True))) for m in script)
        if script else base.script_models,
    )


def load(state_dir: Path) -> Settings:
    """``state_dir`` is ``$HERMES_HOME/brief`` (where brief.yaml lives)."""
    path = state_dir / "brief.yaml"
    raw = yaml.safe_load((path if path.is_file() else EXAMPLE).read_text(encoding="utf-8")) or {}
    return parse(raw)
