"""``/studio`` in Telegram: video, audio, b-roll and images. For now: ``voice`` (Kokoro)."""

from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path

from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http, UrllibHttp
from orchestrator.brief.store import default_state_dir
from orchestrator.notes.errors import NotesError
from orchestrator.notes.telegram import Telegram

from . import settings, voice

HELP = """**/studio** — video, audio, b-roll and images, made on your server
/studio voice <text> — Kokoro reads it and sends you the clip (free, no limits, runs on the server CPU)
  English sentences use studio.voice_en; Hindi in Devanagari uses studio.voice_hi. Hinglish typed in
  Latin script is first written in Devanagari by Gemini (one call), since Kokoro can't read it otherwise.
/studio voices — the voice names you can set in brief.yaml (studio.voice_en, studio.voice_hi)
More (videos, b-roll, images) is on its way. /menu — all your commands"""
HELP_WORDS = {"help", "-help", "--help", "-h", "?"}


class Context:
    def __init__(self, home: Path, http: Http | None = None) -> None:
        self.home = home
        self.http = http or UrllibHttp(timeout=120)
        self.settings = settings.load(home / "brief")
        self.secrets = Secrets(home / ".env", home / "brief" / "tokens")

    @property
    def key(self) -> str:
        return self.secrets.get("GEMINI_API_KEY", "GOOGLE_API_KEY")


def _ogg(wav: Path) -> Path:
    """Telegram plays OGG Opus as a voice message; without ffmpeg the WAV is sent as a file."""
    out = wav.with_suffix(".ogg")
    done = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-c:a", "libopus", "-b:a", "48k", str(out)],
                          capture_output=True, timeout=300, check=False)
    return out if done.returncode == 0 and out.is_file() else wav


def _voice(ctx: Context, text: str) -> str:
    if not text.strip():
        return "What should it say? /studio voice <text>"
    out = ctx.home / "studio" / "voice" / f"{datetime.now():%Y%m%d-%H%M%S}.wav"
    started = time.monotonic()
    speech = voice.speak(ctx.http, ctx.key, ctx.settings, ctx.home, text, out)
    took = time.monotonic() - started
    clip = _ogg(speech.path)
    method, field = ("sendVoice", "voice") if clip.suffix == ".ogg" else ("sendDocument", "document")
    Telegram(ctx.http, ctx.secrets).upload(method, field, clip, f"🔊 {speech.seconds:.1f} s")
    note = f" · {speech.rewritten} Hinglish line(s) written in Devanagari by Gemini" if speech.rewritten else ""
    return f"🔊 Sent: {speech.seconds:.1f} s of speech, made in {took:.0f} s{note}. File: {clip}"


def _voices(ctx: Context, _text: str) -> str:
    names = voice.voices(ctx.settings, ctx.home).split()
    groups = {"English (US)": ("af_", "am_"), "English (UK)": ("bf_", "bm_"), "Hindi": ("hf_", "hm_")}
    lines = [f"{label}: " + " ".join(n for n in names if n.startswith(prefix)) for label, prefix in groups.items()]
    return "\n".join(["**Kokoro voices** (f = female, m = male)", *lines,
                      f"Now: studio.voice_en = {ctx.settings.voice_en}, studio.voice_hi = {ctx.settings.voice_hi}"])


STEPS = {"voice": _voice, "say": _voice, "voices": _voices}


def handle(raw: str, home: Path | None = None, http: Http | None = None) -> str:
    word, _, rest = (raw or "").strip().partition(" ")
    step = STEPS.get(word.lower())
    if step is None or word.lower() in HELP_WORDS:
        return HELP
    try:
        return step(Context(home or default_state_dir().parent, http), rest)
    except (voice.VoiceError, NotesError) as exc:
        return f"⚠️ {exc}"
