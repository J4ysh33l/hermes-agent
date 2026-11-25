"""Your raw footage → the two files every later step reads, made once per job:

- ``source.mp4``: the picture as H.264 at a constant frame rate (phones record a variable one, which makes
  cuts and captions drift), 1080×1920, SDR (iPhone HDR is tone-mapped or it looks washed out), turned
  upright, near lossless (``edit.mezzanine_crf``). Landscape footage is cropped to the middle; the plan can
  move the crop (``frame_x``).
- ``voice.wav``: your voice, mono 48 kHz, cleaned to the style's ``sound`` (rumble cut, noise reduced,
  sibilance softened, gently levelled); ``voice16.wav`` is the same at 16 kHz for transcription.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .style import Style

TIMEOUT = 3600
W, H = 1080, 1920
HDR = ("smpte2084", "arib-std-b67")  # PQ (Dolby Vision/HDR10), HLG (iPhone)


class MediaError(Exception):
    """Shown as it is; the job stops."""


@dataclass(frozen=True)
class Info:
    seconds: float
    width: int  # upright
    height: int
    fps: float
    variable: bool  # variable frame rate
    hdr: bool
    codec: str
    audio: bool

    def describe(self) -> str:
        return (f"{self.width}×{self.height} {self.codec} at {self.fps:.2f} fps{' (variable)' if self.variable else ''}"
                f"{', HDR' if self.hdr else ''}, {self.seconds:.1f} s{'' if self.audio else ', NO SOUND'}")


def run(args: list[str], timeout: int = TIMEOUT) -> str:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaError(f"{args[0]} failed: {exc}") from None
    if done.returncode != 0:
        raise MediaError(f"{args[0]} failed: {done.stderr.strip()[-400:]}")
    return done.stdout + done.stderr


def _rate(text: str) -> float:
    try:
        value = Fraction(text or "0/1")
    except (ValueError, ZeroDivisionError):
        return 0.0
    return float(value) if value.denominator else 0.0


def _rotation(stream: dict) -> int:
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            return int(float(side["rotation"])) % 360
    return int(float((stream.get("tags") or {}).get("rotate", 0))) % 360


def probe(path: Path) -> Info:
    raw = json.loads(run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)]))
    video = next((s for s in raw.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError(f"{path.name} has no picture")
    audio = any(s.get("codec_type") == "audio" for s in raw.get("streams", []))
    w, h = int(video.get("width", 0)), int(video.get("height", 0))
    if _rotation(video) in (90, 270):
        w, h = h, w
    real, average = _rate(video.get("r_frame_rate", "")), _rate(video.get("avg_frame_rate", ""))
    seconds = float(raw.get("format", {}).get("duration") or video.get("duration") or 0)
    return Info(seconds, w, h, average or real, bool(real and average and abs(real - average) > 0.01 * real),
                video.get("color_transfer", "") in HDR, str(video.get("codec_name", "?")), audio)


def picture_filter(info: Info, fps: int, frame_x: float = 0.5) -> str:
    """The filter chain for source.mp4: tone-map, fill 1080×1920 (crop at ``frame_x`` across), constant fps."""
    steps = []
    if info.hdr:
        steps.append("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
                     "zscale=t=bt709:m=bt709:r=tv")
    steps.append(f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos")
    x = min(1.0, max(0.0, frame_x))
    steps.append(f"crop={W}:{H}:(iw-{W})*{x:.3f}:(ih-{H})/2")
    steps += [f"fps={fps}", "setsar=1", "format=yuv420p"]
    return ",".join(steps)


def voice_filter(look: Style) -> str:
    sound = look["sound"]
    steps = ["highpass=f=80"]
    if sound["denoise"] == "light":
        steps.append("afftdn=nr=10:nf=-50:tn=1")
    elif sound["denoise"] == "strong":
        steps.append("afftdn=nr=20:nf=-42:tn=1")
    if sound["deess"]:
        steps.append("deesser=i=0.4:m=0.5:f=0.5")
    steps.append("acompressor=threshold=-22dB:ratio=2.5:attack=8:release=160:makeup=2")
    return ",".join(steps)


def prepare(src: Path, folder: Path, look: Style, fps: int, crf: int, threads: int, frame_x: float = 0.5) -> Info:
    """source.mp4, voice-raw.wav, voice.wav and voice16.wav in ``folder``; returns what the upload was."""
    info = probe(src)
    if not info.audio:
        raise MediaError(f"{src.name} has no sound: the edit is cut on your words")
    folder.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map", "0:v:0", "-vf", picture_filter(info, fps, frame_x),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-threads", str(threads),
         "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-an", str(folder / "source.mp4")])
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map", "0:a:0", "-af", "aresample=async=1", "-ac", "1",
         "-ar", "48000", str(folder / "voice-raw.wav")])
    clean(folder / "voice-raw.wav", folder / "voice.wav", look)
    return info


def clean(raw: Path, dst: Path, look: Style) -> Path:
    run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af", voice_filter(look), "-ac", "1", "-ar", "48000", str(dst)])
    run(["ffmpeg", "-y", "-v", "error", "-i", str(dst), "-ac", "1", "-ar", "16000", str(dst.with_name(dst.stem + "16.wav"))])
    return dst
