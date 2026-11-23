"""The streak animations: a GIF drawn here with Pillow (no assets, no model), sent with the Hermes
Telegram bot's own token (``TELEGRAM_BOT_TOKEN``) to your chat (``TELEGRAM_HOME_CHANNEL``, else the
first of ``TELEGRAM_ALLOWED_USERS``).

``clear``: a flame grows, confetti falls and the streak counts up. ``broken``: the flame cools to
smoke and the streak drops to 0. GIFs are cached per (kind, number) under ``myday/anim/``.
"""

from __future__ import annotations

import io
import math
import random
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from orchestrator.brief.net import Http, HttpError

from .game import Event
from .session import Session

SIZE = (480, 320)
FRAMES = 28
FRAME_MS = 70
WARM = [(255, 214, 10), (255, 149, 0), (255, 69, 58)]
COOL = [(142, 142, 147), (99, 99, 102), (72, 72, 74)]
CONFETTI = [(255, 214, 10), (48, 209, 88), (10, 132, 255), (255, 55, 95), (191, 90, 242)]


def _font(size: int) -> ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _flame(draw: ImageDraw.ImageDraw, cx: int, base: int, height: float, colours, wobble: float) -> None:
    for layer, colour in enumerate(colours):
        h = height * (1 - layer * 0.28)
        w = h * 0.55
        tip = (cx + wobble * (layer + 1), base - h)
        points = [tip, (cx + w / 2, base - h * 0.45), (cx + w / 2, base - h * 0.1), (cx, base),
                  (cx - w / 2, base - h * 0.1), (cx - w / 2, base - h * 0.45)]
        draw.polygon(points, fill=colour)
        draw.ellipse((cx - w / 2, base - w * 0.9, cx + w / 2, base), fill=colour)


def _centered(draw, y: int, text: str, size: int, fill) -> None:
    font = _font(size)
    width = draw.textlength(text, font=font)
    draw.text(((SIZE[0] - width) / 2, y), text, font=font, fill=fill)


def _clear_frames(streak: int) -> list[Image.Image]:
    rng = random.Random(streak)
    bits = [(rng.uniform(0, SIZE[0]), rng.uniform(-SIZE[1], 0), rng.uniform(4, 9), rng.choice(CONFETTI),
             rng.uniform(5, 11)) for _ in range(70)]
    frames = []
    for f in range(FRAMES):
        t = f / (FRAMES - 1)
        img = Image.new("RGB", SIZE, (28, 28, 30))
        draw = ImageDraw.Draw(img)
        for x, y, size, colour, speed in bits:
            yy = (y + speed * f * 2.2) % (SIZE[1] + 20) - 10
            draw.rectangle((x, yy, x + size, yy + size * 0.6), fill=colour)
        grow = min(1.0, t * 1.6)
        _flame(draw, SIZE[0] // 2, 190, 40 + 90 * grow, WARM, math.sin(f * 0.9) * 3)
        shown = streak if t > 0.55 else max(streak - 1, 0)
        pop = 64 if 0.55 < t < 0.7 else 54
        _centered(draw, 200, f"{shown}", pop, (255, 255, 255))
        _centered(draw, 266, "ALL CLEAR  ·  STREAK +1", 22, (255, 214, 10))
        frames.append(img)
    return frames


def _broken_frames(streak: int) -> list[Image.Image]:
    rng = random.Random(1000 + streak)
    puffs = [(rng.uniform(200, 280), rng.uniform(0, 1), rng.uniform(10, 22)) for _ in range(14)]
    frames = []
    for f in range(FRAMES):
        t = f / (FRAMES - 1)
        img = Image.new("RGB", SIZE, (22, 26, 34))
        draw = ImageDraw.Draw(img)
        shrink = max(0.0, 1 - t * 1.4)
        colours = WARM if t < 0.35 else COOL
        if shrink:
            _flame(draw, SIZE[0] // 2, 190, 20 + 110 * shrink, colours, math.sin(f) * 2)
        for x, phase, r in puffs:
            age = (t * 1.5 + phase) % 1
            if t > 0.3:
                y = 180 - age * 150
                grey = int(120 - age * 70)
                draw.ellipse((x - r * (1 + age), y - r, x + r * (1 + age), y + r), outline=(grey, grey, grey + 10),
                             width=2)
        shown = streak if t < 0.6 else 0
        _centered(draw, 200, f"{shown}", 54, (174, 174, 178) if t >= 0.6 else (255, 255, 255))
        _centered(draw, 266, "STREAK RESET  ·  START AGAIN TODAY", 20, (100, 210, 255))
        frames.append(img)
    return frames


def gif(event: Event, cache: Path) -> bytes:
    path = cache / f"{event.kind}-{event.streak}.gif"
    if path.is_file():
        return path.read_bytes()
    frames = (_clear_frames if event.kind == "clear" else _broken_frames)(event.streak)
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=FRAME_MS, loop=0,
                   optimize=True)
    cache.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())
    return buf.getvalue()


def caption(event: Event) -> str:
    if event.kind == "clear":
        return f"🎉 All clear! 🔥 {event.streak}-day streak"
    lost = f"your {event.streak}-day streak" if event.streak else "the day"
    return f"🧊 Tasks were left open, so {lost} reset. New day, new streak."


def _multipart(fields: dict[str, str], file_field: str, filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
                  "Content-Type: image/gif\r\n\r\n").encode() + content + b"\r\n")
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
        body, ctype = _multipart({"chat_id": chat, "caption": caption(event)}, "animation", "streak.gif",
                                 gif(event, session.state_dir / "anim"))
        try:
            (http or session.http).request("POST", f"{base}/bot{token}/sendAnimation", data=body,
                                           headers={"Content-Type": ctype})
        except HttpError as exc:
            notes.append(f"{caption(event)} (animation not sent: HTTP {exc.status})")
    return notes
