"""The rules each of the three writing calls must pass, as plain functions over their JSON answers.

1. **Script** (``script.json``): title, 3 hooks from 3 families, the lines after the hook. Hook length,
   sentence length, the total length at the voice's pace, banned phrases, valid [directions].
2. **Direction** (``storyboard.json``): the script's words unchanged (grouped into scenes, never edited),
   every scene well formed (``storyboard.parse``), allowed types, one sentence per list part, words per
   scene, map countries, on-screen facts copied from the notes, the cover pick.
3. **Animation** (``sceneNN.tsx``): every custom scene has its component, with allowed imports and no
   banned APIs. TypeScript and a test render come after, on the server (``custom.verify``).

Standard library only (with ``direction``, ``text`` and ``storyboard``): Hermes runs these, and commits
the same files to the handoff repo (``tools/check.py``) so Claude checks its own answer before handing it in.
``Params`` carries everything a job's checks need and travels as ``rules.json`` next to the request.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import direction, storyboard
from .text import sentences, said_words, spoken

HOOKS = {
    "definition-twist": "<Name>, a <category> that <does X> <joke twist>.",
    "stake": "<Company> just <did X>, and it should scare every <role>.",
    "contrarian": "Everyone's wrong about <trend>. / Most people get <X> backwards.",
    "curiosity": "This is what happens when <event>. / Here's how <thing> works.",
    "number": "<Big number> <surprising unit>.",
    "question": "Why is <X> <surprising state>?",
    "pain-point": "If you're <situation>, stop doing this.",
    "hindi": "Kya aap jaante hain ki <fact>? / <Country> ne ye kaise kar diya?",
}
ALWAYS_AVOID = ("in this video", "welcome back", "hey guys", "hi guys", "let's dive in", "let's get started",
                "smash that like", "don't forget to subscribe")
GREETINGS = re.compile(r"^(hi|hey|hello|namaste|welcome)\b", re.IGNORECASE)
MAX_SENTENCE = 24
SCENE_WORDS = 20  # ~6 s at the default ~196 wpm
CUSTOM_WORDS = 40  # a custom scene animates through its own sentences
PART_WORDS = 16  # per list item / bar / box / event
HOOK_WORDS = 9  # the hook's first sentence (PLAYBOOK § 3: 6–9 words, the topic or claim first)
HOOK_SCENE_WORDS = 16  # the whole hook: about 5 s at ~196 wpm (a 3-second opening, then the turn)
HOOK_SENTENCES = 2
SHOW_WORDS = 12
TOLERANCE = 0.2  # the narration's length, either way
PARTS = {"bullets": "items", "terminal": "lines", "chart": "labels", "diagram": "nodes", "timeline": "events"}
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
ALIASES = {"usa": "United States of America", "us": "United States of America", "america": "United States of America",
           "uk": "United Kingdom", "britain": "United Kingdom", "uae": "United Arab Emirates",
           "russia": "Russia", "south korea": "South Korea", "korea": "South Korea"}

# Custom-scene components: what a component may import, and what is refused before it runs.
MAX_BYTES = 60_000
ALLOWED_IMPORTS = {"react", "remotion", "@remotion/transitions", "d3-geo", "topojson-client",
                   "world-atlas/countries-110m.json", "world-atlas/countries-50m.json",
                   "studio/motion", "studio/theme", "studio/types"}
BANNED = [
    (re.compile(r"\bfetch\s*\(|XMLHttpRequest|WebSocket|EventSource|navigator\.sendBeacon"), "no network"),
    (re.compile(r"\beval\s*\(|new\s+Function\s*\(|\brequire\s*\(|\bimport\s*\("), "no eval or dynamic import"),
    (re.compile(r"localStorage|sessionStorage|indexedDB|document\.cookie|window\.location|window\.open"),
     "no storage or navigation"),
    (re.compile(r"dangerouslySetInnerHTML|<script|<iframe"), "no raw HTML or scripts"),
    (re.compile(r"Math\.random|Date\.now|new\s+Date\s*\(|performance\.now"),
     "no randomness or clock: use random(seed) from remotion and the frame number"),
    (re.compile(r"setTimeout|setInterval|requestAnimationFrame"), "no timers: everything follows the frame"),
    (re.compile(r"@keyframes|\banimation\s*:|\btransition\s*:"), "no CSS animations or transitions"),
]
IMPORT = re.compile(r"""^\s*import\s[^'"]*?from\s+['"]([^'"]+)['"]|^\s*import\s+['"]([^'"]+)['"]""", re.MULTILINE)


@dataclass(frozen=True)
class Params:
    """What one job's checks need (``rules.json``)."""
    words: int  # spoken words for one hook + the body, at the page's pace
    avoid: tuple[str, ...]  # the page's banned phrases (ALWAYS_AVOID is added)
    scenes: tuple[str, ...]  # scene types this page allows ("custom" included)
    stock: bool  # image scenes may use stock photos
    notes: str  # the only source of on-screen facts
    countries: tuple[str, ...] = ()  # the map's country names; () = not checked here

    @property
    def low(self) -> int:
        return round(self.words * (1 - TOLERANCE))

    @property
    def high(self) -> int:
        return round(self.words * (1 + TOLERANCE))

    def dumps(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1)

    @classmethod
    def loads(cls, text: str) -> Params:
        raw = json.loads(text)
        return cls(int(raw["words"]), tuple(raw["avoid"]), tuple(raw["scenes"]), bool(raw["stock"]),
                   str(raw["notes"]), tuple(raw.get("countries") or ()))


# ---------------------------------------------------------------- narration


def _marks(where: str, say: str) -> list[str]:
    problems = [f"{where}: {p}" for p in direction.problems(say)]
    if say.count("*") % 2:
        problems.append(f"{where}: an *emphasis* is not closed")
    return problems


def _sentences(where: str, say: str) -> list[str]:
    return [f"{where}: a sentence has {len(s.split())} words (at most {MAX_SENTENCE}): {s[:60]!r}"
            for s in sentences(spoken(say)) if len(s.split()) > MAX_SENTENCE]


def _avoided(where: str, say: str, avoid: tuple[str, ...]) -> list[str]:
    said = spoken(say).lower()
    return [f"{where}: says {a!r}, which this page never says"
            for a in dict.fromkeys(x.lower() for x in (*avoid, *ALWAYS_AVOID) if x) if a in said]


def hook_problems(say: str) -> list[str]:
    """PLAYBOOK § 3: a 3-second opening, not an intro."""
    said = sentences(spoken(say))
    first = (said or [""])[0]
    problems = []
    if len(first.split()) > HOOK_WORDS:
        problems.append(f"first sentence has {len(first.split())} words (at most {HOOK_WORDS})")
    total = sum(len(s.split()) for s in said)
    if len(said) > HOOK_SENTENCES or total > HOOK_SCENE_WORDS:
        problems.append(f"says {len(said)} sentences, {total} words (at most {HOOK_SENTENCES} and "
                        f"{HOOK_SCENE_WORDS}: a hook is an opening, not an intro)")
    if direction.TOKEN.search((sentences(say) or [""])[0]):
        problems.append("no pause or [direction] in the first sentence: the first seconds have no dead air")
    if GREETINGS.match(first):
        problems.append("starts with a greeting; start with the topic or the claim")
    return problems


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


# ---------------------------------------------------------------- 1. the script


def check_script(raw: Any, p: Params) -> list[str]:
    """Every problem with a script.json (empty = usable)."""
    shape = '{"title": "...", "hooks": [3 × {"family": ..., "say": ...}], "lines": [{"say": ...}, ...]}'
    if not isinstance(raw, dict) or not isinstance(raw.get("hooks"), list) or not isinstance(raw.get("lines"), list):
        return [f"answer {shape} only"]
    problems = [] if 0 < len(_text(raw.get("title"))) <= 80 else ['"title" must be 1–80 characters']
    unknown = set(raw) - {"title", "hooks", "lines"}
    problems += [f"unknown key {k!r} (only title, hooks, lines)" for k in sorted(unknown)]
    hooks, lines = raw["hooks"], raw["lines"]
    if len(hooks) != 3 or not all(isinstance(h, dict) and _text(h.get("say")) for h in hooks):
        return problems + ['"hooks" must be 3 objects like {"family": "...", "say": "..."}']
    if not lines or not all(isinstance(ln, dict) and _text(ln.get("say")) for ln in lines):
        return problems + ['"lines" must be objects like {"say": "..."}, at least one']
    families = [h.get("family") for h in hooks]
    problems += [f"hook {n}: family {f!r} is not one of {', '.join(HOOKS)}"
                 for n, f in enumerate(families, 1) if f not in HOOKS]
    if len(set(families)) != 3:
        problems.append("the 3 hooks must come from 3 different families")
    for n, h in enumerate(hooks, 1):
        where = f"hook {n}"
        problems += [f"{where}: {x}" for x in hook_problems(h["say"])]
        problems += _marks(where, h["say"]) + _avoided(where, h["say"], p.avoid)
        problems += [f"{where}: unknown key {k!r}" for k in sorted(set(h) - {"family", "say"})]
    for n, line in enumerate(lines, 1):
        where = f"line {n}"
        problems += _marks(where, line["say"]) + _sentences(where, line["say"]) + _avoided(where, line["say"], p.avoid)
        show = line.get("show")
        if show is not None and (not isinstance(show, str) or len(show.split()) > SHOW_WORDS):
            problems.append(f'{where}: "show" is a picture idea of at most {SHOW_WORDS} words')
        problems += [f"{where}: unknown key {k!r}" for k in sorted(set(line) - {"say", "show"})]
    words = said_words(hooks[0]["say"]) + sum(said_words(ln["say"]) for ln in lines)
    if not p.low <= words <= p.high:
        change = (f"add about {p.words - words} words (a line or two more)" if words < p.low
                  else f"cut about {words - p.words} words")
        problems.append(f"the narration (hook 1 + lines) is {words} spoken words; it must be {p.low}–{p.high} "
                        f"(about {p.words}) to fit the length: {change}. Numbers count as said: 1887 is 3 words")
    return list(dict.fromkeys(problems))


def narration(script: dict[str, Any]) -> tuple[list[str], str]:
    """The locked words: each hook's, and the body's as one text."""
    return [h["say"] for h in script["hooks"]], " ".join(ln["say"] for ln in script["lines"])


# ---------------------------------------------------------------- 2. direction


def take_wishes(raw: Any) -> tuple[Any, list[str]]:
    """A copy without the scenes' "wish" keys (the storyboard has none) and the wishes: "type: wish"."""
    if not isinstance(raw, dict):
        return raw, []
    clean = copy.deepcopy(raw)
    scenes = list(clean.get("hooks") or []) + list(clean.get("scenes") or [])
    found = []
    for scene in scenes:
        if isinstance(scene, dict) and "wish" in scene:
            wish = " ".join(str(scene.pop("wish")).split()[:20])
            if wish:
                found.append(f"{scene.get('type', '?')}: {wish}")
    return clean, list(dict.fromkeys(found))


def _squash(text: str) -> str:
    return " ".join(text.split())


def _locked(raw: dict[str, Any], script: dict[str, Any]) -> list[str]:
    hooks, body = narration(script)
    problems = [f"hook {n}: its \"say\" must be the script's hook {n} exactly: {said!r}"
                for n, (scene, said) in enumerate(zip(raw["hooks"], hooks), 1)
                if _squash(str(scene.get("say", ""))) != _squash(said)]
    given = _squash(" ".join(str(s.get("say", "")) for s in raw["scenes"]))
    if given != _squash(body):
        mine, theirs = given.split(), _squash(body).split()
        at = next((n for n, (a, b) in enumerate(zip(mine, theirs)) if a != b), min(len(mine), len(theirs)))
        problems.append(f"the scenes' \"say\" must be the script's lines word for word, in order; they differ "
                        f"at word {at + 1}: script {' '.join(theirs[at:at + 6])!r}, yours {' '.join(mine[at:at + 6])!r}")
    return problems


def _number_in(value: Any, notes: str) -> bool:
    raw = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
    return raw.replace(",", "") in {n.replace(",", "") for n in NUMBER.findall(notes)}


def _numbers(value: Any) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [value]
    if isinstance(value, dict):
        return [n for v in value.values() for n in _numbers(v)]
    if isinstance(value, list):
        return [n for v in value for n in _numbers(v)]
    return []


def _clean(text: str) -> str:
    return re.sub(r"[^\w%₹$.,]+", " ", text.lower()).strip()


def evidence(where: str, scene: dict[str, Any], notes: str) -> list[str]:
    """On-screen facts must be copied from the notes; never invented."""
    kind, squashed = scene.get("type"), _clean(notes)
    texts = {"quote": ("text",), "clipping": ("headline",), "post": ("text",)}.get(kind, ())
    problems = [f"{where} ({kind}): its {key} is not in the notes; copy it word for word or use another scene"
                for key in texts if _clean(str(scene.get(key, ""))) not in squashed]
    numbers = [scene.get("value")] if kind == "stat" else list(scene.get("values") or []) if kind == "chart" else []
    if kind == "custom":  # data a custom scene shows; small counts (3 gears) are pictures, not claims
        numbers = [v for v in _numbers(scene.get("props")) if abs(v) >= 10]
        if isinstance(scene.get("fallback"), dict):
            problems += evidence(f"{where} fallback", scene["fallback"], notes)
    problems += [f"{where} ({kind}): the number {v} is not in the notes; use only numbers given there"
                 for v in numbers if not _number_in(v, notes)]
    return problems


def pacing(where: str, scene: dict[str, Any]) -> list[str]:
    said = sentences(spoken(scene.get("say", "")))
    problems = []
    words = sum(len(s.split()) for s in said)
    parts = len(scene.get(PARTS.get(scene.get("type"), ""), None) or [])
    if parts and len(said) < parts:
        problems.append(f"{where} ({scene['type']}): {parts} parts but {len(said)} sentences; one sentence per part")
    elif parts and len(said) > parts + 1:
        problems.append(f"{where} ({scene['type']}): {len(said)} sentences for {parts} parts; at most one intro sentence")
    limit = SCENE_WORDS + PART_WORDS * parts if parts else CUSTOM_WORDS if scene.get("type") == "custom" else SCENE_WORDS
    if words > limit:
        problems.append(f"{where}: {words} words is too long for one picture (at most {limit}); split it into scenes")
    return problems


def _structure(scenes: list[dict[str, Any]], p: Params) -> list[str]:
    """One storyboard (a hook + the body): parses, allowed types, sources, countries."""
    problems = []
    try:
        board = storyboard.parse({"scenes": scenes}, Path("/nonexistent"))
    except storyboard.StoryboardError as exc:
        return [str(exc)]
    problems += [f"scene {n}: type {s.type!r} is not allowed on this page (allowed: {', '.join(p.scenes)})"
                 for n, s in enumerate(board.scenes, 1) if s.type not in p.scenes]
    for n, scene in enumerate(board.scenes, 1):
        srcs = storyboard.files(scene.fields)
        if any(not (p.stock and src.startswith(storyboard.STOCK)) for src in srcs):
            problems.append(f'scene {n}: no "src" but "stock:..." on image scenes' if p.stock
                            else f'scene {n}: no "src": this page has no images')
        if scene.type == "custom" and scene.fields["component"]:
            problems.append(f'scene {n}: no "component" (the animator names it)')
    if p.countries:
        known = {c.lower() for c in p.countries}
        for n, scene in enumerate(board.scenes, 1):
            for name in storyboard.countries(scene.fields) if scene.type == "map" else ():
                if ALIASES.get(name.lower(), name).lower() not in known:
                    problems.append(f"scene {n}: no country called {name!r} on the map (countries only, never cities)")
    return problems


def check_direction(raw: Any, script: dict[str, Any], p: Params) -> list[str]:
    """Every problem with a storyboard.json, after its wishes are taken out (empty = usable)."""
    shape = '{"hooks": [3 hook scenes], "scenes": [...], "cover": {"scene": n, "words": "..."}}'
    if not isinstance(raw, dict) or not isinstance(raw.get("hooks"), list) or not isinstance(raw.get("scenes"), list):
        return [f"answer {shape} only"]
    if len(raw["hooks"]) != 3 or not all(isinstance(h, dict) for h in raw["hooks"]):
        return ['"hooks" must be 3 scenes, one for each hook of the script, in order']
    if not raw["scenes"] or not all(isinstance(s, dict) for s in raw["scenes"]):
        return ['"scenes" must be scene objects, at least one']
    broken = [f"unknown key {k!r} (only hooks, scenes, cover)" for k in sorted(set(raw) - {"hooks", "scenes", "cover"})]
    for n, hook in enumerate(raw["hooks"], 1):
        found = _structure([hook, *raw["scenes"]], p)
        broken += [f"hook {n}: {x}" if x.startswith("scene 1:") or x.startswith("scene 1 ") else x for x in found]
    problems = _locked(raw, script)
    if broken:  # unparsable scenes: the content checks below would misfire
        return list(dict.fromkeys(broken + problems))
    for n, hook in enumerate(raw["hooks"], 1):
        problems += pacing(f"hook {n}", hook) + evidence(f"hook {n}", hook, p.notes)
    for n, scene in enumerate(raw["scenes"], 2):
        problems += pacing(f"scene {n}", scene) + evidence(f"scene {n}", scene, p.notes)
    cover, count = raw.get("cover"), 1 + len(raw["scenes"])
    if not (isinstance(cover, dict) and isinstance(cover.get("scene"), int) and not isinstance(cover["scene"], bool)
            and 1 <= cover["scene"] <= count and 1 <= len(str(cover.get("words", "")).split()) <= 5):
        problems.append(f'"cover" must be {{"scene": 1–{count}, "words": "2–4 words"}}')
    return list(dict.fromkeys(problems))


# ---------------------------------------------------------------- 3. animation


def component_names(raw: dict[str, Any]) -> dict[str, str]:
    """Where each custom scene's component goes: "hook 2" → hook2.tsx, scene NN → sceneNN.tsx
    (hook 1 is scene 01, the first of "scenes" is 02)."""
    names = {}
    for n, hook in enumerate(raw.get("hooks") or [], 1):
        if isinstance(hook, dict) and hook.get("type") == "custom":
            names[f"hook {n}"] = "scene01.tsx" if n == 1 else f"hook{n}.tsx"
    for n, scene in enumerate(raw.get("scenes") or [], 2):
        if isinstance(scene, dict) and scene.get("type") == "custom":
            names[f"scene {n}"] = f"scene{n:02d}.tsx"
    return names


def static_problems(code: str) -> list[str]:
    problems = []
    if len(code.encode()) > MAX_BYTES:
        problems.append(f"the component is over {MAX_BYTES // 1000} KB")
    for found in IMPORT.finditer(code):
        name = found.group(1) or found.group(2)
        if name not in ALLOWED_IMPORTS:
            problems.append(f"import {name!r} is not allowed (allowed: {', '.join(sorted(ALLOWED_IMPORTS))})")
    problems += [f"{why} (found {match.group(0)!r})" for pattern, why in BANNED for match in [pattern.search(code)] if match]
    if not re.search(r"export\s+default\s+(function|\w)", code):
        problems.append("there is no `export default function Scene(...)`")
    return problems


def check_components(codes: dict[str, str | None], wanted: list[str]) -> list[str]:
    """``codes``: file name → its code (None = missing); ``wanted``: the files to check."""
    problems = []
    for name in wanted:
        code = codes.get(name)
        if not code:
            problems.append(f"{name}: missing")
            continue
        problems += [f"{name}: {p}" for p in static_problems(code)]
    return problems


# ---------------------------------------------------------------- together


def merge(script: dict[str, Any], board: dict[str, Any]) -> dict[str, Any]:
    """Script + direction → the storyboard the queue renders: {"title", "hooks": [{"family", "scene"}],
    "scenes", "cover"}; custom scenes get their component's file name."""
    names = component_names(board)
    hooks = []
    for n, (h, scene) in enumerate(zip(script["hooks"], board["hooks"]), 1):
        scene = dict(scene)
        if f"hook {n}" in names:
            scene["component"] = names[f"hook {n}"]
        hooks.append({"family": h["family"], "scene": scene})
    scenes = []
    for n, scene in enumerate(board["scenes"], 2):
        scene = dict(scene)
        if f"scene {n}" in names:
            scene["component"] = names[f"scene {n}"]
        scenes.append(scene)
    return {"title": _text(script["title"]), "hooks": hooks, "scenes": scenes, "cover": board["cover"]}
