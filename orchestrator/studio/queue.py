"""The studio queue: notes in, a finished video on Telegram and Drive out, rendered overnight.

A job is a folder ``$HERMES_HOME/studio/queue/<id>/`` with ``job.json`` and everything it made. States:

    writing   Claude is writing it through the handoff repo (no API key); the queue collects the answer
    ready     the storyboards are saved and checked; waits for the render window (studio.render_window)
    rendered  video (the chosen hook), hook clips, cover and the quality check are done
    done      the preview went to Telegram, and to Drive when the check passed and Drive is signed in
    failed    a step failed; the reason is in job.json and was sent to you

``/studio make <notes>`` adds a job (writing it at once through the API, or opening a handoff request),
``/studio pick <id> <n>`` re-renders it with hook n, ``/studio run`` renders now, ``/studio queue`` lists.
The ``studio`` cron (every 30 minutes) collects handoff answers and renders inside the window; one run at
a time (a lock), and a run never starts a render after the window closes.
"""

from __future__ import annotations

import fcntl
import json
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from datetime import time as clock
from pathlib import Path
from typing import Any

from orchestrator.brief.net import HttpError
from orchestrator.handoff import HandoffError
from orchestrator.notes.errors import NotesError
from orchestrator.notes.telegram import Telegram

from . import audio, cover, custom, direction, drive, handoff, profile, qc, storyboard, video, voice, writer

PROXY_MB = 48  # Telegram bots may upload 50 MB
STEP_ERRORS = (video.VideoError, cover.CoverError, qc.QcError, writer.WriterError, HandoffError, NotesError,
               drive.DriveError, audio.AudioError, storyboard.StoryboardError, profile.ProfileError,
               voice.VoiceError, custom.CustomError, HttpError, OSError, ValueError)


class QueueError(Exception):
    """Shown as it is."""


@dataclass
class Tools:
    """The slow steps (tests replace them)."""
    video: Callable[..., video.Video] = video.make
    cover: Callable[..., Path] = cover.make
    qc: Callable[..., qc.Report] = qc.run


@dataclass
class Job:
    folder: Path
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def state(self) -> str:
        return self.data["state"]

    def log(self, line: str, state: str = "") -> None:
        self.data.setdefault("log", []).append(f"{datetime.now():%Y-%m-%d %H:%M} {line}")
        if state:
            self.data["state"] = state
        self.save()

    def save(self) -> None:
        self.folder.joinpath("job.json").write_text(json.dumps(self.data, ensure_ascii=False, indent=1),
                                                    encoding="utf-8")


def root(home: Path) -> Path:
    return home / "studio" / "queue"


def load(home: Path, job_id: str) -> Job:
    folder = root(home) / job_id
    if not job_id.replace("-", "").isalnum() or not folder.joinpath("job.json").is_file():
        raise QueueError(f"No job {job_id!r} (/studio queue lists them)")
    return Job(folder, json.loads(folder.joinpath("job.json").read_text(encoding="utf-8")))


def jobs(home: Path) -> list[Job]:
    found = sorted(p.parent for p in root(home).glob("*/job.json"))
    return [load(home, p.name) for p in found]


# ---------------------------------------------------------------- adding


def route(ctx: Any, who: str = "") -> str:
    """Who writes: "gemini", "claude-api" or "handoff" (Claude on your plan, asynchronous)."""
    if who == "gemini" or (not who and ctx.settings.writer == "gemini"):
        return "gemini"
    via = ctx.settings.claude_via
    if via == "api" or (via == "auto" and ctx.keys.claude):
        return "claude-api"
    if handoff.repo(ctx.http, ctx.secrets, ctx.settings.handoff_repo).ready:
        return "handoff"
    raise writer.WriterError("Claude needs ANTHROPIC_API_KEY, or the handoff repo (studio.handoff_repo and "
                             "GITHUB_HANDOFF_TOKEN: orchestrator/HANDOFF.md). Or: /studio make gemini <notes>")


def add(ctx: Any, notes: str, who: str = "", seconds: float = 0) -> Job:
    if len(notes.split()) < 3:
        raise writer.WriterError("Give it something to work from: a topic with a few facts, or a draft script")
    look = profile.load(ctx.settings.profile, ctx.home)
    how = route(ctx, who)
    folder = _new_folder(root(ctx.home), f"{datetime.now():%Y%m%d-%H%M%S}")
    folder.joinpath("notes.txt").write_text(notes, encoding="utf-8")
    job = Job(folder, {"id": folder.name, "created": datetime.now().isoformat(timespec="seconds"),
                       "profile": look.name, "seconds": seconds, "hook": 1, "picked": False, "round": 0,
                       "writer": how, "state": "writing", "outputs": {}})
    if how == "handoff":
        job.data["issue"] = handoff.ask(handoff.repo(ctx.http, ctx.secrets, ctx.settings.handoff_repo), job.id,
                                        look, notes, seconds)
        job.log(f"handoff issue #{job.data['issue']} opened")
        return job
    draft = writer.write(ctx.http, ctx.keys, ctx.settings, look, notes, seconds, folder, how == "claude-api")
    _keep(ctx, job, draft)
    return job


def _new_folder(parent: Path, stamp: str) -> Path:
    """A short id you can type (/studio pick <id>); -2, -3 … when two jobs start in one second."""
    parent.mkdir(parents=True, exist_ok=True)
    for n in range(1, 100):
        folder = parent / (stamp if n == 1 else f"{stamp}-{n}")
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            continue
    raise QueueError("too many jobs in one second")


def _keep(ctx: Any, job: Job, draft: writer.Draft) -> None:
    writer.save(draft, job.folder / "storyboard.json", job.data["profile"])
    if draft.wishes:
        writer.remember(draft, ctx.home, job.folder.joinpath("notes.txt").read_text(encoding="utf-8"))
    job.data.update(title=draft.title, words=draft.words(), writer=draft.model)
    job.log(f"written by {draft.model}: {draft.title}", "ready")


# ---------------------------------------------------------------- steps


def _collect(ctx: Any, job: Job) -> bool:
    """A handoff answer → ready (or a fix request); False while Claude has not answered."""
    hand = handoff.repo(ctx.http, ctx.secrets, ctx.settings.handoff_repo)
    raw = handoff.collect(hand, job.id, job.data["round"], job.folder)
    if raw is None:
        return False
    look = profile.load(job.data["profile"], ctx.home)
    notes = job.folder.joinpath("notes.txt").read_text(encoding="utf-8")
    seconds = job.data["seconds"] or float(look.section("writing")["seconds"])
    accepted = writer.accept(raw, look, notes, writer.target_words(look, seconds), job.folder, "claude (handoff)",
                             job.data["round"] + 1)
    if isinstance(accepted, writer.Draft):
        _keep(ctx, job, accepted)
        return True
    if job.data["round"] >= handoff.FIXES:
        raise writer.WriterError("Claude's storyboard still failed the checks: " + "; ".join(accepted[:3]))
    job.data["round"] += 1
    job.data["issue"] = handoff.ask(hand, job.id, look, notes, seconds, job.data["round"], accepted, raw)
    job.log(f"checks failed ({len(accepted)}): fix request #{job.data['issue']}")
    return True


def longest_pause(board: storyboard.Storyboard) -> float:
    pauses = [0.0]
    for scene in board.scenes:
        for sentence in voice.sentences(scene.say):
            d = direction.parse(sentence)
            pauses += [d.lead, *(p.pause for p in d.parts)]
    return max(pauses)


def _board(job: Job, hook: int) -> storyboard.Storyboard:
    name = "storyboard.json" if hook == 1 else f"storyboard.hook{hook}.json"
    return storyboard.load(job.folder / name)


def _pace(board: storyboard.Storyboard, made: video.Video) -> str:
    words = sum(len(writer.spoken(scene.say).split()) for scene in board.scenes)
    return (f"{made.seconds:.1f} s, {words} words = {words / max(made.seconds, 1) * 60:.0f} wpm · voice "
            f"{made.voice_took:.0f} s · render {made.render_took:.0f} s · {made.job.name}")


def _clips(ctx: Any, job: Job, tools: Tools) -> dict[str, str]:
    """Hooks 2 and 3 as clips of the opening alone, to pick from (not once a hook was picked)."""
    if not ctx.settings.hook_clips or job.data["picked"]:
        return {}
    out = {}
    for n in (2, 3):
        clip = _board(job, n)
        clip = replace(clip, scenes=clip.scenes[:1])
        done = tools.video(ctx.http, ctx.keys, ctx.settings, ctx.home, clip, job.folder / f"hook{n}.mp4",
                           job.data["profile"])
        job.log(f"hook {n} clip: {_pace(clip, done)}")
        out[str(n)] = str(done.path)
    return out


def _render(ctx: Any, job: Job, tools: Tools) -> None:
    board = _board(job, job.data["hook"])
    made = tools.video(ctx.http, ctx.keys, ctx.settings, ctx.home, board, job.folder / "video.mp4", job.data["profile"])
    job.log(f"video (hook {job.data['hook']}): {_pace(board, made)}")
    for note in made.notes:
        job.log(f"  {note}")
    out = {"video": str(made.path), "seconds": made.seconds, "notes": list(made.notes),
           "hooks": _clips(ctx, job, tools)}
    pick = json.loads((job.folder / "storyboard.cover.json").read_text(encoding="utf-8"))
    started = time.monotonic()
    out["cover"] = str(tools.cover(ctx.http, ctx.keys, ctx.settings, ctx.home, board, job.folder / "cover.png",
                                   pick["scene"], pick["words"], job.data["profile"]))
    job.log(f"cover: scene {pick['scene']}, \"{pick['words']}\" · {time.monotonic() - started:.0f} s")
    report = tools.qc(made.path, made.seconds, longest_pause(board))
    out.update(qc=report.summary(), passed=report.passed)
    job.data["outputs"] = out
    job.log(report.summary().replace("\n", " · "), "rendered")


def _small(path: Path) -> Path:
    """A copy Telegram accepts (bots upload at most 50 MB)."""
    if path.stat().st_size <= PROXY_MB * 1_000_000:
        return path
    small = path.with_name(path.stem + "-preview.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-vf", "scale=720:-2", "-c:v", "libx264",
                    "-crf", "28", "-preset", "veryfast", "-c:a", "aac", "-b:a", "128k", str(small)],
                   capture_output=True, timeout=900, check=True)
    return small


def _deliver(ctx: Any, job: Job) -> None:
    out = job.data["outputs"]
    tg = Telegram(ctx.http, ctx.secrets)
    title = job.data.get("title", job.id)
    tg.upload("sendVideo", "video", _small(Path(out["video"])),
              f"🎬 {title} · {out['seconds']:.1f} s · hook {job.data['hook']} · job {job.id}")
    tg.upload("sendPhoto", "photo", Path(out["cover"]), f"Cover · {title}")
    for n, clip in sorted(out.get("hooks", {}).items()):
        tg.upload("sendVideo", "video", Path(clip), f"Hook {n} · /studio pick {job.id} {n}")
    if out["passed"] and drive.ready(ctx.secrets):
        out["drive"] = {"video": drive.upload(ctx.http, ctx.secrets, Path(out["video"]), f"{title} ({job.id}).mp4"),
                        "cover": drive.upload(ctx.http, ctx.secrets, Path(out["cover"]), f"{title} ({job.id}) cover.png",
                                              "image/png")}
    lines = [out["qc"], *out.get("notes", [])]
    if out.get("drive"):
        lines.append(f"Drive: {out['drive']['video']}")
    elif out["passed"]:
        lines.append(f"Drive: not signed in ({drive.LOGIN})")
    script = job.folder.joinpath("storyboard.txt").read_text(encoding="utf-8")
    tg.text("\n".join([f"🎬 {title} (job {job.id})", *lines, "", script]))
    job.log("delivered", "done")


# ---------------------------------------------------------------- running


def in_window(window: str, now: datetime) -> bool:
    start, end = (clock.fromisoformat(t) for t in window.split("-"))
    at = now.time()
    return start <= at < end if start < end else at >= start or at < end


@contextmanager
def _lock(home: Path) -> Iterator[bool]:
    root(home).mkdir(parents=True, exist_ok=True)
    with root(home).joinpath(".lock").open("w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _advance(ctx: Any, job: Job, tools: Tools, render: bool) -> str:
    if job.state == "writing" and not _collect(ctx, job):
        return ""
    if job.state == "ready" and render:
        _render(ctx, job, tools)
    if job.state == "rendered":
        _deliver(ctx, job)
        return f"🎬 {job.data.get('title', job.id)}: delivered (job {job.id})"
    return f"✍️ {job.data.get('title', job.id)}: written, renders in {ctx.settings.render_window}" \
        if job.state == "ready" and not render else ""


def run(ctx: Any, now: datetime | None = None, force: bool = False, tools: Tools | None = None) -> str:
    """One pass over the queue. Returns what to tell you ("" when there was nothing new)."""
    tools = tools or Tools()
    said = []
    with _lock(ctx.home) as mine:
        if not mine:
            return "A studio run is already going." if force else ""
        for job in jobs(ctx.home):
            if job.state in ("done", "failed"):
                continue
            render = force or in_window(ctx.settings.render_window, now or datetime.now())
            try:
                said.append(_advance(ctx, job, tools, render))
            except STEP_ERRORS as exc:
                job.data["error"] = str(exc)[:500]
                job.log(f"failed: {(str(exc).splitlines() or [''])[0][:200]}", "failed")  # no HTML error pages
                said.append(f"⚠️ studio job {job.id} failed: {str(exc)[:300]}")
    return "\n".join(s for s in said if s)


def pick(ctx: Any, job_id: str, hook: int) -> Job:
    job = load(ctx.home, job_id)
    if not 1 <= hook <= 3 or job.state not in ("rendered", "done", "ready", "failed"):
        raise QueueError(f"Hook 1, 2 or 3 of a written job; {job_id} is {job.state}")
    # the same hook again on a failed job is a retry: the other hooks' clips are still wanted
    retry = job.state == "failed" and hook == job.data["hook"] and not job.data["picked"]
    job.data.update(hook=hook, picked=not retry, outputs={})
    job.data.pop("error", None)
    job.log(f"hook {hook} picked" if not retry else "retry", "ready")
    return job


def status(ctx: Any, last: int = 10) -> str:
    found = jobs(ctx.home)[-last:]
    if not found:
        return "No studio jobs yet. /studio make <notes>"
    marks = {"writing": "✍️", "ready": "⏳", "rendered": "🎞", "done": "✅", "failed": "⚠️"}
    return "\n".join(f"{marks.get(j.state, '·')} {j.id} {j.state}: {j.data.get('title', '')}"
                     + (f" ({j.data['error'][:80]})" if j.state == "failed" else "") for j in found)
