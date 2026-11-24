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

import difflib
import json
import shutil
import subprocess
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from orchestrator.brief.net import Http

from . import profile as profiles
from . import audio, broll, custom, direction, sound, voice
from .profile import Profile
from .settings import Keys, Settings
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
    notes: tuple[str, ...] = ()  # custom scenes: built, cached, given, or drawn as their fallback and why


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


def _caption(marked: str, start: float, end: float, times: tuple[tuple[float, float], ...]) -> list[dict[str, Any]]:
    """A sentence's caption words; split by its directions, each part over its own time (a [beat] stays silent
    on screen too). A Hinglish sentence spoken as one part is spread over the whole sentence."""
    texts = [p.text for p in direction.parse(marked).parts]
    if len(times) == len(texts) > 1:
        return [w for text, (a, b) in zip(texts, times) for w in word_times(text, a, b)]
    return word_times(direction.strip(marked), start, end)


def _asset(board: Storyboard, job: Path, n: int, src: str) -> str:
    if not src or src.startswith("https://"):
        return src
    name = f"assets/{n:02d}-{Path(src).name}"
    (job / "assets").mkdir(exist_ok=True)
    shutil.copyfile(board.folder / src, job / name)
    return name


def _with_assets(value: Any, copy: Any) -> Any:
    """The scene's fields as JSON, each ``src`` (nested ones too) copied into the job folder."""
    if isinstance(value, dict):
        return {k: copy(v) if k == "src" else _with_assets(v, copy) for k, v in value.items()}
    if isinstance(value, list):
        return [_with_assets(v, copy) for v in value]
    return value


def props(board: Storyboard, job: Path, speech: voice.Speech, look: Profile) -> dict[str, Any]:
    spans = list(speech.lines)
    scenes, words, used = [], [], 0
    for n, scene in enumerate(board.scenes):
        said = voice.sentences(scene.marked)
        mine = spans[used:used + len(said)]
        used += len(said)
        parts = speech.parts[used - len(said):used] if speech.parts else [()] * len(said)
        for text, (_spoken, start, end), times in zip(said, mine, parts):
            words += _caption(text, start, end, times)
        fields = _with_assets(json.loads(json.dumps(dict(scene.fields), default=dict)),
                              lambda src, n=n: _asset(board, job, n, src))
        start = 0.0 if n == 0 else mine[0][1]
        beats = [round(s - start, 3) for _t, s, _e in mine]  # each sentence's start, from the scene's start
        scenes.append({"type": scene.type, "start": start, "end": mine[-1][2], "beats": beats,
                       "enter": scene.enter, "exit": scene.exit, "transition": scene.transition,
                       "emoji": scene.emoji, **fields})
    if used != len(spans):
        raise VideoError(f"The voice gave {len(spans)} sentences for {used}; nothing rendered")
    return {"profile": look.render_props(), "audio": speech.path.name, "seconds": round(speech.seconds + TAIL, 3), "scenes": scenes, "words": words}


def render_args(settings: Settings, job: Path, out: Path, entry: str = "src/index.ts") -> list[str]:
    args = [str(PROJECT / "node_modules/.bin/remotion"), "render", entry, "Short", str(out),
            f"--props={job / 'props.json'}", f"--public-dir={job}", "--codec=h264",
            f"--crf={settings.video_crf}", f"--x264-preset={settings.video_preset}", "--image-format=jpeg",
            "--color-space=bt709",  # without it the file is tagged full-range JPEG colour (yuvj420p, found by qc.py)
            f"--jpeg-quality={settings.video_jpeg_quality}", "--pixel-format=yuv420p", "--audio-codec=aac",
            f"--audio-bitrate={settings.video_audio_bitrate}", f"--concurrency={settings.video_concurrency}",
            "--log=error"]
    if settings.video_browser:
        args.append(f"--browser-executable={settings.video_browser}")
    return args


WORLD = PROJECT / "node_modules/world-atlas/countries-50m.json"
ALIASES = {"usa": "United States of America", "us": "United States of America", "america": "United States of America",
           "uk": "United Kingdom", "britain": "United Kingdom", "uae": "United Arab Emirates",
           "russia": "Russia", "south korea": "South Korea", "korea": "South Korea"}


def check_countries(board: Storyboard, world: Path = WORLD) -> Storyboard:
    """Map scenes' country names → the map data's spelling (aliases like USA/UK allowed); a name it does
    not have is refused with the closest matches, before anything is spoken."""
    names = {g["properties"]["name"].lower(): g["properties"]["name"]
             for g in json.loads(world.read_text(encoding="utf-8"))["objects"]["countries"]["geometries"]}
    def fix(n: int, name: str) -> str:
        found = names.get(ALIASES.get(name.lower(), name).lower())
        if not found:
            near = difflib.get_close_matches(name.lower(), names, n=3, cutoff=0.6)
            hint = f"; did you mean {', '.join(names[c] for c in near)}?" if near else ""
            raise VideoError(f"scene {n + 1}: no country called {name!r} on the map{hint}")
        return found
    scenes = []
    for n, scene in enumerate(board.scenes):
        if scene.type == "map":
            f = dict(scene.fields)
            f["focus"] = fix(n, f["focus"]) if f["focus"] else ""
            f["highlight"] = tuple(fix(n, c) for c in f["highlight"])
            f["route"] = tuple(fix(n, c) for c in f["route"])
            scene = replace(scene, fields=MappingProxyType(f))
        scenes.append(scene)
    return replace(board, scenes=tuple(scenes))


def voiced(settings: Settings, look: Profile) -> Settings:
    """The studio settings with the page profile's voice in place of studio.engine/voice/speed/pause."""
    v = look.section("voice")
    return replace(settings, engine=v["engine"], voice_en=v["voice_en"], voice_hi=v["voice_hi"],
                   speed=float(v["speed"]), pause=float(v["pause"]))


def make(http: Http, keys: Keys, settings: Settings, home: Path, board: Storyboard, out: Path,
         profile_name: str = "") -> Video:
    """``profile_name`` (or the storyboard's, or studio.profile) picks the page profile. Custom scenes are
    built and checked first (custom.py); one that fails is drawn as its fallback and named in ``notes``."""
    look = profiles.load(profile_name or board.profile or settings.profile, home)
    if not (PROJECT / "node_modules/.bin/remotion").is_file():
        raise VideoError("Remotion is not installed: run orchestrator/studio/install.sh (needs Node 18+)")
    job = home / "studio" / "video" / f"{datetime.now():%Y%m%d-%H%M%S-%f}"  # two renders may start in one second
    job.mkdir(parents=True)
    built = custom.prepare(http, keys, settings, home, board, look, job)
    try:  # from here the job's entry folder exists: whatever fails, it is removed
        footage, found = broll.resolve(http, keys, home, built.board, look)  # stock: images → files, credited
        built = replace(built, board=footage, notes=built.notes + found)
        return _render(http, keys, settings, home, check_countries(built.board), out, look, job, built)
    finally:
        custom.clean(built.entry)


def _render(http: Http, keys: Keys, settings: Settings, home: Path, board: Storyboard, out: Path, look: Profile,
            job: Path, built: custom.Result) -> Video:
    started = time.monotonic()
    text = "\n".join(scene.say for scene in board.scenes)
    speech = voice.speak(http, keys.gemini, voiced(settings, look), home, text, job / "voice.wav")
    made = props(board, job, replace(speech, path=job / "soundtrack.wav"), look)
    chosen = sound.plan(http, home, look, made, board.title)  # effects on the cuts, music under the voice
    audio.normalize(sound.mix(home, speech.path, chosen, made["seconds"], job / "mix.wav"), job / "soundtrack.wav")
    voice_took = time.monotonic() - started
    (job / "props.json").write_text(json.dumps(made, ensure_ascii=False), encoding="utf-8")
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        done = subprocess.run(render_args(settings, job, out, built.entry), cwd=PROJECT, capture_output=True, text=True,
                              timeout=RENDER_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise VideoError(f"The render took over {RENDER_TIMEOUT // 60} minutes; job kept in {job}") from None
    (job / "render.log").write_text(done.stdout + done.stderr, encoding="utf-8")
    if done.returncode != 0 or not out.is_file():
        tail = (done.stderr or done.stdout).strip().splitlines()[-1:] or ["no error text"]
        raise VideoError(f"Remotion failed: {tail[0][:200]} (log: {job / 'render.log'})")
    return Video(out, speech.seconds + TAIL, job, voice_took, time.monotonic() - started,
                 built.notes + chosen.notes)
