"""Storyboard → a 1080×1920, 30 fps short: voice (``voice.speak``), word captions, Remotion render.

1. Every scene's ``say`` goes to the voice in one job; each sentence's start and end come back, so each
   scene starts when its first sentence starts and lasts until the next scene's.
2. The page profile (``profile.py``) sets the look, motion, captions and voice.
3. Captions come from the script, not a transcript (Whisper drops Hindi in mixed clips): each sentence's
   time is split over its words by length. Each scene also gets its sentences' start times ("beats"),
   so a list item or compare point appears when it is said, not on a timer. Hinglish rewritten into Devanagari for the voice is still
   captioned as you wrote it.
4. ``remotion/`` (React templates) renders the props in its own Node project (``install.sh``) at the
   quality set under ``studio:`` (crf 17, x264 slow, JPEG frames at 95, AAC 320k by default).

Each job keeps its folder under ``$HERMES_HOME/studio/video/<time>/`` (voice.wav, props.json, assets,
render.log) so a render can be looked at or redone.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator.brief.net import Http

from dataclasses import replace

from . import profile as profiles
from . import voice
from .profile import Profile
from .settings import Settings
from .storyboard import Storyboard

PROJECT = Path(__file__).with_name("remotion")
FPS, WIDTH, HEIGHT = 30, 1080, 1920
TAIL = 0.6  # seconds after the last word
RENDER_TIMEOUT = 3600


class VideoError(Exception):
    """Shown as it is; no video was made."""


@dataclass(frozen=True)
class Video:
    path: Path
    seconds: float
    job: Path  # the job folder (voice, props, assets, log)
    voice_took: float
    render_took: float


def word_times(marked: str, start: float, end: float) -> list[dict[str, Any]]:
    """One sentence's words spread over its span by length (a long word takes longer to say).
    Words inside *asterisks* come back with ``emphasis``."""
    words, flags, inside = [], [], False
    for raw in marked.split():
        opens = raw.startswith("*")
        inside = inside or opens
        words.append(raw.replace("*", ""))
        flags.append(inside)
        inside = inside and not raw.rstrip(".,!?;:\"'()।").endswith("*")
    weights = [len(w.strip(".,!?;:\"'()।")) + 2 for w in words]
    total, at, out = sum(weights) or 1, start, []
    for word, weight, flag in zip(words, weights, flags):
        until = at + (end - start) * weight / total
        out.append({"text": word, "start": round(at, 3), "end": round(until, 3), "emphasis": flag})
        at = until
    return out


def _asset(board: Storyboard, job: Path, n: int, src: str) -> str:
    if src.startswith("https://"):
        return src
    name = f"assets/{n:02d}-{Path(src).name}"
    (job / "assets").mkdir(exist_ok=True)
    shutil.copyfile(board.folder / src, job / name)
    return name


def props(board: Storyboard, job: Path, speech: voice.Speech, look: Profile) -> dict[str, Any]:
    spans = list(speech.lines)
    scenes, words, used = [], [], 0
    for n, scene in enumerate(board.scenes):
        said = voice.sentences(scene.marked)
        mine = spans[used:used + len(said)]
        used += len(said)
        for text, (_spoken, start, end) in zip(said, mine):
            words += word_times(text, start, end)
        fields = json.loads(json.dumps(dict(scene.fields), default=dict))
        if "src" in fields:
            fields["src"] = _asset(board, job, n, fields["src"])
        start = 0.0 if n == 0 else mine[0][1]
        beats = [round(s - start, 3) for _t, s, _e in mine]  # each sentence's start, from the scene's start
        scenes.append({"type": scene.type, "start": start, "end": mine[-1][2], "beats": beats,
                       "enter": scene.enter, "exit": scene.exit, **fields})
    if used != len(spans):
        raise VideoError(f"The voice gave {len(spans)} sentences for {used}; nothing rendered")
    return {"profile": look.render_props(), "audio": speech.path.name, "seconds": round(speech.seconds + TAIL, 3), "scenes": scenes, "words": words}


def render_args(settings: Settings, job: Path, out: Path) -> list[str]:
    args = [str(PROJECT / "node_modules/.bin/remotion"), "render", "src/index.ts", "Short", str(out),
            f"--props={job / 'props.json'}", f"--public-dir={job}", "--codec=h264",
            f"--crf={settings.video_crf}", f"--x264-preset={settings.video_preset}", "--image-format=jpeg",
            f"--jpeg-quality={settings.video_jpeg_quality}", "--pixel-format=yuv420p", "--audio-codec=aac",
            f"--audio-bitrate={settings.video_audio_bitrate}", f"--concurrency={settings.video_concurrency}",
            "--log=error"]
    if settings.video_browser:
        args.append(f"--browser-executable={settings.video_browser}")
    return args


def voiced(settings: Settings, look: Profile) -> Settings:
    """The studio settings with the page profile's voice in place of studio.engine/voice/speed/pause."""
    v = look.section("voice")
    return replace(settings, engine=v["engine"], voice_en=v["voice_en"], voice_hi=v["voice_hi"],
                   speed=float(v["speed"]), pause=float(v["pause"]))


def make(http: Http, key: str, settings: Settings, home: Path, board: Storyboard, out: Path,
         profile_name: str = "") -> Video:
    """``profile_name`` (or the storyboard's, or studio.profile) picks the page profile."""
    look = profiles.load(profile_name or board.profile or settings.profile, home)
    if not (PROJECT / "node_modules/.bin/remotion").is_file():
        raise VideoError("Remotion is not installed: run orchestrator/studio/install.sh (needs Node 18+)")
    job = home / "studio" / "video" / f"{datetime.now():%Y%m%d-%H%M%S-%f}"  # two renders may start in one second
    job.mkdir(parents=True)
    started = time.monotonic()
    text = "\n".join(scene.say for scene in board.scenes)
    speech = voice.speak(http, key, voiced(settings, look), home, text, job / "voice.wav")
    voice_took = time.monotonic() - started
    (job / "props.json").write_text(json.dumps(props(board, job, speech, look), ensure_ascii=False), encoding="utf-8")
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        done = subprocess.run(render_args(settings, job, out), cwd=PROJECT, capture_output=True, text=True,
                              timeout=RENDER_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise VideoError(f"The render took over {RENDER_TIMEOUT // 60} minutes; job kept in {job}") from None
    (job / "render.log").write_text(done.stdout + done.stderr, encoding="utf-8")
    if done.returncode != 0 or not out.is_file():
        tail = (done.stderr or done.stdout).strip().splitlines()[-1:] or ["no error text"]
        raise VideoError(f"Remotion failed: {tail[0][:200]} (log: {job / 'render.log'})")
    return Video(out, speech.seconds + TAIL, job, voice_took, time.monotonic() - started)
