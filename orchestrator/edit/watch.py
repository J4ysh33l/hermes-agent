"""What the camera saw, for the editor: measurements of the footage (``watch_worker.py`` in the studio venv)
turned into a shot log in words, dense frame sheets it can look at, and where your face is so punch-ins
zoom towards it.

The editor (Claude) can't play a video. It gets:
- an overview of how it was recorded (resolution, framing, light, sharpness, sound in the room);
- a log per sentence: where the face is, light, focus, movement, the moments the face leaves the frame or the
  picture jumps;
- frame sheets: a frame about every second, each labelled with its time and the word being said (S4.12).
"""

from __future__ import annotations

import json
import re
import shutil
import statistics
import subprocess
from pathlib import Path
from typing import Any

from orchestrator.studio.settings import Settings as StudioSettings
from orchestrator.studio.voice import _paths

from .media import run
from .words import Sentence

WORKER = Path(__file__).with_name("watch_worker.py")
TIMEOUT = 1800
GRID = (5, 4)  # thumbnails per frame sheet (columns, rows)
FONT = Path(__file__).resolve().parents[1] / "studio/remotion/node_modules/@fontsource/inter/files/inter-latin-700-normal.woff"


class WatchError(RuntimeError):
    pass


def step_for(seconds: float) -> float:
    """About one look a second; longer videos are sampled more sparsely (at most ~240 frames)."""
    return max(1.0, round(seconds / 240, 1))


def measure(source: Path, studio: StudioSettings, home: Path, out: Path, seconds: float) -> dict[str, Any]:
    python, _models = _paths(studio, home)
    if not python.is_file():
        raise WatchError(f"the studio is not installed ({python} missing)")
    try:
        done = subprocess.run([str(python), "-I", str(WORKER)], input=json.dumps({"video": str(source), "step": step_for(seconds)}),
                              capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise WatchError(f"looking at the footage took over {TIMEOUT // 60} minutes") from None
    if done.returncode != 0:
        tail = (done.stderr or "").strip().splitlines()[-1:] or ["no error text"]
        raise WatchError(f"looking at the footage failed: {tail[0][:300]} (pip install opencv-python-headless in the studio venv)")
    result = json.loads(done.stdout.strip().splitlines()[-1])
    out.write_text(json.dumps(result), encoding="utf-8")
    return result


def room(voice_raw: Path) -> str:
    """The sound of the room, from the untouched voice track: speech level (loud 10% of 50 ms windows) against
    the quiet between words (quiet 10%)."""
    text = run(["ffmpeg", "-v", "error", "-i", str(voice_raw), "-af",
                "asetnsamples=2400,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
                "-f", "null", "-"])
    levels = sorted(float(v) for v in re.findall(r"RMS_level=(-?[\d.]+)", text) if float(v) > -120)
    if len(levels) < 20:
        return "sound: not measured"
    quiet, loud = levels[len(levels) // 10], levels[len(levels) * 9 // 10]
    gap = loud - quiet
    verdict = "clean" if gap > 38 else "some room noise (clean-up softens it)" if gap > 25 else "noisy: hum or room noise under the voice"
    return f"sound: voice about {gap:.0f} dB above the room between words ({quiet:.0f} dBFS), {verdict}"


def _anchor(found: list[Sentence], t: float) -> str:
    for s in found:
        if s.start - 0.3 <= t <= s.end + 0.3:
            k = min(range(len(s.words)), key=lambda i: abs(s.words[i].start - t))
            return f"S{s.id}.{k + 1}"
    return "pause"


def _fmt(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}" if t >= 60 else f"{t:.1f}s"


def overview(data: dict[str, Any], described: str, sound: str) -> str:
    samples = data.get("samples") or []
    if not samples:
        return f"- footage: {described}\n- {sound}"
    faces = [s["face"] for s in samples if s["face"]]
    share = len(faces) / len(samples)
    lines = [f"- footage: {described}"]
    if faces:
        cx = statistics.median(f[0] + f[2] / 2 for f in faces)
        eyes = statistics.median(f[1] + f[3] * 0.4 for f in faces)
        width = statistics.median(f[2] for f in faces)
        shot = "close-up" if width > 0.45 else "head and shoulders" if width > 0.22 else "medium/wide shot"
        side = "centred" if 0.4 <= cx <= 0.6 else "left of centre" if cx < 0.4 else "right of centre"
        lines.append(f"- framing: {shot}, face {side} (centre at {cx:.0%} across), eyes about {eyes:.0%} down, "
                     f"face {width:.0%} of the frame width; face visible in {share:.0%} of the video")
        lines.append(f"- top {min(eyes - 0.12, 0.3):.0%} of the frame is above the head (title card room)" if eyes > 0.2
                     else "- the head is near the top edge: a title card at the top will cover it")
    else:
        lines.append("- framing: no face found (a screen recording, or the face is turned away or too small)")
    light = statistics.median(s["light"] for s in samples)
    spread = max(s["light"] for s in samples) - min(s["light"] for s in samples)
    lines.append(f"- light: {'dark' if light < 70 else 'bright' if light > 185 else 'even'} (median {light:.0f}/255)"
                 + (", changes a lot during the video (exposure not locked?)" if spread > 50 else ", steady"))
    sharp = [s["sharp"] for s in samples if s["face"]] or [s["sharp"] for s in samples]
    med = statistics.median(sharp)
    lines.append(f"- focus: {'soft' if med < 40 else 'sharp'} (detail {med:.0f}; under ~40 looks soft on a phone)")
    lines.append(f"- {sound}")
    return "\n".join(lines)


def log(data: dict[str, Any], found: list[Sentence]) -> str:
    """One line per sentence: what the picture does while it is said."""
    samples = data.get("samples") or []
    if not samples:
        return "(not measured)"
    all_sharp = [s["sharp"] for s in samples if s["face"]] or [s["sharp"] for s in samples]
    soft_at = statistics.median(all_sharp) * 0.55
    lines = []
    for s in found:
        mine = [x for x in samples if s.start - 0.2 <= x["t"] <= s.end + 0.2] or \
               [min(samples, key=lambda x: abs(x["t"] - (s.start + s.end) / 2))]
        faces = [x["face"] for x in mine if x["face"]]
        notes = []
        if not faces:
            notes.append("no face in frame")
        else:
            gone = [x["t"] for x in mine if not x["face"]]
            if gone:
                notes.append(f"face lost at {', '.join(_fmt(t) for t in gone[:3])}")
            cx = statistics.median(f[0] + f[2] / 2 for f in faces)
            w = statistics.median(f[2] for f in faces)
            drift = max(f[0] + f[2] / 2 for f in faces) - min(f[0] + f[2] / 2 for f in faces)
            notes.append(f"face at {cx:.0%} across, {w:.0%} wide" + (", moving around" if drift > 0.12 else ""))
            if len({x["faces"] for x in mine}) > 1 or max(x["faces"] for x in mine) > 1:
                notes.append("another face may be in frame")
        light = statistics.mean(x["light"] for x in mine)
        if light < 60:
            notes.append(f"dark ({light:.0f})")
        elif light > 200:
            notes.append(f"bright ({light:.0f})")
        soft = [x["t"] for x in mine if x["sharp"] < soft_at]
        if soft:
            notes.append(f"soft/blurred at {', '.join(_fmt(t) for t in soft[:3])}")
        motion = max(x["motion"] for x in mine)
        if motion > 12:
            notes.append(f"big movement (camera or hands, {motion:.0f})")
        elif motion < 1.5:
            notes.append("very still")
        jumps = [x["t"] for x in mine if x["cut"]]
        if jumps:
            notes.append(f"picture jumps at {', '.join(_fmt(t) for t in jumps[:3])} (a cut in the raw, a fast camera "
                         "move, or something passing the lens)")
        lines.append(f"S{s.id} {_fmt(s.start)}–{_fmt(s.end)}: " + "; ".join(notes))
    return "\n".join(lines)


def sheets(source: Path, data: dict[str, Any], found: list[Sentence], folder: Path) -> list[str]:
    """A frame every ``step`` s, labelled "12.0s S4.12", 5×4 to a JPEG (frames-1.jpg, ...)."""
    for old in folder.glob("frames-*.jpg"):
        old.unlink()
    times = [s["t"] for s in data.get("samples") or []] or [round((s.start + s.end) / 2, 2) for s in found]
    thumbs = folder / "thumbs"
    shutil.rmtree(thumbs, ignore_errors=True)
    thumbs.mkdir(parents=True)
    font = f"fontfile='{FONT}':" if FONT.is_file() else ""
    for n, t in enumerate(times):
        label = f"{_fmt(t)} {_anchor(found, t)}".replace(":", "\\:")
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(source), "-frames:v", "1", "-vf",
             f"scale=216:384,drawtext={font}text='{label}':fontsize=20:fontcolor=white:box=1:boxcolor=black@0.7:"
             "boxborderw=5:x=6:y=6", "-q:v", "5", str(thumbs / f"{n:04d}.jpg")])
    per = GRID[0] * GRID[1]
    names = []
    for k in range(0, len(times), per):
        name = f"frames-{k // per + 1}.jpg"
        run(["ffmpeg", "-y", "-v", "error", "-start_number", str(k), "-i", str(thumbs / "%04d.jpg"),
             "-vf", f"tile={GRID[0]}x{GRID[1]}:padding=4:color=white", "-frames:v", "1", "-q:v", "4", str(folder / name)])
        names.append(name)
    shutil.rmtree(thumbs, ignore_errors=True)
    return names


def look(job: Path, found: list[Sentence], studio: StudioSettings, home: Path, described: str, seconds: float) -> dict[str, Any]:
    """Measure, draw the sheets and write ``watch.md`` (the overview and the log). Returns what the prompt needs."""
    try:
        data = measure(job / "source.mp4", studio, home, job / "watch.json", seconds)
    except WatchError as exc:
        data = {"samples": [], "error": str(exc)}
    names = sheets(job / "source.mp4", data, found, job)
    raw = job / "voice-raw.wav"
    sound = room(raw) if raw.is_file() else "sound: not measured"
    text = overview(data, described, sound)
    if data.get("error"):
        text += f"\n- (measurements failed: {data['error']}; judge from the frame sheets)"
    (job / "watch.md").write_text("## How it was recorded\n\n" + text + "\n\n## Shot log\n\n" + log(data, found) + "\n",
                                  encoding="utf-8")
    return {"sheets": names, "watch": (job / "watch.md").read_text(encoding="utf-8")}


def focus(job: Path, start: float, end: float) -> tuple[float, float]:
    """Where to zoom towards for a shot: the face's centre (fractions of the frame), else just above centre."""
    path = job / "watch.json"
    if path.is_file():
        faces = [s["face"] for s in json.loads(path.read_text(encoding="utf-8")).get("samples", [])
                 if s["face"] and start - 0.5 <= s["t"] <= end + 0.5]
        if faces:
            return (round(statistics.median(f[0] + f[2] / 2 for f in faces), 3),
                    round(statistics.median(f[1] + f[3] * 0.45 for f in faces), 3))
    return 0.5, 0.42
