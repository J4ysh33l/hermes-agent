"""An edit style: how your own footage is cut, captioned, decorated and mixed. One YAML file per style.

Built-in styles are in ``orchestrator/edit/styles/`` (``clean``, ``zero1``, ``aevy``, ``mine``); your own go
in ``$HERMES_HOME/edit/styles/<name>.yaml`` (same name = yours wins). A style states only what differs from
the one it ``extends`` (``clean`` unless named), so ``extends: mine`` plus two colours is a whole style.

Sections (every field is documented in styles/clean.yaml):

- ``captions``  burned in by ffmpeg (libass): words on screen, case, font, colours, box, position.
- ``title``     the headline at the top for the hook: a serif card, a pill, or none.
- ``graphics``  the boxes, cards and overlays drawn by Remotion: palette, fonts, which kinds may be used,
                logo, progress bar.
- ``pace``      what is cut (pauses, fillers, retakes) and how often the picture changes (punch-ins, b-roll).
- ``grade``     colour: warmth, contrast, saturation.
- ``sound``     your voice's clean-up, music bed and sound effects.
- ``plan``      notes for the editor (Claude): hook, ending, tone, what to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

import yaml

from .plan import KINDS
from orchestrator.studio.profile import _choice, _colour, _flag, _number, _text, _texts, _use

BUILT_IN = Path(__file__).with_name("styles")
BASE = "clean"
DEFAULT = "mine"
MAX_DEPTH = 5
FONTS = ("manrope", "inter", "intertight", "montserrat", "anton", "newsreader")  # files: fonts.py


class StyleError(ValueError):
    """Shown as it is; nothing was made."""


def _colour_or_none(where: str, value: Any) -> str:
    return "none" if value in (None, "none", False) else _colour(where, value)


def _kinds(where: str, value: Any) -> tuple[str, ...]:
    kinds = _texts(where, value)
    wrong = [k for k in kinds if k not in KINDS]
    if wrong:
        raise StyleError(f"{where}: unknown kind {wrong[0]!r}; kinds: {', '.join(KINDS)}")
    return kinds


def _file(where: str, value: Any) -> str:
    return "" if value in (None, "", False) else _text(where, value)


FONT = _choice(*FONTS)

SCHEMA: dict[str, dict[str, Callable[[str, Any], Any]]] = {
    "captions": {"show": _flag, "script": _choice("latin"), "words": _number(1, 6), "case": _choice("sentence", "lower", "upper"),
                 "font": FONT, "size": _number(30, 140), "colour": _colour, "active": _colour_or_none,
                 "box": _colour_or_none, "box_opacity": _number(0, 1), "outline": _number(0, 12),
                 "shadow": _number(0, 12), "y": _number(0.3, 0.9)},
    "title": {"kind": _choice("card", "pill", "none"), "font": FONT, "bg": _colour, "fg": _colour, "size": _number(36, 110),
              "y": _number(0.03, 0.3), "seconds": _number(0, 600), "subtitle": _flag, "weight": _number(300, 900),
              "accent": _colour_or_none},
    "graphics": {"font": FONT, "serif": FONT, "ink": _colour, "paper": _colour, "accent": _colour, "alert": _colour,
                 "good": _colour, "box_bg": _colour, "box_fg": _colour, "figure": _colour_or_none, "radius": _number(0, 60),
                 "kinds": _kinds, "emoji": _flag, "logo": _file, "logo_pos": _choice("top-right", "top-left", "none"),
                 "progress": _flag},
    "pace": {"max_pause": _number(0.05, 2.0), "pad": _number(0.0, 0.3), "fillers": _choice("keep", "alone", "all"),
             "retakes": _flag, "punch_every": _number(0, 60), "punch": _number(1.0, 1.5),
             "punch_ease": _choice("cut", "smooth"), "change_every": _number(0.5, 20), "broll": _number(0, 0.8)},
    "grade": {"warmth": _number(-1, 1), "contrast": _number(0.7, 1.4), "saturation": _number(0, 2),
              "brightness": _number(-0.2, 0.2), "sharpen": _number(0, 1.5)},
    "sound": {"denoise": _choice("off", "light", "strong"), "deess": _flag, "music": _use, "music_query": _text, "sfx": _use},
    "plan": {"hook": _text, "ending": _text, "tone": _text, "avoid": _texts, "language": _choice("hinglish", "en", "hi")},
}


@dataclass(frozen=True)
class Style:
    name: str
    description: str
    sections: Mapping[str, Mapping[str, Any]]

    def __getitem__(self, key: str) -> Mapping[str, Any]:
        return self.sections[key]

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, **{key: dict(value) for key, value in self.sections.items()}}


def folders(home: Path) -> tuple[Path, Path]:
    return home / "edit" / "styles", BUILT_IN


def names(home: Path) -> list[str]:
    return sorted({p.stem for f in folders(home) if f.is_dir() for p in f.glob("*.yaml")})


def _find(name: str, home: Path) -> Path:
    from orchestrator.studio.profile import NAME
    if not NAME.match(name):
        raise StyleError(f"Style names are lowercase letters, digits, - and _: {name!r}")
    for folder in folders(home):
        if (folder / f"{name}.yaml").is_file():
            return folder / f"{name}.yaml"
    raise StyleError(f"No style {name!r}. Styles: {', '.join(names(home))}")


def _raw(name: str, home: Path, depth: int = 0) -> dict[str, Any]:
    if depth > MAX_DEPTH:
        raise StyleError(f"Style {name!r}: 'extends' goes more than {MAX_DEPTH} deep (a loop?)")
    path = _find(name, home)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise StyleError(f"Could not read {path}: {exc}") from None
    if not isinstance(raw, dict):
        raise StyleError(f"{path} must be a mapping")
    unknown = set(raw) - set(SCHEMA) - {"extends", "description"}
    if unknown:
        raise StyleError(f"{path}: unknown section {min(unknown)!r} (sections: {', '.join(SCHEMA)})")
    parent = raw.get("extends", "" if name == BASE else BASE)
    merged: dict[str, Any] = _raw(str(parent), home, depth + 1) if parent else {key: {} for key in SCHEMA}
    for key in SCHEMA:
        section = raw.get(key) or {}
        if not isinstance(section, dict):
            raise StyleError(f"{path}: {key} must be a mapping")
        merged[key] = {**merged[key], **section}
    merged["description"] = raw.get("description", "")
    return merged


def load(name: str, home: Path) -> Style:
    raw = _raw(name, home)
    sections = {}
    for key, fields in SCHEMA.items():
        given = raw[key]
        unknown = set(given) - set(fields)
        if unknown:
            raise StyleError(f"style {name}: unknown key {key}.{min(unknown)}")
        missing = set(fields) - set(given)
        if missing:
            raise StyleError(f"style {name}: {key}.{min(missing)} has no value (clean sets them all)")
        try:
            sections[key] = MappingProxyType({f: parse(f"style {name}: {key}.{f}", given[f]) for f, parse in fields.items()})
        except ValueError as exc:  # ProfileError from the shared field parsers
            raise StyleError(str(exc)) from None
    return Style(name, str(raw["description"]), MappingProxyType(sections))


def create(name: str, home: Path, base: str = DEFAULT, force: bool = False) -> Path:
    """A new style of yours that extends ``base``: the file to edit, with the fields worth changing."""
    from orchestrator.studio.profile import NAME
    if not NAME.match(name):
        raise StyleError(f"Style names are lowercase letters, digits, - and _: {name!r}")
    load(base, home)
    folder = folders(home)[0]
    path = folder / f"{name}.yaml"
    if path.exists() and not force:
        raise StyleError(f"{path} exists already")
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.format(name=name, base=base), encoding="utf-8")
    load(name, home)
    return path


def summary(look: Style) -> str:
    c, t, p, g = look["captions"], look["title"], look["pace"], look["graphics"]
    words = f"{c['words']} word{'s' if c['words'] != 1 else ''}"
    return (f"{look.name}: {look.description}\n"
            f"  captions {words}, {c['case']} case, {c['font']}, at {round(c['y'] * 100)}% height · title {t['kind']}"
            f" ({t['font']}) · pauses over {p['max_pause']} s cut · punch-in every {p['punch_every']} s ×{p['punch']}"
            f" · something new every ~{p['change_every']} s · graphics: {', '.join(g['kinds'])}")


TEMPLATE = """# Your style. It starts as '{base}' and only states what differs; every field: orchestrator/edit/styles/clean.yaml
extends: {base}
description: My style.

# captions:
#   colour: "#FFFFFF"
#   active: "#FFD400"        # the word being said; none = no highlight
# graphics:
#   accent: "#FFD400"
#   logo: logo.png           # in $HERMES_HOME/edit/brand/
# pace:
#   punch_every: 10
"""
