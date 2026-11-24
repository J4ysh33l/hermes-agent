"""The soundtrack: the voice brought to the loudness shorts are played at (and, with music and sound
effects, the mix under it).

Platforms play shorts at about -14 LUFS; Kokoro's voice comes out near -18, so a video sounded weaker
than the ones around it. ``normalize`` measures with ffmpeg's loudnorm, applies the gain to -14 LUFS with a
limiter holding true peaks near -1.5 dBTP (AAC encoding adds a little), and corrects once more.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

TARGET = -14.0
PEAK = -1.5
RANGE = 11.0
TIMEOUT = 600


class AudioError(Exception):
    """Shown as it is; nothing was rendered."""


def _ffmpeg(args: list[str]) -> str:
    try:
        done = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *args], capture_output=True, text=True,
                              timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioError(f"ffmpeg failed: {exc}") from None
    if done.returncode != 0:
        raise AudioError(f"ffmpeg failed: {done.stderr.strip()[-300:]}")
    return done.stderr


def measure(path: Path) -> dict[str, str]:
    """loudnorm's first pass: the file's integrated loudness, range, true peak and threshold."""
    log = _ffmpeg(["-i", str(path), "-af", f"loudnorm=I={TARGET}:TP={PEAK}:LRA={RANGE}:print_format=json",
                   "-f", "null", "-"])
    found = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log, re.DOTALL)
    if not found:
        raise AudioError("ffmpeg did not report the loudness")
    return json.loads(found.group(0))


def normalize(src: Path, dst: Path) -> Path:
    """``src`` at -14 LUFS → ``dst`` (WAV): the gain the measurement asks for, a limiter holding peaks under
    -1.5 dBTP, then one more measurement and correction (limiting takes a little loudness back). loudnorm
    alone stopped at -15.3 on Kokoro's voice: its peaks hit the ceiling before the target."""
    level = float(measure(src)["input_i"])
    if level < -70:  # silence: nothing to bring up
        dst.write_bytes(src.read_bytes())
        return dst
    gain = TARGET - level
    ceiling = 10 ** ((PEAK - 0.5) / 20)  # sample-peak limiter; true peaks land a little above it
    for _ in range(2):
        _ffmpeg(["-y", "-i", str(src), "-af", f"volume={gain:.2f}dB,alimiter=limit={ceiling:.4f}:level=false:"
                 "attack=2:release=60", str(dst)])
        reached = float(measure(dst)["input_i"])
        if abs(reached - TARGET) <= 0.5:
            break
        gain += TARGET - reached
    return dst
