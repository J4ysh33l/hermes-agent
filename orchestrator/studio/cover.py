"""A cover (thumbnail) for a storyboard: one of its scenes, fully arrived, under 2–5 huge words in the
page's caption font (the last word in the accent). Rendered as a 1080×1920 PNG with Remotion's still
renderer from the same scene code as the video, so it always matches; no voice is needed.

PLAYBOOK § 9: one striking visual + 2–4 huge words that add to the title rather than repeat it.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator.brief.net import Http

from . import custom, video
from . import profile as profiles
from .settings import Keys, Settings
from .storyboard import Storyboard
from .voice import sentences

FRAMES = 120  # remotion/src/Root.tsx COVER_FRAMES; the still is the last frame
MAX_WORDS = 5
TIMEOUT = 300


class CoverError(Exception):
    """Shown as it is; no cover was made."""


def props(board: Storyboard, n: int, words: str, job: Path, look: profiles.Profile) -> dict[str, Any]:
    scene = board.scenes[n]
    fields = video._with_assets(json.loads(json.dumps(dict(scene.fields), default=dict)),
                                lambda src: video._asset(board, job, n, src))
    beats = [0.0] * max(1, len(sentences(scene.say)))  # every part already said
    return {"profile": look.render_props(), "words": words,
            "scene": video.scene_props({"type": scene.type, "start": 0.0, "end": FRAMES / 30, "beats": beats,
                                        "enter": scene.enter, "exit": scene.exit, "transition": "",
                                        "emoji": scene.emoji}, fields)}


def still_args(settings: Settings, job: Path, out: Path, entry: str = "src/index.ts") -> list[str]:
    args = [str(video.PROJECT / "node_modules/.bin/remotion"), "still", entry, "Cover", str(out),
            f"--props={job / 'props.json'}", f"--public-dir={job}", f"--frame={FRAMES - 1}", "--image-format=png",
            "--log=error"]
    if settings.video_browser:
        args.append(f"--browser-executable={settings.video_browser}")
    return args


def make(http: Http, keys: Keys, settings: Settings, home: Path, board: Storyboard, out: Path, scene: int = 1,
         words: str = "", profile_name: str = "") -> Path:
    """``scene`` counts from 1 (the hook); ``words`` defaults to the storyboard's title. A custom scene is
    built and checked like in the video (custom.py: cached, so a video's own scene costs nothing more), or
    drawn as its fallback."""
    words = " ".join((words or board.title).split())
    if not words:
        raise CoverError("A cover needs 2–5 words: --words \"...\" (the storyboard has no title)")
    if len(words.split()) > MAX_WORDS:
        raise CoverError(f"At most {MAX_WORDS} words on a cover; {len(words.split())} given: {words!r}")
    if not 1 <= scene <= len(board.scenes):
        raise CoverError(f"Scene {scene}? The storyboard has {len(board.scenes)}")
    if not (video.PROJECT / "node_modules/.bin/remotion").is_file():
        raise CoverError("Remotion is not installed: run orchestrator/studio/install.sh (needs Node 18+)")
    look = profiles.load(profile_name or board.profile or settings.profile, home).with_theme(board.theme)
    board = video.check_countries(board)
    job = home / "studio" / "cover" / f"{datetime.now():%Y%m%d-%H%M%S-%f}"
    job.mkdir(parents=True)
    built = custom.prepare(http, keys, settings, home, replace(board, scenes=(board.scenes[scene - 1],)), look, job)
    (job / "props.json").write_text(json.dumps(props(built.board, 0, words, job, look), ensure_ascii=False),
                                    encoding="utf-8")
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        done = subprocess.run(still_args(settings, job, out, built.entry), cwd=video.PROJECT, capture_output=True,
                              text=True, timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise CoverError(f"The cover took over {TIMEOUT // 60} minutes; job kept in {job}") from None
    finally:
        custom.clean(built.entry)
    (job / "render.log").write_text(done.stdout + done.stderr, encoding="utf-8")
    if done.returncode != 0 or not out.is_file():
        tail = (done.stderr or done.stdout).strip().splitlines()[-1:] or ["no error text"]
        raise CoverError(f"Remotion failed: {tail[0][:200]} (log: {job / 'render.log'})")
    return out
