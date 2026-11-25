"""The edit plan: what the editor (Claude) decides about your talk, by sentence and word number, never by
time. Checked here (``check``), so a plan that would break the video goes back with a list of problems.

    {
      "title": "SIP won't make you rich",           # the headline card for the hook (3–8 words)
      "subtitle": "",                               # only when the style has title.subtitle
      "drop": [{"s": 4, "why": "repeats S6"}],      # sentences cut (retakes are found by code as well)
      "keep": [7],                                  # sentences code took for retakes that are not (overrules it)
      "trim": [{"s": 1, "from": 3, "to": 12}],      # keep only these words of a sentence (warm-up, trailing "so...")
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
        {"kind": "hide", "at": "S2.1", "to": "S2.9", "box": [0.1, 0.55, 0.5, 0.2]}       # blur x, y, w, h (0–1)
      ],
      "music": "calm focused lofi",                 # mood words for the bed ("" = none)
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

from .cuts import CutList
if TYPE_CHECKING:
    from .style import Style
from .words import Sentence

KINDS = ("stat", "headline", "list", "quote", "chapter", "emoji", "lower_third", "screenshot", "image",
         "cutaway", "split", "pop", "hide")
ANCHOR = re.compile(r"^S(\d+)\.(\d+)$")
TEXT_MAX = {"pop": 24, "stat": 28, "headline": 90, "chapter": 40, "lower_third": 40, "quote": 160, "list": 34, "caption": 60}
CARD_KINDS = {"stat", "headline", "list", "quote", "lower_third", "chapter"}  # captions step aside while one shows
FULL_KINDS = {"cutaway", "image", "screenshot"}  # cover the picture; captions stay
SPLIT_KINDS = {"split"}  # the top half shows the picture, your face moves to the bottom half
BROLL_KINDS = FULL_KINDS | SPLIT_KINDS
FILE_OR_QUERY = {"cutaway", "split"}
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
    keep: set[int] = field(default_factory=set)
    punch: list[tuple[int, int]] = field(default_factory=list)
    graphics: list[dict[str, Any]] = field(default_factory=list)
    music: str = ""
    notes: str = ""

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
        for at in raw.get("punch") or []:
            plan.punch.append(_anchor(str(at)))
        plan.graphics = [dict(g) for g in raw.get("graphics") or [] if isinstance(g, dict)]
        return plan

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "subtitle": self.subtitle,
                "drop": [{"s": k, "why": v} for k, v in sorted(self.drop.items())],
                "trim": [{"s": k, "from": a, "to": b} for k, (a, b) in sorted(self.trim.items())], "keep": sorted(self.keep),
                "punch": [f"S{s}.{w}" for s, w in self.punch], "graphics": self.graphics, "music": self.music,
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
        placed.append(Graphic(kind, start, max(end, start + 0.5), g))
    return placed


def _texts(g: dict[str, Any]) -> list[tuple[str, str]]:
    out = [(key, str(g[key])) for key in ("text", "sub", "caption", "source", "by") if g.get(key)]
    out += [("item", str(x)) for x in g.get("items") or []]
    return out


def check(plan: Plan, found: list[Sentence], cut: CutList, look: Style, evidence: str = "") -> list[str]:
    """Problems with a plan, for the editor to fix; [] = ready to render."""
    problems = []
    ids = {s.id for s in found}
    for sid in list(plan.drop) + list(plan.trim) + list(plan.keep) + [s for s, _ in plan.punch]:
        if sid not in ids:
            problems.append(f"S{sid} does not exist (S1–S{max(ids) if ids else 0})")
    for sid, (a, b) in plan.trim.items():
        size = len(next((s.words for s in found if s.id == sid), ()))
        if size and not 1 <= a <= b <= size:
            problems.append(f"trim S{sid}: from {a} to {b} must be inside its {size} words")
    if found and len(plan.drop) > 0.7 * len(found):
        problems.append(f"{len(plan.drop)} of {len(found)} sentences dropped: the talk is yours, cut only what fails")
    title_words = len(plan.title.replace("*", " ").split())
    starred = plan.title.count("*")
    if starred and (starred % 2 or look["title"]["accent"] == "none" or starred > 4):
        problems.append("title: mark at most two stretches with *stars*, in pairs, and only when the style's title has an accent")
    if look["title"]["kind"] != "none" and not 2 <= title_words <= 9:
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
                "image": ["file"], "screenshot": ["file"]}[g.kind]
        problems += [f"{where}: needs '{k}'" for k in need if not raw.get(k)]
        if g.kind in FILE_OR_QUERY and not (raw.get("query") or raw.get("file")):
            problems.append(f"{where}: needs 'query' (stock footage to find) or 'file' (one of the job's assets)")
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
        same_place = (a.kind in CARD_KINDS and b.kind in CARD_KINDS) or (a.kind in BROLL_KINDS and b.kind in BROLL_KINDS) \
            or (a.kind == b.kind == "pop")
        if same_place and b.start < a.end + MIN_GAP:
            problems.append(f"{a.kind} at {a.data.get('at')} and {b.kind} at {b.data.get('at')} overlap: move one or add 'to'")
    covered = sum(min(g.end, g.start + 20) - g.start for g in placed if g.kind in FULL_KINDS) \
        + 0.5 * sum(min(g.end, g.start + 20) - g.start for g in placed if g.kind in SPLIT_KINDS)
    if cut.seconds and covered > look["pace"]["broll"] * cut.seconds + 1:
        problems.append(f"cutaways cover {covered:.0f} s of {cut.seconds:.0f} s; this style allows about "
                        f"{look['pace']['broll'] * 100:.0f}% (a split counts half)")
    kept = [g for g in placed if not cut.ranges or _kept(cut, g.start)]
    if cut.seconds > 25 and look["pace"]["broll"] >= 0.15 and not any(g.kind in BROLL_KINDS for g in kept) \
            and BROLL_KINDS & allowed:
        problems.append(f"{cut.seconds:.0f} s of face with no b-roll: add at least one cutaway or split where the words "
                        "describe something seeable (or an image/screenshot)")
    if cut.ranges:
        problems += _quiet(plan, kept, found, cut, look)
    return problems


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
            problems.append(f"nothing new on screen from {a:.0f} s to {b:.0f} s of the edit ({_said_at(found, cut, a)}): "
                            f"this style wants a change about every {look['pace']['change_every']} s; add a pop, card, "
                            "split, cutaway or punch-in there, or cut the stretch")
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
