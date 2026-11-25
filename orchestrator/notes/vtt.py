"""Teams transcripts (WebVTT) → timed lines with speaker names, sessions joined in time order.

A Teams cue looks like ``00:01:02.500 --> 00:01:05.000`` then ``<v Asha Verma>Let's start.</v>``.
Each session (transcription stopped and started again) is its own file; ``join`` puts them on one
clock, measured from the first session's start, with a marker at each restart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

CUE = re.compile(r"(\d+):(\d\d):(\d\d)[.,](\d+)\s*-->\s*(\d+):(\d\d):(\d\d)[.,](\d+)")
VOICE = re.compile(r"<v\s+([^>]+)>(.*?)(?:</v>|$)", re.DOTALL)
TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Cue:
    start: float  # seconds from the meeting's first session
    end: float
    speaker: str
    text: str


def _seconds(h: str, m: str, s: str, frac: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + float("0." + frac)


def parse(text: str, offset: float = 0.0) -> list[Cue]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [l for l in block.strip().split("\n") if l.strip()]
        timing = next((i for i, l in enumerate(lines) if CUE.search(l)), None)
        if timing is None:
            continue
        g = CUE.search(lines[timing]).groups()
        body = " ".join(lines[timing + 1:])
        voice = VOICE.search(body)
        speaker, words = (voice.group(1).strip(), voice.group(2)) if voice else ("", body)
        words = TAG.sub("", words).strip()
        if words:
            cues.append(Cue(_seconds(*g[:4]) + offset, _seconds(*g[4:]) + offset, speaker, words))
    return cues


def join(sessions: list[tuple[datetime, str]]) -> list[Cue]:
    """(session start, its VTT text) in any order → one list of cues on the first session's clock."""
    ordered = sorted(sessions, key=lambda s: s[0])
    if not ordered:
        return []
    first = ordered[0][0]
    cues: list[Cue] = []
    for began, text in ordered:
        cues += parse(text, (began - first).total_seconds())
    return cues


def clock(seconds: float) -> str:
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60:02d}:{rest % 60:02d}"


def render(cues: list[Cue], restarts: list[float] = ()) -> str:
    """Plain text, one line per cue: ``[12:05] Asha Verma: …``; a marker where a session restarted."""
    marks = sorted(restarts)
    out = []
    for cue in cues:
        while marks and marks[0] <= cue.start:
            out.append(f"--- transcription restarted at {clock(marks.pop(0))} ---")
        out.append(f"[{clock(cue.start)}] {cue.speaker or 'Unknown'}: {cue.text}")
    return "\n".join(out)
