"""Recording → audio chunks for Gemini, with ffmpeg. The video is thrown away: only speech is sent.

Mono 16 kHz Opus at 24 kbit/s keeps an hour near 11 MB. Gemini counts audio by time (32 tokens a
second), not by file size, so a smaller file costs the same tokens and uploads faster.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from hermes_platform.resolver import locate_command

from .errors import NotesError

TIMEOUT = 1800
MIME = "audio/ogg"
TOKENS_PER_SECOND = 32
MIN_SECONDS = 1.0


@dataclass(frozen=True)
class Chunk:
    path: Path
    offset: float  # seconds from the start of its recording
    seconds: float

    @property
    def tokens(self) -> int:
        return int(self.seconds * TOKENS_PER_SECOND)


def _tool(name: str) -> tuple[str, ...]:
    found = locate_command(name)
    if not found.found:
        raise NotesError(f"{name} is not installed on this machine; install ffmpeg for meeting audio.")
    return found.command


def duration(path: Path) -> float:
    done = subprocess.run([*_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of",
                           "default=nw=1:nk=1", str(path)], capture_output=True, text=True, timeout=120, check=False)
    try:
        return float(done.stdout.strip())
    except ValueError:
        raise NotesError(f"could not read the length of {path.name}: {done.stderr[-200:]}") from None


def chunks(recording: Path, out_dir: Path, chunk_minutes: float) -> list[Chunk]:
    """Audio only, cut every ``chunk_minutes``; the last piece is whatever is left."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{recording.stem}-*.ogg"):
        old.unlink()
    pattern = out_dir / f"{recording.stem}-%03d.ogg"
    cmd = [*_tool("ffmpeg"), "-y", "-v", "error", "-i", str(recording), "-vn", "-ac", "1", "-ar", "16000",
           "-c:a", "libopus", "-b:a", "24k", "-f", "segment", "-segment_time", str(int(chunk_minutes * 60)),
           "-reset_timestamps", "1", str(pattern)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, check=False)
    parts = sorted(out_dir.glob(f"{recording.stem}-*.ogg"))
    if done.returncode or not parts:
        raise NotesError(f"ffmpeg could not read the recording: {done.stderr[-300:]}")
    out, offset = [], 0.0
    for part in parts:
        seconds = duration(part)
        if seconds < MIN_SECONDS:  # the sliver ffmpeg leaves at the end: no speech, not worth a call
            part.unlink()
            continue
        out.append(Chunk(part, offset, seconds))
        offset += seconds
    return out
