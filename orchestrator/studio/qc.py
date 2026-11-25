"""Quality check before a video is delivered: what a viewer or a platform would notice, measured with
ffprobe/ffmpeg on the finished file. Blocking problems stop delivery; warnings travel with the preview.

- Format (blocking): H.264 1080×1920 at 30 fps, yuv420p, an AAC audio track, the expected length.
- Clipping (blocking): true peak above -0.5 dBTP distorts on phones.
- Loudness (warning): platforms play shorts at about -14 LUFS; far below sounds weak next to other videos.
- Dead air (warning): silence longer than the longest scripted pause (+0.5 s), outside the tail.
- Black or frozen picture (warning): over 1 s of near-black, or 2 s without a changing pixel (every scene
  drifts, so a freeze means something stopped drawing).
- Size (warning): over 50 MB cannot go to Telegram as is (the preview is re-encoded smaller).
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

TIMEOUT = 600
TELEGRAM_MB = 50
SILENCE = 1.2  # seconds of dead air that read as a mistake (rule 2 of PLAYBOOK: zero dead air)
TAIL = 0.8  # the end of the video may be quiet
LUFS = (-17.0, -11.0)
PEAK = -0.5


class QcError(Exception):
    """ffprobe/ffmpeg could not read the file."""


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    blocking: bool


@dataclass(frozen=True)
class Report:
    checks: tuple[Check, ...]
    seconds: float
    lufs: float
    peak: float
    megabytes: float

    @property
    def passed(self) -> bool:
        return all(c.ok or not c.blocking for c in self.checks)

    @property
    def problems(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def summary(self) -> str:
        head = (f"QC {'passed' if self.passed else 'FAILED'}: {self.seconds:.1f} s, {self.lufs:.1f} LUFS, "
                f"peak {self.peak:.1f} dBTP, {self.megabytes:.1f} MB")
        return "\n".join([head, *(f"{'⛔' if c.blocking else '⚠️'} {c.name}: {c.detail}" for c in self.problems)])


def _run(args: list[str]) -> str:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QcError(f"{args[0]} failed: {exc}") from None
    if done.returncode != 0 and args[0] == "ffprobe":
        raise QcError(f"ffprobe could not read the video: {done.stderr.strip()[-200:]}")
    return done.stdout + done.stderr


def probe(video: Path) -> dict:
    return json.loads(_run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                            str(video)]))


def _filters(video: Path) -> str:
    """One decoding pass: loudness, silences, black and frozen picture."""
    return _run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(video),
                 "-filter_complex", f"[0:a]ebur128=peak=true,silencedetect=n=-45dB:d={SILENCE / 2}[a];"
                 "[0:v]blackdetect=d=1.0:pix_th=0.02:pic_th=0.995,freezedetect=n=0.0005:d=2[v]",
                 "-map", "[a]", "-map", "[v]", "-f", "null", "-"])


def _number(pattern: str, text: str, default: float) -> float:
    found = re.findall(pattern, text)
    return float(found[-1]) if found else default


def _silences(log: str) -> list[tuple[float, float]]:
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    return list(zip(starts, ends + [float("inf")] * (len(starts) - len(ends))))


def _format_checks(info: dict, expected: float) -> list[Check]:
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    seconds = float(info.get("format", {}).get("duration", 0))
    shape = (video.get("codec_name"), video.get("width"), video.get("height"), video.get("r_frame_rate"),
             video.get("pix_fmt"))
    checks = [Check("format", shape == ("h264", 1080, 1920, "30/1", "yuv420p"),
                    "{} {}×{} at {} fps, {}".format(*shape), True),
              Check("audio", bool(audio and audio.get("codec_name") == "aac"),
                    f"{audio.get('codec_name') if audio else 'no'} audio track", True)]
    if expected:
        checks.append(Check("length", abs(seconds - expected) <= 1.0,
                            f"{seconds:.1f} s for {expected:.1f} s of voice and tail", True))
    return checks


def run(video: Path, expected: float = 0, longest_pause: float = 0) -> Report:
    """``expected``: the length the job should have (0 = do not check); ``longest_pause``: the longest
    pause the script asked for, so a scripted [pause 2] is not called dead air."""
    info = probe(video)
    seconds = float(info.get("format", {}).get("duration", 0))
    megabytes = video.stat().st_size / 1_000_000
    log = _filters(video)
    lufs = _number(r"I:\s+(-?[\d.]+) LUFS", log, -70.0)
    peak = _number(r"Peak:\s+(-?[\d.]+) dBFS", log, -70.0)
    allowed = max(SILENCE, longest_pause + 0.5)
    dead = [(a, min(b, seconds)) for a, b in _silences(log) if min(b, seconds) - a > allowed and a < seconds - TAIL]
    black = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)
    frozen = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", log)]
    checks = _format_checks(info, expected) + [
        Check("clipping", peak <= PEAK, f"true peak {peak:.1f} dBTP (at most {PEAK})", True),
        Check("loudness", LUFS[0] <= lufs <= LUFS[1], f"{lufs:.1f} LUFS (shorts play at about -14)", False),
        Check("dead air", not dead, ", ".join(f"{b - a:.1f} s of silence at {a:.1f} s" for a, b in dead) or "none",
              False),
        Check("black picture", not black, ", ".join(f"{a}–{b} s" for a, b in black) or "none", False),
        Check("frozen picture", not frozen, ", ".join(f"from {a:.1f} s" for a in frozen) or "none", False),
        Check("size", megabytes <= TELEGRAM_MB, f"{megabytes:.1f} MB (Telegram takes {TELEGRAM_MB} MB)", False),
    ]
    return Report(tuple(checks), seconds, lufs, peak, megabytes)
