"""The edit plan: what the editor (Claude) decides about your talk, by sentence and word number, never by
time. Checked here (``check``), so a plan that would break the video goes back with a list of problems.

    {
      "title": "SIP won't make you rich",           # the headline card for the hook (3–8 words)
      "subtitle": "",                               # only when the style has title.subtitle
      "drop": [{"s": 4, "why": "repeats S6"}],      # sentences cut (retakes are found by code as well)
      "keep": [7],                                  # sentences code took for retakes that are not (overrules it)
      "trim": [{"s": 1, "from": 3, "to": 12}],      # keep only these words of a sentence (warm-up, trailing "so...")
      "cut": [{"s": 9, "from": 9, "to": 19}],       # cut these words from inside a sentence (a repeat, a detour)
      "punch": ["S3.5", "S7.1"],                    # punch-ins (word where the zoom jumps in); [] = by the style's rhythm
      "graphics": [
        {"kind": "stat", "at": "S3.4", "text": "10× practice", "sub": "beats 1 more mock"},
        {"kind": "headline", "at": "S5.1", "text": "YES Bank tumbles 34%", "source": "Economic Times"},
        {"kind": "list", "at": "S8.1", "to": "S10.9", "items": ["Pick weakest section", "One timed set daily"]},
        {"kind": "chapter", "at": "S12.1", "n": 2, "text": "How to review"},
        {"kind": "lower_third", "at": "S1.1", "text": "Your Name", "sub": "CAT 99.8 %ile"},
        {"kind": "emoji", "at": "S6.3", "emoji": "🔥"},
        {"kind": "quote", "at": "S9.1", "text": "...", "by": "..."},
        {"kind": "cutaway", "at": "S4.1", "to": "S4.20", "query": "student solving maths at desk at night"},
        {"kind": "image", "at": "S11.1", "file": "chart.png", "caption": "..."},
        {"kind": "screenshot", "at": "S2.3", "file": "screen1.png"},
        {"kind": "split", "at": "S6.1", "to": "S6.14", "query": "nurse writing paper register"},   # or "file"
        {"kind": "pop", "at": "S3.2", "text": "Missed claims"},                         # a 1–3 word chip pops in
        {"kind": "hide", "at": "S2.1", "to": "S2.9", "box": [0.1, 0.55, 0.5, 0.2]},      # blur x, y, w, h (0–1)
        # explainer scenes: "layout" panel (top half, face below) | full (whole frame) | top (big type over the
        # wall above your head); "at"/"to" = the scene's span; each element's "at" (and "strike_at"...) is the
        # word it arrives on, inside that span
        {"kind": "scene", "type": "counter", "layout": "top", "at": "S1.1", "to": "S1.23", "count_from": 69,
         "number": 70, "suffix": "%", "label": "of healthcare payments", "sub": "out of pocket", "tone": "problem"},
        {"kind": "scene", "type": "stack", "layout": "panel", "at": "S1.17", "to": "S3.7", "kicker": "who pays?", "tone": "problem",
         "rows": [{"text": "No insurance cover", "icon": "insurance", "mark": "cross", "at": "S1.19"},
                  {"text": "Paid by the patient", "icon": "wallet", "at": "S3.4"}]},
        {"kind": "scene", "type": "points", "layout": "full", "at": "S6.1", "to": "S8.14", "kicker": "the usual answer",
         "title": "Fix insurance?", "items": [{"text": "More insurance", "at": "S6.20"}], "strike_at": "S8.4"},
        {"kind": "scene", "type": "statement", "layout": "panel", "at": "S9.1", "to": "S10.16", "text": "prevention",
         "tone": "solution", "kicker": "the best way", "sub": "catch it at stage one", "underline_at": "S9.21"},
        {"kind": "scene", "type": "bars", "layout": "full", "at": "S13.1", "to": "S14.5", "title": "Screen early. Save big.",
         "bars": [{"label": "Screening", "value": "₹1,000", "size": 0.05, "tone": "solution", "at": "S13.2"},
                  {"label": "Treatment", "value": "₹ lakhs", "size": 1, "tone": "problem", "at": "S14.4"}]},
        {"kind": "scene", "type": "steps", "layout": "panel", "at": "S5.1", "to": "S7.9",
         "steps": [{"label": "rates & doctors", "icon": "clipboard", "at": "S5.3"}, {"label": "train staff", "icon": "training",
                    "sub": "their own language", "at": "S6.2"}]},
        {"kind": "scene", "type": "compare", "layout": "panel", "at": "S8.1", "to": "S9.6", "title": "the real cost",
         "left": {"text": "the license"}, "right": {"text": "the disruption"}, "heavy": "right",
         "strike": "left", "strike_at": "S9.2"},
        {"kind": "scene", "type": "badge", "layout": "panel", "at": "S4.1", "icon": "hospital", "text": "OPD open, every day",
         "badge": "0 days down"}
      ],
      "emphasis": {"problem": ["S1.11"], "solution": ["S9.21"]},  # caption words in the problem/solution colour
      "end": {"cta": "Follow for more on fixing Indian healthcare", "seconds": 2.5},  # an end card after the last word
      "music": "calm focused lofi",                 # mood words for the bed ("" = none)
      "grade": {"brightness": 0.04, "sharpen": 0.3}, # optional: on top of the style's grade, for this footage
      "notes": "what you should know"               # goes to you with the preview
    }

``at``/``to`` are ``S<sentence>.<word>``, words counted from 1. Without ``to`` a graphic lasts to the end of
its sentence (cards), 1.2 s (emoji, pop) or 2 s (chapter). A cutaway or split may name ``file`` (the
creator's own footage or screen recording in the job's assets/) instead of a stock ``query``. Numbers on screen must be ones you said (or wrote in
the job's notes): the editor never invents a figure.
"""

from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from orchestrator.studio import storyboard

from .cuts import CutList
if TYPE_CHECKING:
    from .style import Style
from .words import Sentence

KINDS = ("stat", "headline", "list", "quote", "chapter", "emoji", "lower_third", "screenshot", "image",
         "cutaway", "split", "pop", "hide", "scene")
# Explainer scenes (remotion/src/edit/Scenes.tsx): type → the fields it needs
SCENES = {"statement": ("text|lines",), "counter": ("number", "label"), "stack": ("rows",), "steps": ("steps",),
          "compare": ("left", "right", "heavy"), "bars": ("bars",), "points": ("title", "items"), "badge": ("icon", "text"),
          "library": ("scene",)}
# The faceless library's scenes an edit may use full-frame (type "library"); not those that need files.
LIBRARY = ("chart", "timeline", "quote", "clipping", "diagram", "map", "post", "compare", "stat", "bullets", "title")
LAYOUTS = ("panel", "full", "top")  # top half (face below) · whole frame · big type above your head
ICONS = ("hospital", "stethoscope", "pill", "syringe", "heart-pulse", "activity", "ambulance", "bed", "clipboard",
         "clipboard-check", "file", "receipt", "wallet", "rupee", "piggy-bank", "shield", "shield-check", "user", "users",
         "calendar", "clock", "alert", "cross", "check", "trending-up", "trending-down", "chart", "database", "phone",
         "monitor", "laptop", "offline", "languages", "training", "building", "home", "pin", "call", "search", "idea",
         "target", "zap", "lock", "scale", "rocket", "sparkles", "microscope", "test", "scan", "brain", "care", "cash",
         "government", "insurance", "timer", "hourglass", "settings", "wrench", "chat", "mic", "camera", "arrow", "ban",
         "hand", "eye", "heart", "baby", "leaf", "apple", "fitness", "coins", "card", "file-x", "calendar-x", "user-x",
         "sad", "happy", "thumbs-up", "globe", "truck", "package", "printer", "chip", "bot", "cloud", "sync", "layers",
         "dashboard", "checklist", "siren", "blood", "fever", "bandage", "plus")
LONGEST_SCENE = 25.0
ANCHOR = re.compile(r"^S(\d+)\.(\d+)$")
TEXT_MAX = {"pop": 24, "stat": 28, "headline": 90, "chapter": 40, "lower_third": 40, "quote": 160, "list": 34, "caption": 60}
CARD_KINDS = {"stat", "headline", "list", "quote", "lower_third", "chapter"}  # captions step aside while one shows
FULL_KINDS = {"cutaway", "image", "screenshot"}  # cover the picture; captions stay (and full-layout scenes)
SPLIT_KINDS = {"split"}  # the top half shows the picture, your face moves to the bottom half
BROLL_KINDS = FULL_KINDS | SPLIT_KINDS
FILE_OR_QUERY = {"cutaway", "split"}
GRADE = {"brightness": (-0.1, 0.1), "contrast": (-0.15, 0.15), "saturation": (-0.3, 0.3), "warmth": (-0.5, 0.5),
         "sharpen": (0.0, 0.8)}  # what the editor may add to the style's grade for one video
QUIET_MAX = 2.6  # × pace.change_every: the longest stretch with nothing new on screen
LONGEST_CARD = 7.0
MIN_GAP = 0.4  # between two graphics in the same place
NUMBER = re.compile(r"\d[\d,.]*")


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class Graphic:
    kind: str
    start: float  # source time (the edit maps it to output)
    end: float
    data: dict[str, Any]


@dataclass
class Plan:
    title: str = ""
    subtitle: str = ""
    drop: dict[int, str] = field(default_factory=dict)
    trim: dict[int, tuple[int, int]] = field(default_factory=dict)
    cut: dict[int, list[tuple[int, int]]] = field(default_factory=dict)  # words cut from inside a sentence
    keep: set[int] = field(default_factory=set)
    punch: list[tuple[int, int]] = field(default_factory=list)
    graphics: list[dict[str, Any]] = field(default_factory=list)
    music: str = ""
    notes: str = ""
    grade: dict[str, float] = field(default_factory=dict)
    end: dict[str, Any] = field(default_factory=dict)  # {"cta": ..., "seconds": 2.5}: an end card after the last word
    emphasis: dict[str, list[tuple[int, int]]] = field(default_factory=dict)  # problem/solution → caption words

    @classmethod
    def parse(cls, raw: Any) -> Plan:
        if not isinstance(raw, dict):
            raise PlanError("the plan must be a JSON object")
        plan = cls(title=str(raw.get("title", "")).strip(), subtitle=str(raw.get("subtitle", "")).strip(),
                   music=str(raw.get("music", "")).strip(), notes=str(raw.get("notes", "")).strip())
        for item in raw.get("drop") or []:
            plan.drop[int(item["s"])] = str(item.get("why", "editor"))
        plan.keep = {int(x) for x in raw.get("keep") or []}
        for item in raw.get("trim") or []:
            plan.trim[int(item["s"])] = (int(item["from"]), int(item["to"]))
        for item in raw.get("cut") or []:
            plan.cut.setdefault(int(item["s"]), []).append((int(item["from"]), int(item["to"])))
        for at in raw.get("punch") or []:
            plan.punch.append(_anchor(str(at)))
        plan.graphics = [dict(g) for g in raw.get("graphics") or [] if isinstance(g, dict)]
        grade = raw.get("grade") or {}
        if not isinstance(grade, dict):
            raise PlanError("grade must be an object like {\"brightness\": 0.04}")
        plan.grade = {str(k): float(v) for k, v in grade.items()}
        end = raw.get("end") or {}
        if not isinstance(end, dict):
            raise PlanError("end must be an object like {\"cta\": \"Follow for more\", \"seconds\": 2.5}")
        plan.end = dict(end)
        emphasis = raw.get("emphasis") or {}
        if not isinstance(emphasis, dict):
            raise PlanError("emphasis must be an object like {\"problem\": [\"S1.4\"], \"solution\": [\"S9.21\"]}")
        plan.emphasis = {str(k): [_anchor(str(a)) for a in v or []] for k, v in emphasis.items()}
        return plan

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "subtitle": self.subtitle,
                "drop": [{"s": k, "why": v} for k, v in sorted(self.drop.items())],
                "trim": [{"s": k, "from": a, "to": b} for k, (a, b) in sorted(self.trim.items())], "keep": sorted(self.keep),
                "cut": [{"s": k, "from": a, "to": b} for k, v in sorted(self.cut.items()) for a, b in v],
                "punch": [f"S{s}.{w}" for s, w in self.punch], "graphics": self.graphics, "music": self.music, "grade": self.grade, "end": self.end,
                "emphasis": {k: [f"S{s}.{w}" for s, w in v] for k, v in self.emphasis.items()},
                "notes": self.notes}


def _anchor(text: str) -> tuple[int, int]:
    found = ANCHOR.match(text.strip())
    if not found:
        raise PlanError(f"{text!r} is not an anchor like S3.5 (sentence 3, word 5)")
    return int(found.group(1)), int(found.group(2))


def load(text: str) -> Plan:
    try:
        return Plan.parse(json.loads(text))
    except (ValueError, KeyError, TypeError) as exc:
        raise PlanError(f"plan.json: {exc}") from None


def _time(found: dict[int, Sentence], anchor: tuple[int, int], edge: str) -> float:
    s, w = anchor
    if s not in found:
        raise PlanError(f"S{s} does not exist (S1–S{max(found)})")
    words = found[s].words
    if not 1 <= w <= len(words):
        raise PlanError(f"S{s} has {len(words)} words, so S{s}.{w} does not exist")
    return words[w - 1].start if edge == "start" else words[w - 1].end


def place(plan: Plan, found_list: list[Sentence]) -> list[Graphic]:
    """Each graphic's source start and end (raises PlanError on a bad anchor)."""
    found = {s.id: s for s in found_list}
    placed = []
    for n, g in enumerate(plan.graphics, 1):
        kind = str(g.get("kind", ""))
        if "at" not in g:
            raise PlanError(f"graphic {n} ({kind}) has no 'at'")
        start_anchor = _anchor(str(g["at"]))
        start = _time(found, start_anchor, "start")
        if "to" in g:
            end = _time(found, _anchor(str(g["to"])), "end")
        elif kind in ("emoji", "pop"):
            end = start + 1.2
        elif kind == "chapter":
            end = start + 2.0
        else:
            end = found[start_anchor[0]].end
        if kind in CARD_KINDS:
            end = min(max(end, start + 1.5), start + LONGEST_CARD)
        if kind == "scene":
            end = min(max(end, start + 1.5), start + LONGEST_SCENE)
        placed.append(Graphic(kind, start, max(end, start + 0.5), g))
    return placed


SCENE_TEXT = {"text": 40, "title": 40, "kicker": 50, "sub": 60, "label": 50, "badge": 30, "value": 16, "cta": 60}


def _texts(g: dict[str, Any]) -> list[tuple[str, str]]:
    if g.get("kind") == "scene":
        return list(_walk_texts(g))
    out = [(key, str(g[key])) for key in ("text", "sub", "caption", "source", "by") if g.get(key)]
    out += [("item", str(x)) for x in g.get("items") or []]
    return out


def _walk_texts(value: Any, key: str = "") -> Any:
    """Every piece of text in a scene, with the key it sits under (text, label, ...)."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k not in ("kind", "type", "layout", "tone", "icon", "mark", "heavy", "strike", "at", "to", "scene", "beats") \
                    and not k.endswith("_at"):
                yield from _walk_texts(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_texts(v, key)
    elif isinstance(value, str) and value.strip():
        yield key or "text", value


def scene_anchors(g: dict[str, Any], top: bool = True) -> list[tuple[str, str]]:
    """The word anchors inside a scene (an element's "at", any "*_at"), with where they sit; not the scene's own."""
    out = []
    for k, v in g.items():
        if isinstance(v, str) and ((k == "at" and not top) or k.endswith("_at")):
            out.append((k, v))
        elif isinstance(v, dict):
            out += [(f"{k}.{a}", b) for a, b in scene_anchors(v, False)]
        elif isinstance(v, list):
            for n, x in enumerate(v):
                if isinstance(x, dict):
                    out += [(f"{k}[{n}].{a}", b) for a, b in scene_anchors(x, False)]
    return out


def _library_problems(where: str, raw: dict[str, Any]) -> list[str]:
    inner = raw.get("scene")
    if raw.get("layout", "panel") != "full":
        return [f"{where}: a library scene fills the frame: layout must be full"]
    if not isinstance(inner, dict) or inner.get("type") not in LIBRARY:
        return [f"{where}: scene must be one of the library's ({', '.join(LIBRARY)}) as {{\"type\": \"chart\", ...}}"]
    try:
        storyboard.library_scene(f"{where}.scene", inner)
    except storyboard.StoryboardError as exc:
        return [str(exc)]
    beats = raw.get("beats") or []
    if not isinstance(beats, list) or not all(isinstance(b, dict) and isinstance(b.get("at"), str) for b in beats):
        return [f'{where}: beats is a list of {{"at": "S4.2"}}, one per part (bar, event, node) as it is said']
    return []


def _scene_problems(where: str, raw: dict[str, Any], g: Graphic, found: dict[int, Sentence]) -> list[str]:
    problems = []
    kind = raw.get("type")
    if kind not in SCENES:
        return [f"{where}: scene type must be one of {', '.join(SCENES)}"]
    if raw.get("layout", "panel") not in LAYOUTS:
        problems.append(f"{where}: layout must be one of {', '.join(LAYOUTS)}")
    for need in SCENES[kind]:
        if not any(raw.get(k) for k in need.split("|")):
            problems.append(f"{where}: a {kind} scene needs '{need.replace('|', '' + chr(39) + ' or ' + chr(39))}'")
    for k, text in _walk_texts(raw):
        limit = SCENE_TEXT.get(k, 40)
        if len(text) > limit:
            problems.append(f"{where}: {k} {text[:20]!r}... is {len(text)} characters (at most {limit})")
    icons = [raw.get("icon")] + [x.get("icon") for key in ("rows", "steps") for x in raw.get(key) or [] if isinstance(x, dict)]
    problems += [f"{where}: unknown icon {i!r} (icons: {', '.join(ICONS)})" for i in icons if i and i not in ICONS]
    for path, anchor in scene_anchors(raw):
        try:
            t = _time(found, _anchor(anchor), "start")
        except PlanError as exc:
            problems.append(f"{where}: {path}: {exc}")
            continue
        if not g.start - 0.05 <= t <= g.end + 0.05:
            problems.append(f"{where}: {path} {anchor} is outside the scene ({raw.get('at')} to its end); extend 'to' or move it")
    if kind == "library":
        problems += _library_problems(where, raw)
    if kind == "counter" and not isinstance(raw.get("number"), (int, float)):
        problems.append(f"{where}: counter 'number' must be a number")
    if kind in ("stack", "steps", "bars", "points"):
        size = len(raw.get({"stack": "rows", "steps": "steps", "bars": "bars", "points": "items"}[kind]) or [])
        if not 2 <= size <= {"stack": 4, "steps": 5, "bars": 3, "points": 4}[kind]:
            problems.append(f"{where}: a {kind} scene has 2–{ {'stack': 4, 'steps': 5, 'bars': 3, 'points': 4}[kind]} entries")
    return problems


def check(plan: Plan, found: list[Sentence], cut: CutList, look: Style, evidence: str = "") -> list[str]:
    """Problems with a plan, for the editor to fix; [] = ready to render."""
    problems = []
    ids = {s.id for s in found}
    for sid in list(plan.drop) + list(plan.trim) + list(plan.keep) + [s for s, _ in plan.punch]:
        if sid not in ids:
            problems.append(f"S{sid} does not exist (S1–S{max(ids) if ids else 0})")
    for sid, spans in plan.cut.items():
        size = len(next((s.words for s in found if s.id == sid), ()))
        for a, b in spans:
            if not size:
                problems.append(f"cut S{sid}: no such sentence")
            elif not 1 <= a <= b <= size or (a == 1 and b == size):
                problems.append(f"cut S{sid}: from {a} to {b} must be inside its {size} words (to cut it all, use drop)")
    for sid, (a, b) in plan.trim.items():
        size = len(next((s.words for s in found if s.id == sid), ()))
        if size and not 1 <= a <= b <= size:
            problems.append(f"trim S{sid}: from {a} to {b} must be inside its {size} words")
    if found and len(plan.drop) > 0.7 * len(found):
        problems.append(f"{len(plan.drop)} of {len(found)} sentences dropped: the talk is yours, cut only what fails")
    for key, value in plan.grade.items():
        if key not in GRADE:
            problems.append(f"grade: unknown {key!r}; use {', '.join(GRADE)}")
        elif not GRADE[key][0] <= value <= GRADE[key][1]:
            problems.append(f"grade: {key} must be between {GRADE[key][0]} and {GRADE[key][1]}")
    title_words = len(plan.title.replace("*", " ").split())
    starred = plan.title.count("*")
    if starred and (starred % 2 or look["title"]["accent"] == "none" or starred > 4):
        problems.append("title: mark at most two stretches with *stars*, in pairs, and only when the style's title has an accent")
    if plan.title and look["title"]["kind"] != "none" and not 2 <= title_words <= 9:
        problems.append(f"title must be 2–9 words (it is {title_words})")
    allowed = set(look["graphics"]["kinds"]) | ({"emoji"} if look["graphics"]["emoji"] else set()) | {"hide"}  # always
    said = " ".join(s.text for s in found) + " " + plan.title + " " + evidence
    known = {re.sub(r"[,.]", "", n) for n in NUMBER.findall(said)}
    try:
        placed = place(plan, found)
    except PlanError as exc:
        return problems + [str(exc)]
    for n, (g, raw) in enumerate(zip(placed, plan.graphics), 1):
        where = f"graphic {n} ({g.kind} at {raw.get('at')})"
        if g.kind not in KINDS:
            problems.append(f"{where}: unknown kind; kinds: {', '.join(KINDS)}")
            continue
        if g.kind not in allowed:
            problems.append(f"{where}: this style does not use {g.kind} (allowed: {', '.join(sorted(allowed))})")
        need = {"stat": ["text"], "headline": ["text"], "list": ["items"], "chapter": ["text"], "lower_third": ["text"],
                "emoji": ["emoji"], "quote": ["text"], "cutaway": [], "split": [], "pop": ["text"], "hide": ["box"],
                "image": ["file"], "screenshot": ["file"], "scene": ["type"]}[g.kind]
        problems += [f"{where}: needs '{k}'" for k in need if not raw.get(k)]
        if g.kind in FILE_OR_QUERY and not (raw.get("query") or raw.get("file")):
            problems.append(f"{where}: needs 'query' (stock footage to find) or 'file' (one of the job's assets)")
        if g.kind == "scene":
            problems += _scene_problems(where, raw, g, {s.id: s for s in found})
            if raw.get("type") == "counter" and isinstance(raw.get("number"), (int, float)):
                number = re.sub(r"\.0$", "", str(raw["number"]))
                if number not in known:
                    problems.append(f"{where}: {number!r} was not said in the talk or the notes: only show numbers you said")
        if g.kind == "hide" and not _box(raw.get("box")):
            problems.append(f"{where}: box must be [x, y, w, h], fractions of the frame (0–1), inside it")
        for key, text in _texts(raw):
            limit = TEXT_MAX.get("caption" if key in ("caption", "sub", "source", "by") else ("list" if key == "item" else g.kind), 90)
            if len(text) > limit:
                problems.append(f"{where}: {key} is {len(text)} characters (at most {limit} fit)")
            for number in NUMBER.findall(text):
                if re.sub(r"[,.]", "", number) not in known:
                    problems.append(f"{where}: {number!r} was not said in the talk or the notes: only show numbers you said")
        if g.kind == "list" and not 2 <= len(raw.get("items") or []) <= 5:
            problems.append(f"{where}: a list has 2–5 items")
        if cut.ranges and not _kept(cut, g.start):
            problems.append(f"{where}: it starts in a part that is cut (S{_anchor(str(raw['at']))[0]} dropped or trimmed?)")
    for a, b in zip(sorted(placed, key=lambda g: g.start), sorted(placed, key=lambda g: g.start)[1:]):
        same_place = (_place(a) == _place(b) != "")
        gap = -0.05 if a.kind == b.kind == "scene" else MIN_GAP  # one scene may hand straight to the next
        if same_place and b.start < a.end + gap:
            problems.append(f"{a.kind} at {a.data.get('at')} and {b.kind} at {b.data.get('at')} overlap: move one or add 'to'")
    out = cut.to_output if cut.ranges else (lambda x: x)  # in the edit's own time (it may play faster)
    covered = sum((out(min(g.end, g.start + 25)) - out(g.start)) * _cover(g) for g in placed)
    for kind, anchors in plan.emphasis.items():
        if kind not in ("problem", "solution"):
            problems.append(f"emphasis: use 'problem' or 'solution', not {kind!r}")
        for s, w in anchors:
            try:
                _time({x.id: x for x in found}, (s, w), "start")
            except PlanError as exc:
                problems.append(f"emphasis: {exc}")
    if plan.end:
        if len(str(plan.end.get("cta", ""))) > 60:
            problems.append("end: cta is over 60 characters")
        if not 1.0 <= float(plan.end.get("seconds", 2.5)) <= 5.0:
            problems.append("end: seconds must be 1–5")
    if cut.seconds and covered > look["pace"]["broll"] * cut.seconds + 1:
        problems.append(f"cutaways cover {covered:.0f} s of {cut.seconds:.0f} s; this style allows about "
                        f"{look['pace']['broll'] * 100:.0f}% (a split counts half)")
    return problems


def advice(plan: Plan, found: list[Sentence], cut: CutList, look: Style) -> list[str]:
    """Suggestions, not rules: the editor may ignore them (long quiet stretches are sometimes the point)."""
    try:
        placed = [g for g in place(plan, found) if not cut.ranges or _kept(cut, g.start)]
    except PlanError:
        return []
    return _quiet(plan, placed, found, cut, look) if cut.ranges else []


def _place(g: Graphic) -> str:
    """Where a graphic sits on screen; two in the same place may not overlap."""
    if g.kind == "scene":
        return "top" if g.data.get("layout") == "top" else "cover"
    if g.kind in CARD_KINDS:
        return "card"
    if g.kind in BROLL_KINDS:
        return "cover"
    return "pop" if g.kind == "pop" else ""


def _cover(g: Graphic) -> float:
    """How much of the face a graphic hides: 1 full screen, 0.5 the top half."""
    if g.kind == "scene":
        return {"full": 1.0, "panel": 0.5}.get(g.data.get("layout", "panel"), 0.0)
    return 1.0 if g.kind in FULL_KINDS else 0.5 if g.kind in SPLIT_KINDS else 0.0


def _box(value: Any) -> tuple[float, float, float, float] | None:
    """[x, y, w, h] as fractions of the frame, inside it and not a sliver; else None."""
    try:
        x, y, w, h = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if not (0 <= x < 1 and 0 <= y < 1 and 0.02 <= w and 0.02 <= h and x + w <= 1.001 and y + h <= 1.001):
        return None
    return x, y, w, h


def _quiet(plan: Plan, placed: list[Graphic], found: list[Sentence], cut: CutList, look: Style) -> list[str]:
    """Stretches of the finished video where nothing new appears (no graphic, punch-in or cut between takes)."""
    limit = max(5.0, QUIET_MAX * float(look["pace"]["change_every"]))
    events = {0.0, cut.seconds}
    events |= {cut.to_output(g.start) for g in placed if g.kind != "hide"}
    by_id = {s.id: s for s in found}
    for g in placed:  # every element arriving inside a scene is something new
        if g.kind == "scene":
            for _path, anchor in scene_anchors(g.data):
                try:
                    events.add(cut.to_output(_time(by_id, _anchor(anchor), "start")))
                except PlanError:
                    pass
    events |= {cut.to_output(g.end) for g in placed if g.kind in BROLL_KINDS}
    events |= {cut.to_output(t) for t in punch_points(plan, found, cut, look)}
    out_t = 0.0
    for a, b in zip(cut.ranges, cut.ranges[1:]):  # a jump between two takes or after a dropped line is a change
        out_t += a.end - a.start
        if b.start - a.end > 1.0:
            events.add(out_t)
    times = sorted(events)
    problems = []
    for a, b in itertools.pairwise(times):
        if b - a > limit:
            problems.append(f"nothing new on screen from {a:.0f} s to {b:.0f} s ({_said_at(found, cut, a)}); the style's "
                            f"rhythm is about every {look['pace']['change_every']} s. Fine if the face carries it; "
                            "otherwise a pop, card, b-roll or punch-in could go there")
    return problems


def _said_at(found: list[Sentence], cut: CutList, out_t: float) -> str:
    for s in found:
        if _kept(cut, s.start) and cut.to_output(s.end) > out_t + 0.2:
            return f"around S{s.id}"
    return "near the end"


def _kept(cut: CutList, t: float) -> bool:
    return any(r.start - 0.05 <= t <= r.end for r in cut.ranges)


def basic(found: list[Sentence], look: Style) -> Plan:
    """A plan without the editor: cuts and captions only, title from the first sentence."""
    first = found[0].text if found else ""
    words = re.sub(r"[^\w' %₹$-]", "", first).split()[:7]
    return Plan(title=" ".join(words) if look["title"]["kind"] != "none" and len(words) >= 2 else "",
                notes="Made without the editor: cuts, captions and punch-ins only.")


def punch_points(plan: Plan, found: list[Sentence], cut: CutList, look: Style) -> list[float]:
    """Source times where the zoom changes: the plan's, or one every ``pace.punch_every`` s of output on a
    sentence start (alternating in and out, like two cameras)."""
    by_id = {s.id: s for s in found}
    if plan.punch:
        return sorted(by_id[s].words[min(w, len(by_id[s].words)) - 1].start for s, w in plan.punch if s in by_id)
    every = float(look["pace"]["punch_every"])
    if not every:
        return []
    points, last = [], 0.0
    for s in found:
        if s.id in plan.drop or not _kept(cut, s.start):
            continue
        out = cut.to_output(s.start)
        if out - last >= every:
            points.append(s.start)
            last = out
    return points
