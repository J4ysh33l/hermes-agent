"""Sending the streak animations (drawn in ``anim``) with the Hermes Telegram bot's own token
(``TELEGRAM_BOT_TOKEN``) to your chat (``TELEGRAM_HOME_CHANNEL``, else the first of
``TELEGRAM_ALLOWED_USERS``).

Encoded as H.264 MP4 with ffmpeg (smooth gradients; Telegram plays it as a looping animation),
or as a GIF when ffmpeg is not installed. Cached per (kind, number) under ``myday/anim/``.
"""

from __future__ import annotations

import io
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from orchestrator.brief.net import Http, HttpError

from . import anim
from .game import Event
from .session import Session


@dataclass(frozen=True)
class Clip:
    data: bytes
    filename: str
    mime: str


def _frames(event: Event) -> list[Image.Image]:
    return (anim.clear_frames if event.kind == "clear" else anim.broken_frames)(event.streak)


def _mp4(frames: list[Image.Image], path: Path) -> bool:
    """Write ``path``; False when ffmpeg is missing or fails (the GIF is used instead)."""
    raw = b"".join(f.tobytes() for f in frames)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{anim.OUT}x{anim.OUT}",
           "-r", str(anim.FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
           "-preset", "slow", "-movflags", "+faststart", str(path)]
    try:
        done = subprocess.run(cmd, input=raw, capture_output=True, timeout=120, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0 and path.is_file() and path.stat().st_size > 0


def _gif(frames: list[Image.Image]) -> bytes:
    buf = io.BytesIO()
    small = [f.convert("P", palette=Image.ADAPTIVE, colors=255) for f in frames]
    small[0].save(buf, format="GIF", save_all=True, append_images=small[1:], duration=1000 // anim.FPS, loop=0)
    return buf.getvalue()


def clip(event: Event, cache: Path) -> Clip:
    stem = cache / f"{event.kind}-{event.streak}.v2"
    for ext, mime in (("mp4", "video/mp4"), ("gif", "image/gif")):
        path = stem.with_suffix(f".v2.{ext}")
        if path.is_file():
            return Clip(path.read_bytes(), f"streak.{ext}", mime)
    cache.mkdir(parents=True, exist_ok=True)
    frames = _frames(event)
    mp4 = stem.with_suffix(".v2.mp4")
    if _mp4(frames, mp4):
        return Clip(mp4.read_bytes(), "streak.mp4", "video/mp4")
    mp4.unlink(missing_ok=True)
    gif = stem.with_suffix(".v2.gif")
    gif.write_bytes(_gif(frames))
    return Clip(gif.read_bytes(), "streak.gif", "image/gif")


def caption(event: Event) -> str:
    if event.kind == "clear":
        return f"🎉 All clear! 🔥 {event.streak}-day streak"
    lost = f"your {event.streak}-day streak" if event.streak else "the day"
    return f"🧊 Tasks were left open, so {lost} reset. New day, new streak."


def _multipart(fields: dict[str, str], file_field: str, media: Clip) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{media.filename}"\r\n'
                  f"Content-Type: {media.mime}\r\n\r\n").encode() + media.data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def chat_id(session: Session) -> str:
    home = session.secrets.get("TELEGRAM_HOME_CHANNEL")
    allowed = session.secrets.get("TELEGRAM_ALLOWED_USERS").split(",")[0].strip()
    return home or allowed


def send(session: Session, events: tuple[Event, ...] | list[Event], http: Http | None = None) -> list[str]:
    """Send one animation per event. Returns notes for anything not sent (shown under the reply)."""
    token, chat = session.secrets.get("TELEGRAM_BOT_TOKEN"), chat_id(session)
    if not events:
        return []
    if not (token and chat):
        return [caption(e) for e in events]  # no bot set up (CLI, tests): the words still celebrate
    base = session.secrets.get("TELEGRAM_API_HOST") or "https://api.telegram.org"
    notes = []
    for event in events:
        body, ctype = _multipart({"chat_id": chat, "caption": caption(event)}, "animation",
                                 clip(event, session.state_dir / "anim"))
        try:
            (http or session.http).request("POST", f"{base}/bot{token}/sendAnimation", data=body,
                                           headers={"Content-Type": ctype})
        except HttpError as exc:
            notes.append(f"{caption(event)} (animation not sent: HTTP {exc.status})")
    return notes
