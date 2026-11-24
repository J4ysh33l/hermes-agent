"""A page profile from a reference video: the pace and colours of a short you like, measured with ffmpeg.

``python -m orchestrator.studio profile from liked.mp4 --name mypage`` writes
``$HERMES_HOME/studio/profiles/mypage.yaml`` (``extends: default``), with what was measured as comments:

- **Cut rate** (scene changes per second, ffmpeg's scene score): fast cutters get hard cuts or whips, short
  transitions, strong punch-ins; slow ones get fades, a soft feel and more drift.
- **Palette** (frames shrunk and counted in coarse colour bins): the most common dark colour becomes the
  background, the most common vivid one the accent, a second vivid hue far from it the "cool" colour; text
  is light or dark against the background, and an accent too close to the background is not used.
- **Length** → ``writing.seconds``; **pauses** in the sound (silences over 0.25 s) → ``voice.pause``.

It measures; it does not copy: no frames, fonts or audio are kept. Captions, fonts and the voice stay the
default's until you change them (the YAML says where).
"""

from __future__ import annotations

import colorsys
import json
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import profile

TIMEOUT = 600
SCENE = 0.2  # ffmpeg scene score that counts as a cut (dark-to-dark cuts score ~0.23; motion within a shot < 0.1)
SAMPLE_WIDTH = 36


class ReferenceVideoError(Exception):
    """Shown as it is; nothing was written."""


@dataclass(frozen=True)
class Measured:
    seconds: float
    cuts: int
    pauses: tuple[float, ...]  # each silence's length
    colours: Counter  # (r, g, b) bin centre → pixels

    @property
    def shot(self) -> float:
        """Average seconds between cuts."""
        return self.seconds / (self.cuts + 1)


def _run(args: list[str], binary: bool = False) -> subprocess.CompletedProcess:
    try:
        done = subprocess.run(args, capture_output=True, text=not binary, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReferenceVideoError(f"{args[0]} failed: {exc}") from None
    if done.returncode != 0:
        err = done.stderr if isinstance(done.stderr, str) else done.stderr.decode(errors="replace")
        raise ReferenceVideoError(f"{args[0]} could not read the video: {err.strip()[-200:]}")
    return done


def measure(video: Path) -> Measured:
    if not video.is_file():
        raise ReferenceVideoError(f"{video} not found")
    log = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-filter_complex",
                f"[0:v]select='gt(scene,{SCENE})',showinfo[v];[0:a]silencedetect=n=-35dB:d=0.25[a]",
                "-map", "[v]", "-map", "[a]", "-f", "null", "-"]).stderr
    seconds = float(_run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(video)]).stdout.strip() or 0)
    cuts = len(re.findall(r"Parsed_showinfo.*pts_time:", log))
    pauses = tuple(float(x) for x in re.findall(r"silence_duration: ([\d.]+)", log))
    raw = _run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps=2,scale={SAMPLE_WIDTH}:-2",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], binary=True).stdout
    colours = Counter((r // 32 * 32 + 16, g // 32 * 32 + 16, b // 32 * 32 + 16)
                      for r, g, b in zip(raw[0::3], raw[1::3], raw[2::3]))
    return Measured(seconds, cuts, pauses, colours)


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, c)) for c in rgb))


def _hsv(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(*(c / 255 for c in rgb))


def _luma(rgb: tuple[int, int, int]) -> float:
    def lin(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    hi, lo = sorted((_luma(a), _luma(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _hue_gap(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    gap = abs(_hsv(a)[0] - _hsv(b)[0])
    return min(gap, 1 - gap) * 360


def palette(colours: Counter) -> dict[str, str]:
    """Theme colours from the counted bins (only the ones found; the rest stay the default's)."""
    ranked = [c for c, _n in colours.most_common()]
    dark = [c for c in ranked if _hsv(c)[2] < 0.3]
    bg = dark[0] if dark else ranked[0]
    out = {"bg": _hex(bg), "glow": _hex(tuple(min(255, int(c * 1.6) + 12) for c in bg)),
           "panel": _hex(tuple(min(255, int(c * 1.25) + 8) for c in bg))}
    light = _luma(bg) > 0.4
    out["text"], out["muted"] = ("#15171c", "#5b6170") if light else ("#f5f7fb", "#9aa4bf")
    vivid = [c for c in ranked if _hsv(c)[1] > 0.5 and _hsv(c)[2] > 0.5 and contrast(c, bg) >= 3]
    if vivid:
        out["accent"] = _hex(vivid[0])
        other = [c for c in vivid[1:] if _hue_gap(c, vivid[0]) > 60]
        if other:
            out["cool"] = _hex(other[0])
    return out


# Average shot length (s) → motion: the first row whose limit is above it.
PACE = (
    (1.2, {"feel": "snappy", "transition": "cut", "transition_frames": 4, "punch": 0.14, "drift": 0.03}),
    (2.5, {"feel": "snappy", "transition": "whip", "transition_frames": 6, "punch": 0.11, "drift": 0.04}),
    (5.0, {"feel": "snappy", "transition": "push", "transition_frames": 8, "punch": 0.08, "drift": 0.05}),
    (float("inf"), {"feel": "soft", "transition": "fade", "transition_frames": 12, "punch": 0.04, "drift": 0.07}),
)


def motion(shot: float) -> dict[str, object]:
    return next(values for limit, values in PACE if shot < limit)


def _yaml_block(name: str, values: dict[str, object]) -> str:
    lines = [f"{name}:"]
    for key, value in values.items():
        lines.append(f'  {key}: "{value}"' if isinstance(value, str) and value.startswith("#") else f"  {key}: {value}")
    return "\n".join(lines)


def write(video: Path, name: str, home: Path, force: bool = False) -> tuple[Path, str]:
    """The profile file and a one-paragraph summary of what was measured."""
    if not profile.NAME.match(name):
        raise ReferenceVideoError("Profile names are lowercase letters, digits, - and _")
    path = home / "studio" / "profiles" / f"{name}.yaml"
    if path.exists() and not force:
        raise ReferenceVideoError(f"{path} exists; pass --force to replace it")
    found = measure(video)
    colours, pace = palette(found.colours), motion(found.shot)
    pause = round(min(0.6, max(0.1, sorted(found.pauses)[len(found.pauses) // 2])), 2) if found.pauses else None
    seconds = int(min(180, max(10, round(found.seconds))))
    summary = (f"{found.seconds:.1f} s, {found.cuts} cuts (a shot every {found.shot:.1f} s), "
               f"{len(found.pauses)} pauses; colours {colours['bg']} / {colours.get('accent', 'default accent')}")
    text = "\n\n".join(filter(None, [
        f"# Measured from {video.name}: {summary}.\n# Captions, fonts and the voice are the default's: change them "
        "below (fields: orchestrator/studio/profile.py).\nextends: default\n"
        "description: " + json.dumps(f"From {video.name}: a shot every {found.shot:.1f} s, "
                                     f"{pace['transition']} transitions."),
        _yaml_block("theme", colours),
        _yaml_block("motion", pace),
        _yaml_block("voice", {"pause": pause}) if pause is not None else "",
        _yaml_block("writing", {"seconds": seconds}),
    ])) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        profile.load(name, home)  # what we wrote must load
    except profile.ProfileError:
        path.unlink()
        raise
    return path, summary
