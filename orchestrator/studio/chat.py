"""``/studio`` in Telegram: video, audio, b-roll and images. For now: ``voice`` (Kokoro or Edge TTS)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http, UrllibHttp
from orchestrator.brief.store import default_state_dir
from orchestrator.notes.errors import NotesError
from orchestrator.notes.telegram import Telegram

from . import profile, queue, settings, voice, writer

HELP = """**/studio** — video, audio, b-roll and images, made on your server
/studio voice <text> — read aloud with studio.engine and sent to you as a voice message
/studio voice kokoro <text> · /studio voice edge <text> — pick the engine for this one
  Kokoro: on the server CPU, free, no limits. Edge: Microsoft's online voices (Indian English and
  Hindi), no CPU, but unofficial: it can stop working without notice.
  English sentences use the English voice; Hindi in Devanagari the Hindi one. Hinglish typed in Latin
  script is first written in Devanagari by Gemini (one call): neither engine reads it well otherwise.
/studio voices · /studio voices edge — voice names to set in brief.yaml (studio.voice_en, edge_voice_en …)
/studio write <notes or a draft script> — a storyboard with 3 hooks, written to your page profile by
  Claude (studio.writer; needs ANTHROPIC_API_KEY). /studio write gemini <notes> — by Gemini's free models.
  Numbers, quotes and headlines on screen must be in your notes, so include the facts you want shown.
/studio make <notes> — write it now and render it tonight (studio.render_window): you get the video, the
  cover and hooks 2–3 as clips here, and on Drive. /studio make gemini <notes> — written by Gemini.
/studio queue — the jobs · /studio pick <job> <n> — re-render with hook n · /studio run — render now
/menu — all your commands"""
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

    @property
    def keys(self) -> settings.Keys:
        return settings.Keys(self.key, self.secrets.get("ANTHROPIC_API_KEY"))


def _ogg(wav: Path) -> Path:
    """Telegram plays OGG Opus as a voice message; without ffmpeg the WAV is sent as a file."""
    out = wav.with_suffix(".ogg")
    done = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-c:a", "libopus", "-b:a", "48k", str(out)],
                          capture_output=True, timeout=300, check=False)
    return out if done.returncode == 0 and out.is_file() else wav


def _engine(ctx: Context, text: str) -> tuple[str, str]:
    first, _, rest = text.strip().partition(" ")
    return (first.lower(), rest) if first.lower() in settings.ENGINES else (ctx.settings.engine, text)


def _voice(ctx: Context, text: str) -> str:
    engine, text = _engine(ctx, text)
    if not text.strip():
        return "What should it say? /studio voice <text>"
    out = ctx.home / "studio" / "voice" / f"{datetime.now():%Y%m%d-%H%M%S}-{engine}.wav"
    started = time.monotonic()
    speech = voice.speak(ctx.http, ctx.key, ctx.settings, ctx.home, text, out, engine)
    took = time.monotonic() - started
    clip = _ogg(speech.path)
    method, field = ("sendVoice", "voice") if clip.suffix == ".ogg" else ("sendDocument", "document")
    Telegram(ctx.http, ctx.secrets).upload(method, field, clip, f"🔊 {engine}, {speech.seconds:.1f} s")
    note = f" · {speech.rewritten} Hinglish line(s) written in Devanagari by Gemini" if speech.rewritten else ""
    return f"🔊 Sent ({engine}): {speech.seconds:.1f} s of speech, made in {took:.0f} s{note}. File: {clip}"


VOICE_GROUPS = {
    "kokoro": {"English (US)": ("af_", "am_"), "English (UK)": ("bf_", "bm_"), "Hindi": ("hf_", "hm_")},
    "edge": {"English (India)": ("en-IN-",), "Hindi": ("hi-IN-",), "English (US)": ("en-US-",),
             "English (UK)": ("en-GB-",)},
}


def _voices(ctx: Context, text: str) -> str:
    engine, _ = _engine(ctx, text)
    names = voice.voices(ctx.settings, ctx.home, engine)
    lines = [f"{label}: " + " ".join(n for n in names if n.startswith(prefixes))
             for label, prefixes in VOICE_GROUPS[engine].items()]
    s = ctx.settings
    now = f"studio.voice_en = {s.voice_en}, voice_hi = {s.voice_hi}" if engine == "kokoro" else \
        f"studio.edge_voice_en = {s.edge_voice_en}, edge_voice_hi = {s.edge_voice_hi}"
    return "\n".join([f"**{engine} voices**" + (" (f = female, m = male)" if engine == "kokoro" else ""), *lines,
                      f"Now: {now}"])


def _write(ctx: Context, text: str) -> str:
    first, _, rest = text.strip().partition(" ")
    named = first.lower() in settings.WRITERS
    notes = rest if named else text
    who = writer.choose(ctx.settings, first.lower() == "claude", first.lower() == "gemini")
    if not notes.strip():
        return "What is the video about? /studio write <notes or a draft script>"
    look = profile.load(ctx.settings.profile, ctx.home)
    folder = ctx.home / "studio" / "write" / f"{datetime.now():%Y%m%d-%H%M%S}"
    draft = writer.write(ctx.http, ctx.keys, ctx.settings, look, notes, 0, folder, who)
    saved = writer.save(draft, folder / "storyboard.json", look.name)
    if draft.wishes:
        writer.remember(draft, ctx.home, notes)
    hooks = [f"{n}. ({h.family}) {h.scene['say']}" for n, h in enumerate(draft.hooks, 1)]
    body = [f"[{s['type']}] {s['say']}" for s in draft.scenes]
    extra = [f"⚠️ {n}" for n in draft.notes] + [f"💭 wish: {w}" for w in draft.wishes]
    return "\n".join([f"🎬 **{draft.title}** · {draft.words()} words (~{draft.words() / writer.WPM * 60:.0f} s) · "
                      f"{draft.model}", "", "**Hooks**", *hooks, "", "**Script** (after the hook)", *body,
                      *([""] + extra if extra else []), "", f"Saved: {saved[0].parent} (storyboard.json = hook 1, "
                      f".hook2/.hook3 = the others)"])


def _make(ctx: Context, text: str) -> str:
    first, _, rest = text.strip().partition(" ")
    who = first.lower() if first.lower() in settings.WRITERS else ""
    job = queue.add(ctx, rest if who else text, who)
    if job.state == "writing":
        return (f"✍️ Job {job.id}: Claude is writing it through the handoff repo (issue #{job.data['issue']}). "
                f"It renders in {ctx.settings.render_window} once written; /studio queue to check.")
    script = job.folder.joinpath("storyboard.txt").read_text(encoding="utf-8")
    return (f"✍️ Job {job.id} written by {job.data['writer']}; renders in {ctx.settings.render_window} "
            f"(or /studio run now). You get the video, the cover and hooks 2–3 as clips; /studio pick "
            f"{job.id} <n> re-renders with another hook.\n\n{script}")


def _run(ctx: Context, _text: str) -> str:
    log = ctx.home / "studio" / "queue" / "run.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as out:  # detached: a render takes minutes; it reports to Telegram itself
        subprocess.Popen([sys.executable, "-m", "orchestrator.studio", "queue", "run", "--now", "--notify"],
                         cwd=REPO, env={**os.environ, "HERMES_HOME": str(ctx.home)}, stdout=out, stderr=out,
                         start_new_session=True)
    return "🎬 Rendering the queue now; each video comes here when it is done."


def _pick(ctx: Context, text: str) -> str:
    parts = text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return "/studio pick <job id> <hook 1-3>"
    job = queue.pick(ctx, parts[0], int(parts[1]))
    return f"Job {job.id} will be rendered with hook {parts[1]} (next run, or /studio run)."


STEPS = {"voice": _voice, "say": _voice, "voices": _voices, "write": _write, "make": _make, "run": _run,
         "pick": _pick, "queue": lambda ctx, _text: queue.status(ctx)}
REPO = Path(__file__).resolve().parents[2]


def handle(raw: str, home: Path | None = None, http: Http | None = None) -> str:
    word, _, rest = (raw or "").strip().partition(" ")
    step = STEPS.get(word.lower())
    if step is None or word.lower() in HELP_WORDS:
        return HELP
    try:
        return step(Context(home or default_state_dir().parent, http), rest)
    except (voice.VoiceError, NotesError, writer.WriterError, profile.ProfileError, queue.QueueError,
            queue.HandoffError) as exc:
        return f"⚠️ {exc}"
