"""A page's profile: how its videos look, move, sound and are written. One YAML file per page.

Built-in profiles are in ``orchestrator/studio/profiles/``; your own go in
``$HERMES_HOME/studio/profiles/<name>.yaml`` (same name = yours wins). A profile only states what differs
from the one it ``extends`` (``default`` unless named), so a page can be three lines.

- ``theme``, ``motion``, ``captions`` go to the renderer (remotion/src/theme.ts has the same fields).
- ``voice`` overrides studio.engine/voice/speed/pause for this page's videos.
- ``writing`` and ``elements`` are for the script → storyboard step: format, hooks, humour, words to avoid,
  example scripts; and whether music, sound effects, b-roll and memes are off, allowed when they help
  (``auto``) or always used.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from .storyboard import ENTERS, EXITS, TRANSITIONS

BUILT_IN = Path(__file__).with_name("profiles")
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_DEPTH = 5  # extends chain


class ProfileError(ValueError):
    """Shown as it is; nothing was made."""


def _colour(where: str, value: Any) -> str:
    if not isinstance(value, str) or not COLOUR.match(value):
        raise ProfileError(f"{where} must be a colour like #ffd23f")
    return value


def _choice(*options: Any) -> Callable[[str, Any], Any]:
    def parse(where: str, value: Any) -> Any:
        if isinstance(value, bool) or value not in options:
            raise ProfileError(f"{where} must be one of {', '.join(map(str, options))}")
        return value
    return parse


def _use(where: str, value: Any) -> str:
    # YAML reads a bare `off` as false
    return _choice("off", "auto", "always")(where, "off" if value is False else value)


def _number(low: float, high: float) -> Callable[[str, Any], float]:
    def parse(where: str, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise ProfileError(f"{where} must be a number from {low} to {high}")
        return value
    return parse


def _text(where: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ProfileError(f"{where} must be text")
    return value.strip()


def _texts(where: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProfileError(f"{where} must be a list")
    return tuple(_text(f"{where}[{n}]", v) for n, v in enumerate(value))


def _flag(where: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ProfileError(f"{where} must be true or false")
    return value


FONT = _choice("inter", "intertight", "montserrat", "anton", "jetbrains")
USE = _use  # off | auto (only where it helps the video; never forced) | always

SCHEMA: dict[str, dict[str, Callable[[str, Any], Any]]] = {
    "theme": {**{key: _colour for key in ("bg", "glow", "panel", "text", "muted", "accent", "cool", "bad", "good")},
              "font": FONT, "mono": FONT, "background": _choice("glow-grid", "glow", "flat")},
    "motion": {"feel": _choice("snappy", "soft", "bouncy", "settle"),
               "enter": _choice(*ENTERS),
               "exit": _choice(*EXITS),
               "exit_frames": _number(0, 15), "punch": _number(0, 0.3), "drift": _number(0, 0.2),
               "step": _choice(0, 12, 15),
               "transition": _choice(*TRANSITIONS), "transition_frames": _number(3, 20)},
    "captions": {"words": _number(1, 6), "size": _number(48, 140), "upper": _flag, "font": FONT,
                 "stroke": _number(0, 24), "fill": _colour, "outline": _colour},
    "voice": {"engine": _choice("kokoro", "edge", "omnivoice"), "voice_en": _text, "voice_hi": _text,
              "speed": _number(0.5, 2.0), "pause": _number(0, 1.0)},
    "writing": {"format": _choice("explainer", "news", "how-it-works", "business-case", "hindi-explainer"),
                "language": _choice("en", "hi", "hinglish"), "hooks": _texts, "humour": _text, "tone": _text,
                "avoid": _texts, "examples": _texts, "seconds": _number(10, 180)},
    "elements": {"music": USE, "music_query": _text, "sfx": USE, "broll": USE, "memes": USE,
                 "scenes": _texts},
}
RENDERED = ("theme", "motion", "captions")


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    sections: Mapping[str, Mapping[str, Any]]  # SCHEMA's sections, every field filled

    def render_props(self) -> dict[str, Any]:
        """What remotion/src/theme.ts's Profile expects."""
        return {"name": self.name, **{key: dict(self.sections[key]) for key in RENDERED}}

    def section(self, key: str) -> Mapping[str, Any]:
        return self.sections[key]

    def with_theme(self, theme: Mapping[str, Any] | None) -> Profile:
        """This profile in the director's colours for one video (rules.theme_problems checked them). A glow
        not given is mixed from the new background and accent, so a light page never gets a dark glow."""
        if not theme:
            return self
        given = {k: v for k, v in theme.items() if k in SCHEMA["theme"]}
        if "bg" in given and "glow" not in given:
            given["glow"] = _mix(str(given["bg"]), str(given.get("accent", self.sections["theme"]["accent"])), 0.12)
        fields = SCHEMA["theme"]
        merged = {**self.sections["theme"], **{k: fields[k](f"theme.{k}", v) for k, v in given.items()}}
        return Profile(self.name, self.description, MappingProxyType({**self.sections, "theme": MappingProxyType(merged)}))


def _mix(a: str, b: str, share: float) -> str:
    parts = [round(int(a[i:i + 2], 16) * (1 - share) + int(b[i:i + 2], 16) * share) for i in (1, 3, 5)]
    return "#" + "".join(f"{p:02x}" for p in parts)


def _find(name: str, home: Path) -> Path:
    if not NAME.match(name):
        raise ProfileError(f"Profile names are lowercase letters, digits, - and _: {name!r}")
    for folder in (home / "studio" / "profiles", BUILT_IN):
        if (folder / f"{name}.yaml").is_file():
            return folder / f"{name}.yaml"
    known = sorted({p.stem for f in (home / "studio" / "profiles", BUILT_IN) if f.is_dir() for p in f.glob("*.yaml")})
    raise ProfileError(f"No profile {name!r}. Profiles: {', '.join(known)}")


def _raw(name: str, home: Path, depth: int = 0) -> dict[str, Any]:
    if depth > MAX_DEPTH:
        raise ProfileError(f"Profile {name!r}: 'extends' goes more than {MAX_DEPTH} deep (a loop?)")
    path = _find(name, home)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileError(f"Could not read {path}: {exc}") from None
    if not isinstance(raw, dict):
        raise ProfileError(f"{path} must be a mapping")
    unknown = set(raw) - set(SCHEMA) - {"extends", "description"}
    if unknown:
        raise ProfileError(f"{path}: unknown section {min(unknown)!r}")
    parent = raw.get("extends", "" if name == "default" else "default")
    merged: dict[str, Any] = _raw(str(parent), home, depth + 1) if parent else {key: {} for key in SCHEMA}
    for key in SCHEMA:
        section = raw.get(key) or {}
        if not isinstance(section, dict):
            raise ProfileError(f"{path}: {key} must be a mapping")
        merged[key] = {**merged[key], **section}
    merged["description"] = raw.get("description", "")
    return merged


def load(name: str, home: Path) -> Profile:
    raw = _raw(name, home)
    sections = {}
    for key, fields in SCHEMA.items():
        given = raw[key]
        unknown = set(given) - set(fields)
        if unknown:
            raise ProfileError(f"profile {name}: unknown key {key}.{min(unknown)}")
        missing = set(fields) - set(given)
        if missing:
            raise ProfileError(f"profile {name}: {key}.{min(missing)} has no value (the default profile sets all)")
        sections[key] = MappingProxyType({f: parse(f"{name}: {key}.{f}", given[f]) for f, parse in fields.items()})
    return Profile(name, str(raw["description"]), MappingProxyType(sections))
