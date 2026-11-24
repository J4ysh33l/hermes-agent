"""A storyboard (JSON) → checked, frozen scenes for ``video.make``.

{"title": "Rust in 30 seconds", "profile": "bold",
 "scenes": [{"type": "title", "say": "Rust is fast. Really fast.", "text": "Rust is fast", "kicker": "100 seconds"},
            {"type": "bullets", "say": "...", "title": "Why", "items": ["No GC", "Zero-cost abstractions"]},
            {"type": "code", "say": "...", "title": "main.rs", "code": "fn main() {}"},
            {"type": "stat", "say": "...", "value": 87, "suffix": "%", "label": "most loved language"},
            {"type": "image", "say": "...", "src": "crab.jpg", "caption": "Ferris"},
            {"type": "compare", "say": "...", "left": {"label": "C++", "points": ["..."]},
                                              "right": {"label": "Rust", "points": ["..."]}}]}

``say`` is the narration for the scene (the scene lasts as long as it takes to say); wrap words in
``*asterisks*`` to emphasise them (caption colour + a camera punch-in; the voice never hears the
asterisks). The other keys are what is on screen, plus optional ``enter`` (pop, rise, slide, drop, zoom,
fade) and ``exit`` (lift, fade, whip, zoom, cut) to override the profile's motion for that scene.
``profile`` names the page profile (default: studio.profile). ``src`` is a file next to the storyboard, or an https URL. Unknown types or keys are refused,
so a typo fails here and not halfway through a render.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .profile import SCHEMA as PROFILE_SCHEMA
from .profile import ProfileError
from .voice import sentences

MAX_SCENES = 40
MAX_ITEMS = 6


class StoryboardError(ValueError):
    """Shown as it is; nothing was rendered."""


@dataclass(frozen=True)
class Scene:
    type: str
    say: str  # what the voice reads (no asterisks)
    marked: str  # the narration as written, *emphasis* kept, for captions
    fields: Mapping[str, Any]  # what is on screen, per SCHEMA[type]
    enter: str  # "" = the profile's
    exit: str


@dataclass(frozen=True)
class Storyboard:
    title: str
    scenes: tuple[Scene, ...]
    folder: Path  # where relative ``src`` files are
    profile: str  # "" = studio.profile


Field = Callable[[str, Any], Any]
MISSING = object()


def _text(required: bool) -> Field:
    def parse(where: str, value: Any) -> str:
        if value is MISSING or value in ("", None):
            if required:
                raise StoryboardError(f"{where} is required")
            return ""
        if not isinstance(value, (str, int, float)):
            raise StoryboardError(f"{where} must be text")
        return str(value).strip()
    return parse


def _number(where: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StoryboardError(f"{where} must be a number")
    return value


def _items(where: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or len(value) > MAX_ITEMS:
        raise StoryboardError(f"{where} must be a list of 1 to {MAX_ITEMS} lines")
    return tuple(_text(True)(f"{where}[{n}]", v) for n, v in enumerate(value))


def _side(where: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise StoryboardError(f"{where} must be {{\"label\": ..., \"points\": [...]}}")
    return MappingProxyType({"label": _text(True)(f"{where}.label", value.get("label", MISSING)),
                             "points": _items(f"{where}.points", value.get("points", MISSING))})


SCHEMA: dict[str, dict[str, Field]] = {
    "title": {"text": _text(True), "kicker": _text(False)},
    "bullets": {"title": _text(False), "items": _items},
    "code": {"title": _text(False), "code": _text(True)},
    "stat": {"value": _number, "prefix": _text(False), "suffix": _text(False), "label": _text(True)},
    "image": {"src": _text(True), "caption": _text(False)},
    "compare": {"left": _side, "right": _side},
}


def _scene(n: int, raw: Any) -> Scene:
    where = f"scene {n + 1}"
    if not isinstance(raw, dict):
        raise StoryboardError(f"{where} must be an object")
    kind = raw.get("type")
    if kind not in SCHEMA:
        raise StoryboardError(f"{where}: type must be one of {', '.join(SCHEMA)}")
    unknown = set(raw) - set(SCHEMA[kind]) - {"type", "say", "enter", "exit"}
    if unknown:
        raise StoryboardError(f"{where} ({kind}): unknown key {min(unknown)!r}")
    marked = _text(True)(f"{where}.say", raw.get("say", MISSING))
    if marked.count("*") % 2:
        raise StoryboardError(f"{where}.say: an *emphasis* is not closed")
    say = marked.replace("*", "")
    if not sentences(say):
        raise StoryboardError(f"{where}.say has nothing to say")
    motion = {}
    for key in ("enter", "exit"):
        value = raw.get(key, "")
        try:
            motion[key] = PROFILE_SCHEMA["motion"][key](f"{where}.{key}", value) if value else ""
        except ProfileError as exc:
            raise StoryboardError(str(exc)) from None
    fields = {key: parse(f"{where}.{key}", raw.get(key, MISSING)) for key, parse in SCHEMA[kind].items()}
    return Scene(kind, say, marked, MappingProxyType(fields), motion["enter"], motion["exit"])


def parse(raw: Any, folder: Path) -> Storyboard:
    if not isinstance(raw, dict) or not isinstance(raw.get("scenes"), list) or not raw["scenes"]:
        raise StoryboardError('A storyboard is {"title": ..., "scenes": [...]} with at least one scene')
    if len(raw["scenes"]) > MAX_SCENES:
        raise StoryboardError(f"At most {MAX_SCENES} scenes")
    unknown = set(raw) - {"title", "scenes", "profile"}
    if unknown:
        raise StoryboardError(f"unknown key {min(unknown)!r} in the storyboard")
    scenes = tuple(_scene(n, s) for n, s in enumerate(raw["scenes"]))
    for n, scene in enumerate(scenes):
        src = str(scene.fields.get("src", ""))
        if src and not src.startswith("https://") and not (folder / src).is_file():
            raise StoryboardError(f"scene {n + 1}.src: {folder / src} not found")
    return Storyboard(_text(False)("title", raw.get("title", MISSING)), scenes, folder,
                      _text(False)("profile", raw.get("profile", MISSING)))


def load(path: Path) -> Storyboard:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoryboardError(f"Could not read {path}: {exc}") from None
    return parse(raw, path.parent)
