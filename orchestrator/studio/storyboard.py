"""A storyboard (JSON) → checked, frozen scenes for ``video.make``.

{"title": "Rust in 30 seconds", "profile": "bold",
 "scenes": [{"type": "title", "say": "Rust is fast. Really fast.", "text": "Rust is fast", "kicker": "100 seconds"},
            {"type": "bullets", "say": "...", "title": "Why", "items": ["No GC", "Zero-cost abstractions"]},
            {"type": "code", "say": "...", "title": "main.rs", "code": "fn main() {}"},
            {"type": "stat", "say": "...", "value": 87, "suffix": "%", "label": "most loved language"},
            {"type": "image", "say": "...", "src": "crab.jpg", "caption": "Ferris"},
            {"type": "compare", "say": "...", "left": {"label": "C++", "points": ["..."]},
                                              "right": {"label": "Rust", "points": ["..."]}},
            {"type": "terminal", "say": "...", "lines": ["$ cargo new hello", "Created binary package"]},
            {"type": "chart", "say": "...", "kind": "bar", "labels": ["2022", "2023"], "values": [12, 30],
             "suffix": "%", "highlight": 1},                       # kind bar|line; highlight -1 = largest
            {"type": "diagram", "say": "...", "nodes": ["Source", "Compiler", "Binary"]},
            {"type": "quote", "say": "...", "text": "...", "author": "..."},
            {"type": "timeline", "say": "...", "events": [{"when": "2010", "what": "..."}, ...]},
            {"type": "clipping", "say": "...", "source": "The Daily", "date": "12 May 2025",
             "headline": "...", "highlight": "words from the headline"},
            {"type": "post", "say": "...", "name": "...", "handle": "@...", "text": "...", "likes": "12K"},
            {"type": "meme", "say": "...", "src": "cc0-photo.jpg", "top": "...", "bottom": "..."},
            {"type": "beforeafter", "say": "...", "before": {"label": "...", "src": ""}, "after": {"label": "..."}},
            {"type": "logo", "say": "...", "name": "Rust", "src": "rust.svg", "tagline": "..."},
            {"type": "map", "say": "...", "title": "...", "focus": "India", "highlight": ["India", "Japan"],
             "route": ["India", "Japan"], "labels": true},        # Natural Earth country names
            {"type": "statement", "say": "...", "lines": [{"text": "not the *price*", "strike": true},
                                                          {"text": "the *chaos*", "tone": "solution"}], "sub": "..."},
            {"type": "counter", "say": "...", "value": 70, "suffix": "%", "label": "paid out of pocket", "tone": "problem"},
            {"type": "stack", "say": "...", "title": "Who *pays*?", "tone": "problem",
             "rows": [{"text": "No insurance", "icon": "insurance", "mark": "cross"}, ...]},   # 2–4 rows
            {"type": "steps", "say": "...", "title": "How it works", "steps": [{"label": "Book", "icon": "calendar"}, ...]},
            {"type": "points", "say": "...", "title": "The usual *fixes*", "items": ["...", "..."], "numbered": false,
             "struck": true},                                      # struck: all crossed out after the last one
            {"type": "bars", "say": "...", "title": "...", "bars": [{"label": "Screening", "value": "₹1,000", "size": 0.05},
                                                                {"label": "Treatment", "value": "₹5 lakh", "size": 1,
                                                                 "tone": "problem"}]},
            {"type": "balance", "say": "...", "left": "Price", "right": "Chaos", "heavy": "right", "strike": "left"},
            {"type": "badge", "say": "...", "icon": "check", "text": "OPD open every day", "badge": "0 days down"},
            {"type": "custom", "say": "...", "brief": "what is on screen, moment by moment",
             "props": {...}, "full_bleed": false, "component": "coins.tsx",
             "fallback": {"type": "stat", "value": 25, "suffix": "×", "label": "faster"}}]}

The library types are a fast track (ready, tested, quick to render), not the limit. ``custom`` is any
other picture: ``brief`` says what it shows; Claude writes it as a component for this one video
(custom.py), or ``component`` names one written by hand next to the storyboard; ``props`` is data the
component reads; ``fallback`` is a library scene (no "say") drawn instead if the component cannot be
built or fails its checks, so a video never breaks.

Any scene may also have ``"emoji": "🔥"``: it pops on the scene's first *emphasised* word, in a band kept
free above the scene (the scene moves down to make room).

``terminal`` is for software only: real commands and what they print, at least one ``"$ "`` command and one
output line. A scene that is not about a command line (a history, an experiment) is not a terminal:
use a statement, a timeline or a custom scene.

List items, chart bars, diagram boxes, timeline events, statement lines, stack rows, steps, points and bars,
and the "after" panel appear on the sentence that says them when ``say`` has one sentence per item (after any
intro sentences). Statement, counter, stack, steps, points, bars, balance and badge are the explainer scenes
(the same as /edit's): big type, one idea, parts that build; a struck line or point is crossed out as the
next one arrives (or at the end); ``*starred*`` words in their text set in the accent colour, in italic.
Icons: any of the names in icons.py (hospital, wallet, check, cross, chart, users, code, ...).

``say`` is the narration for the scene (the scene lasts as long as it takes to say); wrap words in
``*asterisks*`` to emphasise them (caption colour + a camera punch-in; the voice never hears the
asterisks). Voice directions go in ``say`` too: ``[beat]`` (a 0.4 s pause), ``[pause 0.8]``, and
``[slow]`` / ``[fast]`` for the rest of a sentence (direction.py); captions never show them. The other keys are what is on screen, plus optional ``enter`` (pop, rise, slide, drop, zoom,
fade), ``exit`` (lift, fade, whip, zoom, cut) and ``transition`` into the next scene (none, cut, fade, push,
whip, zoom, flash, burn) to override the profile's motion for that scene.
``profile`` names the page profile (default: studio.profile). ``src`` is a file next to the storyboard,
an https URL, or for an image scene ``stock:<what to show>`` (a public-domain photo found at render time, broll.py). Unknown types or keys are refused, so a typo fails here and not halfway through a render.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from . import direction
from .icons import ICONS
from .text import sentences

MAX_SCENES = 40
MAX_ITEMS = 6
# Motion a scene may set for itself (the page profile's ``motion:`` takes the same values).
ENTERS = ("pop", "rise", "slide", "drop", "zoom", "fade", "mask")
EXITS = ("lift", "fade", "whip", "zoom", "cut")
# Scene to scene: the next scene comes in while this one leaves (overlapping); "none" = the scene's own
# exit, then the next one's entrance; "cut" = a hard cut.
TRANSITIONS = ("none", "cut", "fade", "push", "whip", "zoom", "flash", "burn")
MOTION = {"enter": ENTERS, "exit": EXITS, "transition": TRANSITIONS}


class StoryboardError(ValueError):
    """Shown as it is; nothing was rendered."""


@dataclass(frozen=True)
class Scene:
    type: str
    say: str  # what the voice reads (no asterisks; [directions] kept for the voice)
    marked: str  # the narration as written, *emphasis* and [directions] kept
    fields: Mapping[str, Any]  # what is on screen, per SCHEMA[type]
    enter: str  # "" = the profile's
    exit: str
    emoji: str  # "" = none; pops on the scene's first *emphasised* word
    transition: str = ""  # into the next scene; "" = the profile's


@dataclass(frozen=True)
class Storyboard:
    title: str
    scenes: tuple[Scene, ...]
    folder: Path  # where relative ``src`` files are
    profile: str  # "" = studio.profile
    music: str = ""  # "none" = no music; a mood ("tense ticking electronic"); "" = the profile's music_query


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


def _list(low: int, high: int, each: Field) -> Field:
    def parse(where: str, value: Any) -> tuple[Any, ...]:
        if value is MISSING and low == 0:
            return ()
        if not isinstance(value, list) or not low <= len(value) <= high:
            raise StoryboardError(f"{where} must be a list of {low} to {high}")
        return tuple(each(f"{where}[{n}]", v) for n, v in enumerate(value))
    return parse


def _object(**fields: Field) -> Field:
    def parse(where: str, value: Any) -> Mapping[str, Any]:
        if not isinstance(value, dict):
            raise StoryboardError(f"{where} must be an object with {', '.join(fields)}")
        unknown = set(value) - set(fields)
        if unknown:
            raise StoryboardError(f"{where}: unknown key {min(unknown)!r}")
        return MappingProxyType({key: p(f"{where}.{key}", value.get(key, MISSING)) for key, p in fields.items()})
    return parse


def _choice(*options: str) -> Field:
    def parse(where: str, value: Any) -> str:
        if value is MISSING:
            return options[0]
        if value not in options:
            raise StoryboardError(f"{where} must be one of {', '.join(options)}")
        return value
    return parse


def _flag(default: bool) -> Field:
    def parse(where: str, value: Any) -> bool:
        if value is MISSING:
            return default
        if not isinstance(value, bool):
            raise StoryboardError(f"{where} must be true or false")
        return value
    return parse


def _index(where: str, value: Any) -> int:
    if value is MISSING:
        return -1
    if isinstance(value, bool) or not isinstance(value, int):
        raise StoryboardError(f"{where} must be a whole number (0 = the first)")
    return value


def _number_or(default: float) -> Field:
    def parse(where: str, value: Any) -> float:
        return default if value is MISSING else _number(where, value)
    return parse


def _short(most: int, required: bool = True) -> Field:
    """Text that must stay short enough to read at a glance (one line on screen)."""
    text = _text(required)

    def parse(where: str, value: Any) -> str:
        out = text(where, value)
        if len(out.replace("*", "")) > most:
            raise StoryboardError(f"{where} is {len(out)} characters; at most {most} (say the rest)")
        return out
    return parse


def _icon(required: bool) -> Field:
    def parse(where: str, value: Any) -> str:
        if value is MISSING or value in ("", None):
            if required:
                raise StoryboardError(f"{where} is required (one of {', '.join(ICONS)})")
            return ""
        if value not in ICONS:
            raise StoryboardError(f"{where}: unknown icon {value!r} (icons: {', '.join(ICONS)})")
        return str(value)
    return parse


_items = _list(1, MAX_ITEMS, _text(True))
_tone = _choice("neutral", "problem", "solution")
_side = _object(label=_text(True), points=_items)
_panel = _object(label=_text(True), src=_text(False))


SCHEMA: dict[str, dict[str, Field]] = {
    "title": {"text": _text(True), "kicker": _text(False)},
    "bullets": {"title": _text(False), "items": _items},
    "code": {"title": _text(False), "code": _text(True)},
    "stat": {"value": _number, "prefix": _text(False), "suffix": _text(False), "label": _text(True)},
    "image": {"src": _text(True), "caption": _text(False)},
    "compare": {"left": _side, "right": _side},
    "terminal": {"title": _text(False), "lines": _list(1, 10, _text(True))},
    "chart": {"kind": _choice("bar", "line"), "title": _text(False), "labels": _list(2, 8, _text(True)),
              "values": _list(2, 8, _number), "suffix": _text(False), "highlight": _index},
    "diagram": {"title": _text(False), "nodes": _list(2, 5, _text(True))},
    "quote": {"text": _text(True), "author": _text(False)},
    "timeline": {"title": _text(False), "events": _list(2, 6, _object(when=_text(True), what=_text(True)))},
    "clipping": {"source": _text(True), "date": _text(False), "headline": _text(True), "highlight": _text(False)},
    "post": {"name": _text(True), "handle": _text(False), "text": _text(True), "likes": _text(False)},
    "meme": {"src": _text(True), "top": _text(False), "bottom": _text(False)},
    "beforeafter": {"before": _panel, "after": _panel},
    "logo": {"name": _text(True), "src": _text(False), "tagline": _text(False)},
    "map": {"title": _text(False), "focus": _text(False), "highlight": _list(0, 12, _text(True)),
            "route": _list(0, 6, _text(True)), "labels": _flag(True)},
    # The explainer scenes (shared with /edit, remotion/src/edit/Scenes.tsx); *starred* words in their text
    # set in the accent colour, in italic.
    "statement": {"lines": _list(1, 3, _object(text=_short(30), tone=_tone, strike=_flag(False))), "sub": _short(60, False),
                  "icon": _icon(False)},
    "counter": {"value": _number, "start": _number_or(0), "prefix": _text(False), "suffix": _text(False),
                "label": _short(50), "sub": _short(30, False), "tone": _tone},
    "stack": {"title": _short(40, False), "tone": _choice("problem", "solution"),
              "rows": _list(2, 4, _object(text=_short(32), icon=_icon(False), mark=_choice("none", "cross", "check")))},
    "steps": {"title": _short(40, False), "steps": _list(2, 5, _object(label=_short(22), icon=_icon(False), sub=_short(24, False)))},
    "points": {"title": _short(40), "items": _list(2, 4, _short(32)), "numbered": _flag(False), "struck": _flag(False)},
    "bars": {"title": _short(40, False), "bars": _list(2, 3, _object(label=_short(18), value=_short(12), size=_number, tone=_tone))},
    "balance": {"title": _short(40, False), "left": _short(24), "right": _short(24), "heavy": _choice("right", "left"),
                "strike": _choice("none", "left", "right")},
    "badge": {"icon": _icon(True), "text": _short(30), "badge": _short(30, False)},
}
def _json_object(where: str, value: Any) -> Mapping[str, Any]:
    if value is MISSING:
        return MappingProxyType({})
    if not isinstance(value, dict) or len(json.dumps(value)) > 20_000:
        raise StoryboardError(f"{where} must be an object of data (at most 20 KB)")
    return MappingProxyType(value)


def _fallback(where: str, value: Any) -> Mapping[str, Any]:
    """A library scene's fields with its type, drawn when a custom scene cannot be."""
    if not isinstance(value, dict) or value.get("type") not in set(SCHEMA) - {"custom"}:
        raise StoryboardError(f"{where} must be a library scene ({{\"type\": \"stat\", ...}}) without \"say\"")
    kind = value["type"]
    unknown = set(value) - set(SCHEMA[kind]) - {"type"}
    if unknown:
        raise StoryboardError(f"{where} ({kind}): unknown key {min(unknown)!r}")
    fields = {key: parse(f"{where}.{key}", value.get(key, MISSING)) for key, parse in SCHEMA[kind].items()}
    problem = CHECKS.get(kind, lambda _f: "")(fields)
    if problem:
        raise StoryboardError(f"{where} ({kind}): {problem}")
    return MappingProxyType({"type": kind, **fields})


def library_scene(where: str, value: Any) -> Mapping[str, Any]:
    """A library scene's fields with its type, checked (another pipeline drawing one: an edit's full-frame scene)."""
    return _fallback(where, value)


SCHEMA["custom"] = {"brief": _text(True), "props": _json_object, "full_bleed": _flag(False), "component": _text(False),
                    "fallback": _fallback}
STOCK = "stock:"  # an image scene's src searched at render time (broll.py: public-domain photos, or Pexels/Pixabay with a key)
COMMON = {"type", "say", "enter", "exit", "transition", "emoji"}  # keys every scene may have


def _map(f: Mapping[str, Any]) -> str:
    if not (f["focus"] or f["highlight"] or f["route"]):
        return "needs a focus, highlight or route (country names)"
    return "" if len(f["route"]) != 1 else "a route needs at least two countries"


def countries(fields: Mapping[str, Any]) -> list[str]:
    """Every country a map scene names (checked against the map data before rendering)."""
    return [c for c in (fields.get("focus", ""), *fields.get("highlight", ()), *fields.get("route", ())) if c]


def _chart(f: Mapping[str, Any]) -> str:
    if len(f["labels"]) != len(f["values"]):
        return f"labels ({len(f['labels'])}) and values ({len(f['values'])}) must pair up"
    if f["highlight"] >= len(f["values"]):
        return f"highlight {f['highlight']} is past the last value"
    return ""


def _clipping(f: Mapping[str, Any]) -> str:
    missing = f["highlight"] and f["highlight"].lower() not in f["headline"].lower()
    return f"highlight {f['highlight']!r} is not in the headline" if missing else ""


def _bars(f: Mapping[str, Any]) -> str:
    return "" if all(0 < b["size"] <= 1 for b in f["bars"]) else "each bar's size is a share of the tallest, from 0 to 1"


# Checks across a scene's fields, after each field is parsed.
CHECKS: dict[str, Callable[[Mapping[str, Any]], str]] = {"chart": _chart, "clipping": _clipping, "map": _map, "bars": _bars}


def files(value: Any) -> list[str]:
    """Every ``src`` in a scene's fields, nested ones included (before/after panels)."""
    if isinstance(value, Mapping):
        return [v for k, v in value.items() if k == "src" and v] + [f for v in value.values() for f in files(v)]
    if isinstance(value, tuple):
        return [f for v in value for f in files(v)]
    return []


def _scene(n: int, raw: Any) -> Scene:
    where = f"scene {n + 1}"
    if not isinstance(raw, dict):
        raise StoryboardError(f"{where} must be an object")
    kind = raw.get("type")
    if kind not in SCHEMA:
        raise StoryboardError(f"{where}: type must be one of {', '.join(SCHEMA)}")
    unknown = set(raw) - set(SCHEMA[kind]) - COMMON
    if unknown:
        raise StoryboardError(f"{where} ({kind}): unknown key {min(unknown)!r}")
    marked = _text(True)(f"{where}.say", raw.get("say", MISSING))
    if marked.count("*") % 2:
        raise StoryboardError(f"{where}.say: an *emphasis* is not closed")
    wrong = direction.problems(marked)
    if wrong:
        raise StoryboardError(f"{where}.say: {wrong[0]}")
    say = marked.replace("*", "")
    if not sentences(direction.strip(say)):
        raise StoryboardError(f"{where}.say has nothing to say")
    motion = {}
    for key, options in MOTION.items():
        value = raw.get(key, "")
        if value and value not in options:
            raise StoryboardError(f"{where}.{key} must be one of {', '.join(options)}")
        motion[key] = value or ""
    fields = {key: parse(f"{where}.{key}", raw.get(key, MISSING)) for key, parse in SCHEMA[kind].items()}
    problem = CHECKS.get(kind, lambda _f: "")(fields)
    if problem:
        raise StoryboardError(f"{where} ({kind}): {problem}")
    emoji = _text(False)(f"{where}.emoji", raw.get("emoji", MISSING))
    if len(emoji) > 8:
        raise StoryboardError(f"{where}.emoji is one emoji, not text")
    return Scene(kind, say, marked, MappingProxyType(fields), motion["enter"], motion["exit"], emoji,
                 motion["transition"])


def parse(raw: Any, folder: Path) -> Storyboard:
    if not isinstance(raw, dict) or not isinstance(raw.get("scenes"), list) or not raw["scenes"]:
        raise StoryboardError('A storyboard is {"title": ..., "scenes": [...]} with at least one scene')
    if len(raw["scenes"]) > MAX_SCENES:
        raise StoryboardError(f"At most {MAX_SCENES} scenes")
    unknown = set(raw) - {"title", "scenes", "profile", "music"}
    if unknown:
        raise StoryboardError(f"unknown key {min(unknown)!r} in the storyboard")
    scenes = tuple(_scene(n, s) for n, s in enumerate(raw["scenes"]))
    for n, scene in enumerate(scenes):
        component = scene.fields.get("component", "") if scene.type == "custom" else ""
        if component and (not component.endswith(".tsx") or not (folder / component).is_file()):
            raise StoryboardError(f"scene {n + 1}: component {folder / component} not found (a .tsx file)")
        for src in files(scene.fields):
            if src.startswith(STOCK):
                if scene.type != "image" or not 2 <= len(src) - len(STOCK) <= 80:
                    raise StoryboardError(f"scene {n + 1}: stock: is for image scenes, 2–80 characters of what to show")
            elif not src.startswith("https://") and not (folder / src).is_file():
                raise StoryboardError(f"scene {n + 1}: {folder / src} not found")
    return Storyboard(_text(False)("title", raw.get("title", MISSING)), scenes, folder,
                      _text(False)("profile", raw.get("profile", MISSING)), _text(False)("music", raw.get("music", MISSING)))


def load(path: Path) -> Storyboard:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoryboardError(f"Could not read {path}: {exc}") from None
    return parse(raw, path.parent)
