"""A meeting → one transcript on disk, made once and reused by every document you ask for.

With a recording: each recording session is cut into ``chunk_minutes`` audio chunks; each chunk is
one Gemini call (Hindi in Latin script, speakers "Speaker 1, 2 …"), at least ``gap_seconds`` after
the last and only when the tokens of the last 60 s (every workflow, from the usage log) leave room
under ``tokens_per_minute``. The Teams transcript, when there is one, gives the speakers their names.
Without a recording, the Teams transcript itself is used. Neither: wait (Teams is still processing)
until ``GIVE_UP`` after the meeting, then say so.
"""

from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from orchestrator import llm, usage
from orchestrator.brief.net import Http, HttpError

from . import audio, vtt
from .errors import NotesError
from .settings import Settings
from .teams import Files, Teams

GIVE_UP = timedelta(hours=24)  # no recording or transcript by then: there will not be one
ROOM_WAIT = 5.0  # seconds between checks while waiting for token room
MAX_WAIT = 600.0  # a call that cannot fit in 10 minutes is left for the next run
LINE = re.compile(r"^\[?(?:(\d+):)?(\d{1,2}):(\d\d)\]?\s*([^:\]]{1,60}):\s*(.+)$")
PROMPT = """Transcribe this meeting audio word for word.
- Hindi is written in Latin script (romanised, e.g. "kal ka plan kya hai"), never in Devanagari. English stays English.
- One line per speaker turn: [mm:ss] Speaker N: words. Times count from the start of this audio.
- Name speakers Speaker 1, Speaker 2 … and keep the same number for the same voice throughout.
- Do not summarise, translate, correct or add anything. Write [unclear] for words you cannot make out.
{context}"""
CONTEXT = "This audio continues a meeting. Its previous part ended with:\n{tail}\nKeep the same speaker numbers."


@dataclass(frozen=True)
class Turn:
    start: float  # seconds from the first recording session
    speaker: str
    text: str


@dataclass(frozen=True)
class Result:
    status: str  # "done", "wait" (try again at ``retry``), "gone" (nothing to transcribe, ever)
    note: str = ""
    retry: timedelta = timedelta(hours=1)
    path: Path | None = None
    source: str = ""  # "gemini" or "teams"
    audio_minutes: float = 0.0  # sent to Gemini, counted against the daily budget


class Clock:
    """Time and sleeping, replaceable in tests."""

    def __init__(self, now: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep) -> None:
        self.now = now
        self.sleep = sleep


def wait_for_room(tokens: int, settings: Settings, clock: Clock) -> None:
    """Block until the last 60 s of Gemini use plus ``tokens`` fits the per-minute limit and the last
    audio call is ``gap_seconds`` old. Raises NotesError after MAX_WAIT (the next run tries again)."""
    waited = 0.0
    while True:
        now = datetime.fromtimestamp(clock.now()).astimezone()
        recent = [c for c in usage.read_calls(now - timedelta(seconds=max(60, settings.gap_seconds)))
                  if c.provider == "gemini"]
        last_minute = sum(c.input for c in recent if datetime.fromisoformat(c.ts) >= now - timedelta(seconds=60))
        last_audio = max((datetime.fromisoformat(c.ts) for c in recent if c.step == "transcribe"), default=None)
        spaced = last_audio is None or (now - last_audio).total_seconds() >= settings.gap_seconds
        if spaced and last_minute + tokens <= settings.tokens_per_minute:
            return
        if waited >= MAX_WAIT:
            raise NotesError("Gemini's per-minute token limit stayed full; trying again next run")
        clock.sleep(ROOM_WAIT)
        waited += ROOM_WAIT


def parse_turns(text: str, offset: float) -> list[Turn]:
    turns = []
    for raw in text.splitlines():
        m = LINE.match(raw.strip())
        if m:
            h, mm, ss, who, words = m.groups()
            turns.append(Turn(offset + int(h or 0) * 3600 + int(mm) * 60 + int(ss), who.strip(), words.strip()))
        elif turns and raw.strip():
            last = turns[-1]
            turns[-1] = Turn(last.start, last.speaker, f"{last.text} {raw.strip()}")
    return turns


def name_speakers(turns: list[Turn], cues: list[vtt.Cue]) -> list[Turn]:
    """Gemini's "Speaker N" → the name Teams heard at the same moments, when most of them agree."""
    named = [c for c in cues if c.speaker]
    if not named:
        return turns
    votes: dict[str, Counter] = defaultdict(Counter)
    for turn in turns:
        cue = min(named, key=lambda c: abs(c.start - turn.start))
        if abs(cue.start - turn.start) <= 8:
            votes[turn.speaker][cue.speaker] += 1
    names = {}
    for label, counter in votes.items():
        name, count = counter.most_common(1)[0]
        if count >= 2 and count / sum(counter.values()) >= 0.6:
            names[label] = name
    return [Turn(t.start, names.get(t.speaker, t.speaker), t.text) for t in turns]


def _gemini_chunk(http: Http, key: str, settings: Settings, chunk: audio.Chunk, tail: str) -> str:
    context = CONTEXT.format(tail=tail) if tail else ""
    errors = []
    for model in settings.models:
        uploaded = llm.upload(http, key, chunk.path, audio.MIME)
        try:
            llm.wait_active(http, key, uploaded["name"])
            return llm.gemini(http, key, model, PROMPT.format(context=context).strip(), workflow="notes",
                              step="transcribe", max_output_tokens=32_000, temperature=0.0,
                              files=((audio.MIME, uploaded["uri"]),))
        except (HttpError, ValueError) as exc:
            errors.append(f"{model}: {str(exc)[:120]}")
        finally:
            try:
                llm.delete(http, key, uploaded["name"])
            except HttpError:
                pass  # Gemini deletes uploads by itself after 48 hours
    raise NotesError("Gemini could not transcribe: " + "; ".join(errors))


def _write(path: Path, meeting: dict, turns: list[Turn], source: str, restarts: list[float]) -> Path:
    head = [f"# {meeting['subject']}", f"{meeting['start'][:16].replace('T', ' ')} IST · transcript from {source}", ""]
    body = []
    marks = sorted(restarts)
    for t in sorted(turns, key=lambda t: t.start):
        while marks and marks[0] <= t.start:
            body.append(f"--- recording restarted at {vtt.clock(marks.pop(0))} ---")
        body.append(f"[{vtt.clock(t.start)}] {t.speaker}: {t.text}")
    path.write_text("\n".join(head + body) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def run(meeting: dict, folder: Path, teams: Teams, http: Http, key: str, settings: Settings, clock: Clock,
        audio_left: float) -> Result:
    """Make ``folder/transcript.md``. ``audio_left``: minutes of today's audio budget still free."""
    files: Files = teams.files(meeting)
    cues = vtt.join([(s.start, teams.transcript(files.meeting_id, s)) for s in files.transcripts])
    if not files.recordings:
        if cues:
            turns = [Turn(c.start, c.speaker or "Unknown", c.text) for c in cues]
            return Result("done", path=_write(folder / "transcript.md", meeting, turns, "Teams", []), source="teams")
        ended = datetime.fromisoformat(meeting["end"])
        if datetime.fromtimestamp(clock.now(), ended.tzinfo) - ended > GIVE_UP:
            return Result("gone", "Teams has no recording or transcript of this meeting")
        return Result("wait", "waiting for Teams to finish the recording")
    planned = sum(((r.end or r.start) - r.start).total_seconds() for r in files.recordings) / 60
    if planned > audio_left:  # known from Teams' times: no download until the budget allows it
        tomorrow = datetime.combine(datetime.fromtimestamp(clock.now()).date() + timedelta(days=1), datetime.min.time())
        return Result("wait", f"needs {planned:.0f} min of audio; today's budget has {max(audio_left, 0):.0f} left",
                      retry=tomorrow - datetime.fromtimestamp(clock.now()))
    first = files.recordings[0].start
    if files.transcripts:  # Teams' clock starts at its first transcript session; move it onto the recording's
        shift = (files.transcripts[0].start - first).total_seconds()
        cues = [vtt.Cue(c.start + shift, c.end + shift, c.speaker, c.text) for c in cues]
    pieces: list[tuple[audio.Chunk, float]] = []
    for n, rec in enumerate(files.recordings):
        path = teams.recording(files.meeting_id, rec, folder / f"recording-{n + 1}.mp4")
        offset = (rec.start - first).total_seconds()
        pieces += [(c, offset) for c in audio.chunks(path, folder / "audio", settings.chunk_minutes)]
        path.unlink()  # the video is not kept
    minutes = sum(c.seconds for c, _ in pieces) / 60
    turns: list[Turn] = []
    for chunk, offset in pieces:
        wait_for_room(chunk.tokens + 1_000, settings, clock)
        tail = "\n".join(f"{t.speaker}: {t.text}" for t in turns[-8:])
        turns += parse_turns(_gemini_chunk(http, key, settings, chunk, tail), offset + chunk.offset)
        chunk.path.unlink()
    restarts = [(r.start - first).total_seconds() for r in files.recordings[1:]]
    path = _write(folder / "transcript.md", meeting, name_speakers(turns, cues), "Gemini (audio)", restarts)
    return Result("done", path=path, source="gemini", audio_minutes=minutes)
