"""Smriti's two jobs, both run by the ``notes`` cron every 15 minutes (no network when idle):

- ``check``: at each of ``check_hours`` (and from the 20:00 recap), one calendar call finds the Teams
  meetings you organised that have ended; each new one is remembered and you are asked what to make.
- ``process``: makes what you asked for, oldest first: the transcript once (``transcribe``), then each
  document (``docs`` with Gemini, or ``handoff`` to Claude), delivered on Telegram. A request is never
  dropped: it waits for a recording, for the audio budget or for Claude, and a failure is retried
  until ``max_attempts``, then reported (and listed in the recap). Then every other ended meeting gets
  its transcript stored too, unasked (``skip`` opts a meeting out), so any document later starts from it.

One run at a time: a run that finds another still working leaves at once.
"""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from functools import cached_property
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http, UrllibHttp

from . import docs, settings, transcribe
from .errors import NotesError
from .handoff import Handoff
from .store import Store, label
from .teams import Teams
from .telegram import Telegram
from .transcribe import Clock

IST = ZoneInfo("Asia/Kolkata")
LONG_CALLS = 600  # seconds: uploads, downloads and audio calls


@dataclass
class Context:
    home: Path
    http: Http
    clock: Clock

    @cached_property
    def secrets(self) -> Secrets:
        return Secrets(self.home / ".env", self.home / "brief" / "tokens")

    @cached_property
    def settings(self) -> settings.Settings:
        return settings.load(self.home / "brief")

    @cached_property
    def store(self) -> Store:
        return Store(self.home)

    @cached_property
    def teams(self) -> Teams:
        return Teams(self.http, self.secrets)

    @cached_property
    def telegram(self) -> Telegram:
        return Telegram(self.http, self.secrets)

    @property
    def now(self) -> datetime:
        return datetime.fromtimestamp(self.clock.now(), IST)

    @property
    def key(self) -> str:
        return self.secrets.get("GEMINI_API_KEY", "GOOGLE_API_KEY")


def context(home: Path) -> Context:
    return Context(home, UrllibHttp(timeout=LONG_CALLS), Clock())


@contextmanager
def one_at_a_time(home: Path):
    """Yields False when another run holds the lock (it is still transcribing)."""
    path = home / "notes" / ".lock"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# ---- asking ---------------------------------------------------------------------------------------


def ref(subject: str) -> str:
    """Words to type for a meeting: its first three words, lower case."""
    return " ".join(subject.lower().split()[:3]) or "last"


def _found(files) -> str:
    recording = "recording ✓" if files.recordings else "recording not ready yet"
    count = len(files.transcripts)
    transcript = "no Teams transcript" if not count else "transcript ✓" if count == 1 else f"transcript ✓ ({count} sessions)"
    return f"{recording} · {transcript}"


def ask(ctx: Context, key: str) -> str:
    m = ctx.store.meetings[key]
    try:
        found = _found(ctx.teams.files(m))
    except NotesError as exc:
        found = f"files not checked ({exc})"
    start, end = datetime.fromisoformat(m["start"]), datetime.fromisoformat(m["end"])
    words = ref(m["subject"])
    return (f"🎙 {m['subject']} ended ({start:%H:%M}–{end:%H:%M}) · {found}\n"
            f"What do you need? /notes {words} summary tasks prd · doc <anything> · transcript\n"
            f"Add claude to use Claude (default Gemini). Nothing needed: /notes {words} skip")


def check(ctx: Context, *, force: bool = False) -> list[str]:
    """New ended meetings → one question each. Runs at most once per check hour unless ``force``."""
    now, data = ctx.now, ctx.store.data
    slot = now.strftime("%Y-%m-%dT%H")
    if not force and (now.hour not in ctx.settings.check_hours or data.get("checked_slot") == slot):
        return []
    since = datetime.fromisoformat(data["checked_at"]) if data.get("checked_at") else \
        datetime.combine(now.date(), time.min, tzinfo=IST)
    meetings = ctx.teams.ended(since - timedelta(hours=1), now)  # an hour of overlap: a meeting ending at a check
    data["checked_slot"], data["checked_at"] = slot, now.isoformat()
    new = [m.key for m in meetings if ctx.store.add(m)]
    ctx.store.prune(now)
    return [ask(ctx, key) for key in new]


# ---- making ---------------------------------------------------------------------------------------


def _transcript(ctx: Context, key: str) -> str | None:
    """The saved transcript text, making it first if needed; None while it must wait (noted on the requests)."""
    m = ctx.store.meetings[key]
    if m["transcript"] and Path(m["transcript"]).is_file():
        return Path(m["transcript"]).read_text(encoding="utf-8")
    if m.get("retry_at", "") > ctx.now.isoformat():
        for req in m["requests"]:  # a request made while the meeting waits says why it waits
            req["note"] = req["note"] or m.get("wait", "")
        return None
    day = ctx.now.date().isoformat()
    left = ctx.settings.daily_audio_minutes - ctx.store.audio_used(day)
    result = transcribe.run(m, ctx.store.folder(key), ctx.teams, ctx.http, ctx.key, ctx.settings, ctx.clock, left)
    if result.status == "gone":
        for req in m["requests"]:
            if req["status"] in ("queued", "claude"):
                req["status"], req["note"] = "failed", result.note
        raise NotesError(result.note)
    if result.status == "wait":
        m["retry_at"], m["wait"] = (ctx.now + result.retry).isoformat(), result.note
        for req in m["requests"]:
            req["note"] = result.note
        return None
    m["transcript"], m["source"] = str(result.path), result.source
    ctx.store.add_audio(day, result.audio_minutes)
    return result.path.read_text(encoding="utf-8")


def _deliver(ctx: Context, key: str, req: dict, text: str) -> None:
    m = ctx.store.meetings[key]
    kind = docs.KINDS[req["kind"]]
    title = req["what"] if req["kind"] == "doc" else kind.title
    if kind.as_file:
        name = f"{title[:40]} - {m['subject'][:40]}".replace("/", "-")
        path = docs.to_docx(text, ctx.store.folder(key) / f"{name}.docx")
        ctx.telegram.file(path, f"📄 {title}: {label(m)}")
    else:
        ctx.telegram.text(f"📝 {title}: {label(m)}\n\n{text}")


def _one(ctx: Context, key: str, req: dict) -> None:
    m = ctx.store.meetings[key]
    if req["status"] == "claude":
        result = Handoff(ctx.http, ctx.secrets, ctx.settings.handoff_repo).result(req)
        if result is not None:
            _deliver(ctx, key, req, result)
            req["status"], req["note"] = "done", ""
        return
    text = _transcript(ctx, key)
    if text is None:
        return
    if req["kind"] == "transcript":
        ctx.telegram.file(Path(m["transcript"]), f"🗒 Transcript ({m['source']}): {label(m)}")
    elif req["model"] == "claude":
        make = req["what"] if req["kind"] == "doc" else docs.KINDS[req["kind"]].title
        req["issue"] = Handoff(ctx.http, ctx.secrets, ctx.settings.handoff_repo).send(req, m, text, make)
        req["status"], req["note"] = "claude", f"with Claude (issue #{req['issue']})"
        return
    else:
        _deliver(ctx, key, req, docs.write(ctx.http, ctx.key, ctx.settings, ctx.clock, req["kind"], req["what"], text))
    req["status"], req["note"] = "done", ""


def process(ctx: Context) -> list[str]:
    """Work through every open request; lines only for what failed for good."""
    lines = []
    for key, req in ctx.store.open_requests():
        if req["status"] not in ("queued", "claude"):  # failed with another request of its meeting
            continue
        try:
            _one(ctx, key, req)
        except NotesError as exc:
            if req["status"] == "failed":  # nothing to transcribe, ever
                lines.append(f"⚠️ {label(ctx.store.meetings[key])}: {exc}")
                continue
            req["attempts"] += 1
            req["note"] = str(exc)
            if req["attempts"] >= ctx.settings.max_attempts:
                req["status"] = "failed"
                lines.append(f"⚠️ {req['kind']} for {label(ctx.store.meetings[key])} failed {req['attempts']} times: "
                             f"{exc}. Ask again to retry: /notes {ref(ctx.store.meetings[key]['subject'])} {req['kind']}")
        finally:
            ctx.store.save()
    return lines


def store_transcripts(ctx: Context) -> None:
    """Every ended meeting not skipped gets its transcript, after the requests (within the audio budget,
    hourly retries while Teams is processing). A meeting with nothing recorded is given up quietly."""
    for key, m in ctx.store.recent(ctx.now):
        if m["skipped"] or m["transcript"] or m.get("gone") or m.get("tries", 0) >= ctx.settings.max_attempts:
            continue
        try:
            _transcript(ctx, key)
        except NotesError as exc:
            if "no recording or transcript" in str(exc):
                m["gone"] = True
            else:
                m["tries"] = m.get("tries", 0) + 1
            m["note"] = str(exc)
        finally:
            ctx.store.save()


def run(ctx: Context, *, force_check: bool = False) -> str:
    with one_at_a_time(ctx.home) as mine:
        if not mine:
            return ""
        lines = check(ctx, force=force_check)
        ctx.store.save()
        lines += process(ctx)
        store_transcripts(ctx)
        ctx.store.save()
        return "\n\n".join(lines)
