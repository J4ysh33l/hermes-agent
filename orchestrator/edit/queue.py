"""Edit jobs, one folder each in ``$HERMES_HOME/edit/jobs/<id>/`` (job.json + every file the job made).
The ``edit`` cron (every 5 minutes; ``install.sh`` prints the line) runs one pass at a time:

    new ──fetch, ingest, transcribe──▶ transcribed ──ask the editor──▶ planning ──answer checked──▶ planned
    planned ──(edit.approve) the plan comes to you──▶ approval ──/edit approve──▶ ready ──render──▶ done

A plan that fails its checks goes back to Claude (``edit.plan_retries``), then the job is edited on code
alone (cuts, captions, punch-ins) and the notes say so: a video is never lost to the editor. Any step that
fails sets ``failed`` with the reason, sent to you.

Where footage comes from: a file on the server, a direct https link, or a Google Drive link shared as
"anyone with the link" (Hermes' Drive sign-in only sees files it made itself, so it cannot open yours).
Telegram bots can download at most 20 MB, so send big files by Drive.
"""

from __future__ import annotations

import fcntl
import json
import re
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from orchestrator.brief.net import HttpError
from orchestrator.handoff import Handoff, HandoffError
from orchestrator.notes.telegram import Telegram
from orchestrator.studio import drive

from . import cuts, editor, media, plan as plans, render, style, transcript, words

DRIVE_ID = re.compile(r"(?:/d/|id=)([A-Za-z0-9_-]{20,})")
TELEGRAM_MB = 48
STATES = ("new", "transcribed", "planning", "planned", "approval", "ready", "done", "failed", "cancelled")


class QueueError(Exception):
    """Shown as it is."""


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
        (self.folder / "job.json").write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")


def root(home: Path) -> Path:
    return home / "edit" / "jobs"


def load(home: Path, job_id: str) -> Job:
    folder = root(home) / job_id
    if not re.fullmatch(r"[0-9A-Za-z-]+", job_id) or not (folder / "job.json").is_file():
        raise QueueError(f"No edit job {job_id!r} (/edit queue lists them)")
    return Job(folder, json.loads((folder / "job.json").read_text(encoding="utf-8")))


def jobs(home: Path) -> list[Job]:
    return [load(home, p.parent.name) for p in sorted(root(home).glob("*/job.json"))]


def add(home: Path, source: str, look_name: str, asked: str) -> Job:
    style.load(look_name, home)  # a wrong style name fails here, not overnight
    stamp = datetime.now().strftime("%m%d-%H%M%S")
    folder = root(home) / stamp
    folder.mkdir(parents=True, exist_ok=False)
    job = Job(folder, {"id": stamp, "state": "new", "source": source.strip(), "style": look_name, "asked": asked.strip(),
                       "created": datetime.now().isoformat(timespec="seconds")})
    (folder / "asked.txt").write_text(asked.strip(), encoding="utf-8")
    (folder / "style.txt").write_text(look_name, encoding="utf-8")
    job.log(f"added: {source.strip()} · style {look_name}")
    return job


# ---------------------------------------------------------------- the steps


def fetch(ctx: Any, job: Job) -> Path:
    """The upload into the job folder (raw.*)."""
    source = job.data["source"]
    local = Path(source).expanduser()
    if local.is_file():
        dst = job.folder / f"raw{local.suffix.lower() or '.mp4'}"
        shutil.copy(local, dst)
        return dst
    found = DRIVE_ID.search(source)
    if "drive.google.com" in source and found:
        url = f"https://drive.usercontent.google.com/download?id={found.group(1)}&export=download&confirm=t"
    elif source.startswith("https://"):
        url = source
    else:
        raise QueueError(f"Cannot read {source!r}: give a file on the server, an https link, or a Drive link shared "
                         "as 'anyone with the link'")
    dst = job.folder / "raw.mp4"
    try:
        body = ctx.http.request("GET", url).body
    except HttpError as exc:
        raise QueueError(f"Download failed ({exc}); for Drive, share the file as 'anyone with the link'") from None
    if body[:15].lower().startswith((b"<!doctype html", b"<html")):
        raise QueueError("The link gave a web page, not a video: share it on Drive as 'anyone with the link'")
    dst.write_bytes(body)
    return dst


def _ingest(ctx: Any, job: Job) -> None:
    look = style.load(job.data["style"], ctx.home)
    raw = fetch(ctx, job)
    info = media.probe(raw)
    if info.seconds > ctx.edit.max_minutes * 60:
        raise QueueError(f"{info.seconds / 60:.1f} min is over edit.max_minutes ({ctx.edit.max_minutes})")
    media.prepare(raw, job.folder, look, ctx.edit.fps, ctx.edit.mezzanine_crf, ctx.edit.threads)
    job.data["input"] = info.describe()
    transcript.transcribe(ctx.edit, ctx.settings, ctx.home, job.folder / "voice16.wav", job.folder / "transcript.json")
    ws = words.load(job.folder / "transcript.json")
    if words.has_devanagari(ws):
        job.data.setdefault("warnings", []).append("Some words came out in Devanagari; captions want Latin (edit.asr_language: en)")
    raw.unlink(missing_ok=True)  # source.mp4 and voice.wav hold everything from here on
    job.log(f"ingested: {info.describe()}; {len(ws)} words", "transcribed")


def _hand(ctx: Any) -> Handoff:
    from orchestrator.studio import handoff as studio_handoff
    return studio_handoff.repo(ctx.http, ctx.secrets, ctx.settings.handoff_repo)


def _parts(ctx: Any, job: Job) -> tuple[style.Style, list[words.Word], list[words.Sentence]]:
    look = style.load(job.data["style"], ctx.home)
    ws = words.load(job.folder / "transcript.json")
    return look, ws, words.sentences(ws)


def _plan(ctx: Any, job: Job) -> None:
    look, ws, found = _parts(ctx, job)
    text = editor.prompt(job.id, look, ws, found, job.data["asked"])
    via = ctx.settings.claude_via
    if via == "auto":
        via = "api" if ctx.keys.claude else "handoff"
    if via == "api" and ctx.keys.claude:
        try:
            chosen = editor.by_api(ctx.http, ctx.keys.claude, ctx.settings.claude_model, text)
        except (ValueError, plans.PlanError, HttpError) as exc:
            return _fallback(ctx, job, f"the editor's answer failed ({exc})")
        return _accept(ctx, job, chosen)
    hand = _hand(ctx)
    if not hand.ready:
        return _fallback(ctx, job, "Claude is not set up (handoff repo or API key)")
    words_json = (job.folder / "transcript.json").read_text(encoding="utf-8")
    number = editor.send(hand, job.id, look, words_json, job.data["asked"], text)
    job.data.update({"issue": number, "round": 0})
    job.log(f"editor asked (handoff issue #{number})", "planning")


def _collect(ctx: Any, job: Job) -> None:
    hand = _hand(ctx)
    if not hand.closed(int(job.data["issue"])):
        return
    look, ws, found = _parts(ctx, job)
    chosen, wrong = editor.answer(hand, job.id)
    problems = [wrong] if wrong else plans.check(chosen, found, cuts.build(ws, found, look, chosen.drop, chosen.trim, chosen.keep),
                                                look, job.data["asked"])
    if not problems:
        return _accept(ctx, job, chosen)
    if job.data["round"] < ctx.edit.plan_retries:
        job.data["round"] += 1
        words_json = (job.folder / "transcript.json").read_text(encoding="utf-8")
        job.data["issue"] = editor.send(hand, job.id, look, words_json, job.data["asked"],
                                        editor.fix_request(job.id, problems), job.data["round"])
        job.log(f"plan sent back ({len(problems)} problems): issue #{job.data['issue']}")
        return None
    return _fallback(ctx, job, "the plan still failed its checks: " + "; ".join(problems[:3]))


def _fallback(ctx: Any, job: Job, why: str) -> None:
    look, _ws, found = _parts(ctx, job)
    chosen = plans.basic(found, look)
    chosen.notes = f"Edited without the editor: {why}. Cuts, captions and punch-ins only."
    _accept(ctx, job, chosen)


def _accept(ctx: Any, job: Job, chosen: plans.Plan) -> None:
    (job.folder / "plan.json").write_text(json.dumps(chosen.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    job.data["title"] = chosen.title.replace("*", "") or job.id
    job.log("plan ready", "planned")
    if ctx.edit.approve:
        Telegram(ctx.http, ctx.secrets).text(summary(ctx, job))
        job.log("plan sent to you for approval", "approval")
    else:
        job.log("no approval asked (edit.approve: false)", "ready")


def summary(ctx: Any, job: Job) -> str:
    look, ws, found = _parts(ctx, job)
    chosen = plans.load((job.folder / "plan.json").read_text(encoding="utf-8"))
    cut = cuts.build(ws, found, look, chosen.drop, chosen.trim, chosen.keep)
    by_id = {s.id: s for s in found}
    lines = [f"✂️ **{chosen.title.replace('*', '') or job.id}** · job {job.id} · style {look.name}",
             f"{ws[-1].end if ws else 0:.0f} s raw → {cut.seconds:.0f} s edited"]
    for sid, why in sorted(cut.dropped.items()):
        lines.append(f"  cut S{sid} ({why}): {by_id[sid].text[:80] if sid in by_id else ''}")
    if cut.fillers:
        lines.append(f"  fillers cut: {', '.join(cut.fillers[:8])}")
    for g in chosen.graphics:
        what = g.get("text") or g.get("emoji") or g.get("query") or g.get("file") or ", ".join(g.get("items") or [])
        lines.append(f"  {g.get('kind')} at {g.get('at')}: {what}")
    if chosen.notes:
        lines.append(f"📝 {chosen.notes}")
    lines.append(f"/edit approve {job.id} to render · /edit plan {job.id} for the full transcript · /edit cancel {job.id}")
    return "\n".join(lines)


def _small(path: Path) -> Path:
    if path.stat().st_size <= TELEGRAM_MB * 1_000_000:
        return path
    small = path.with_name(path.stem + "-preview.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-vf", "scale=720:-2", "-c:v", "libx264", "-crf", "28",
                    "-preset", "veryfast", "-c:a", "aac", "-b:a", "128k", str(small)], capture_output=True, timeout=1800, check=True)
    return small


def _render(ctx: Any, job: Job) -> None:
    look, ws, found = _parts(ctx, job)
    chosen = plans.load((job.folder / "plan.json").read_text(encoding="utf-8"))
    out = job.folder / "edited.mp4"
    started = datetime.now()
    result = render.render(job.folder, look, chosen, ws, found, ctx.edit, ctx.settings, ctx.home, out, ctx.http, ctx.keys)
    took = (datetime.now() - started).total_seconds()
    tg = Telegram(ctx.http, ctx.secrets)
    title = job.data.get("title", job.id)
    tg.upload("sendVideo", "video", _small(out), f"🎬 {title} · {result.seconds:.1f} s · job {job.id}")
    lines = [f"🎬 {title} (job {job.id}) · rendered in {took / 60:.1f} min", result.report, *result.notes,
             *job.data.get("warnings", [])]
    if drive.ready(ctx.secrets):
        lines.append(f"Drive: {drive.upload(ctx.http, ctx.secrets, out, f'{title} ({job.id}).mp4')}")
    tg.text("\n".join(lines))
    job.data["outputs"] = {"video": str(out), "seconds": result.seconds, "notes": result.notes}
    job.log(f"rendered and sent ({took:.0f} s)", "done")


# ---------------------------------------------------------------- running

STEP: dict[str, Callable[[Any, Job], None]] = {"new": _ingest, "transcribed": _plan, "planning": _collect,
                                                "ready": _render}
ERRORS = (QueueError, media.MediaError, transcript.TranscriptError, plans.PlanError, style.StyleError, HandoffError,
          HttpError, render.MediaError, OSError, subprocess.SubprocessError)


@contextmanager
def _lock(home: Path) -> Iterator[bool]:
    root(home).mkdir(parents=True, exist_ok=True)
    with (root(home) / ".lock").open("w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def run(ctx: Any) -> str:
    """One pass: every job moves as far as it can (slow steps one at a time). Returns what happened."""
    with _lock(ctx.home) as mine:
        if not mine:
            return "An edit pass is already running."
        said = []
        for job in jobs(ctx.home):
            while job.state in STEP:
                before = job.state
                try:
                    STEP[job.state](ctx, job)
                except ERRORS as exc:
                    job.log(f"failed in {before}: {exc}", "failed")
                    Telegram(ctx.http, ctx.secrets).text(f"⚠️ Edit job {job.id} failed while {before}: {exc}")
                    said.append(f"⚠️ {job.id}: {exc}")
                    break
                if job.state == before:  # waiting (Claude still editing)
                    break
                said.append(f"{job.id}: {before} → {job.state}")
        return "\n".join(said)


def approve(home: Path, job_id: str) -> Job:
    job = load(home, job_id)
    if job.state not in ("approval", "planned"):
        raise QueueError(f"Job {job.id} is {job.state}; only a planned job can be approved")
    job.log("approved by you", "ready")
    return job


def cancel(home: Path, job_id: str) -> Job:
    job = load(home, job_id)
    if job.state in ("done", "cancelled"):
        raise QueueError(f"Job {job.id} is already {job.state}")
    job.log("cancelled by you", "cancelled")
    return job


def status(home: Path, last: int = 10) -> str:
    found = jobs(home)[-last:]
    if not found:
        return "No edit jobs yet. /edit <Drive link or file> [style] [what you want]"
    icons = {"new": "📥", "transcribed": "📝", "planning": "✍️", "planned": "📋", "approval": "⏳", "ready": "🎬",
             "done": "✅", "failed": "⚠️", "cancelled": "✖️"}
    return "\n".join(f"{icons.get(j.state, '•')} {j.id} · {j.data.get('title', j.data['source'][:40])} · {j.data['style']} · {j.state}"
                     for j in found)
