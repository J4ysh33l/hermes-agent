"""Notes or a script → a storyboard with 3 hook variants, written by Gemini to the page profile's
``writing:`` (format, hooks, humour, tone, words to avoid, example scripts, length) and checked in code.

The prompt is built from the profile and PLAYBOOK.md (the format's beats, the hook bank, the ten rules).
The model fills scenes and fields only; it never writes animation code. What it returns must pass
``storyboard.parse`` and the checks below; problems go back to the same model once ("fix these"), then
the next model in ``studio.script_models`` starts fresh.

Checks (each refusal names the scene):
- 3 hooks from 3 different families; the hook's first sentence is short and is not a greeting.
- Length within 20% of the profile's ``seconds`` at the voice's pace; no sentence over 24 words; a scene
  says at most ~6 s unless it has parts (list items, bars, boxes, events), one sentence per part.
- No phrase from the profile's ``avoid`` (plus the usual "in this video", "welcome back" …).
- Only scene types the profile allows; image scenes only as stock b-roll (``stock:`` src) when a Pexels or
  Pixabay key is set and the page allows b-roll; never meme scenes or files.
- **Evidence comes from the notes:** a stat's or chart's numbers, a quote, a headline or a post's text
  must appear in what you gave it. The model may not invent proof.
- Map scenes name countries the map has (cities are refused: the map draws countries only).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator import llm
from orchestrator.brief.net import Http, HttpError
from orchestrator.brief.settings import ModelChoice

from . import broll, custom, direction, storyboard, video
from .profile import Profile
from .settings import Keys, Settings
from .voice import sentences

PLAYBOOK = Path(__file__).with_name("PLAYBOOK.md")
WPM = 196  # measured at voice speed 1.0, pause 0.15 (README); scales with the profile's speed
MAX_SENTENCE = 24
SCENE_WORDS = 20  # ~6 s at 196 wpm
CUSTOM_WORDS = 40  # a custom scene animates through its own sentences
PART_WORDS = 16  # per list item / bar / box / event
HOOK_WORDS = 12  # the hook's first sentence
FORMATS = {"explainer": "A", "news": "B", "how-it-works": "C", "business-case": "D", "hindi-explainer": "E"}
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
NEEDS_FILE = ("image", "meme")  # image comes back as stock b-roll when a key is set (broll.py)
PARTS = {"bullets": "items", "terminal": "lines", "chart": "labels", "diagram": "nodes", "timeline": "events"}
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


class WriterError(ValueError):
    """Shown as it is; nothing was written."""


@dataclass(frozen=True)
class Hook:
    family: str
    scene: dict[str, Any]


@dataclass(frozen=True)
class Draft:
    title: str
    hooks: tuple[Hook, ...]  # hooks[0] opens ``storyboard(0)``
    scenes: tuple[dict[str, Any], ...]  # after the hook
    model: str
    rounds: int  # model calls it took
    notes: tuple[str, ...]  # soft warnings, shown, not refused
    wishes: tuple[str, ...] = ()  # visuals the model wanted but we cannot make yet (scene type: wish)
    cover: tuple[int, str] = (1, "")  # the scene the cover shows (1 = the hook) and its 2–4 big words

    def storyboard(self, hook: int, profile: str) -> dict[str, Any]:
        return {"title": self.title, "profile": profile, "scenes": [self.hooks[hook].scene, *self.scenes]}

    def script(self, hook: int = 0) -> str:
        return "\n".join(s["say"] for s in (self.hooks[hook].scene, *self.scenes))

    def words(self, hook: int = 0) -> int:
        return len(spoken(self.script(hook)).split())


# ---------------------------------------------------------------- the prompt


def _format_beats(fmt: str) -> str:
    text = PLAYBOOK.read_text(encoding="utf-8")
    found = re.search(rf"^### {FORMATS[fmt]}\. .*?(?=^### |^---)", text, re.MULTILINE | re.DOTALL)
    return found.group(0).strip() if found else ""


def _rules() -> str:
    text = PLAYBOOK.read_text(encoding="utf-8")
    found = re.search(r"^## 1\. .*?(?=^---)", text, re.MULTILINE | re.DOTALL)
    return found.group(0).strip() if found else ""


def allowed_scenes(look: Profile, stock: bool = False) -> list[str]:
    """The library types this page uses (all unless its profile lists some), plus custom, always; image
    scenes too when stock b-roll can be searched (``stock``) and the page allows it."""
    elements = look.section("elements")
    listed = list(elements["scenes"]) or [s for s in storyboard.SCHEMA if s != "custom"]
    footage = stock and elements["broll"] != "off"
    return [s for s in listed if s in storyboard.SCHEMA and s != "custom"
            and (s not in NEEDS_FILE or (footage and s == "image"))] + ["custom"]


MEDIA = {
    False: '- No "src" fields: there are no image files, so no image or meme scenes (a custom scene can draw instead).',
    True: '- Image scenes are stock footage: "src": "stock:<what the clip shows, 2–6 plain words>" (e.g. "stock:busy '
          'mumbai street at night"), searched on Pexels/Pixabay; a portrait clip fills the screen under the caption. '
          'Use it where real footage beats a graphic (places, people, things), at most 1 in 3 scenes. No other "src".',
}


def _families(look: Profile) -> list[str]:
    wanted = [h for h in look.section("writing")["hooks"] if h in HOOKS]
    return wanted + [h for h in HOOKS if h not in wanted]


SCENE_HELP = storyboard.__doc__ or ""

PROMPT = """You write vertical short videos (1080×1920, ~{seconds} s) for a faceless page. You write the
narration AND direct what is on screen, as JSON scenes. Quality beats speed: write the best video you can
imagine, then express it with the scenes below.

# The page
Format: {format}. Language: {language}. Tone: {tone}. Humour: {humour}.
Never say: {avoid}.
{examples}
# The ten rules every great channel follows
{rules}

# The format's beats
{beats}

# Hooks
Write exactly 3 hooks, each from a DIFFERENT family, in this order of preference: {families}.
Families: {hook_bank}
A hook is the whole first scene: the first sentence is at most {hook_words} words, says the topic or the
claim at once, and never greets. Each hook must lead naturally into the same second scene.

# Scenes: a fast track, not a menu
The library types ({scenes}) are ready-made, tested and quick to render: use one when it is genuinely the
best way to show that moment. When a better picture exists, ask for it: a "custom" scene with a "brief"
describing exactly what is on screen and how it moves with the words. A custom scene is built for this
video by a motion designer (Claude, writing a Remotion component) and checked frame by frame; give it a
"fallback" library scene, drawn only if the build fails. Nothing here limits your ideas except the real
limits of the pipeline:

{limits}

Change the picture every 1.5–4 s; never two scenes of the same type in a row unless it is the point.
The format and fields:
{scene_help}
- A custom brief is direction for an animator: name the elements, their arrangement, what appears on
  which sentence, the motion, what the viewer should feel. Data the component should show goes in
  "props" (numbers from the notes only). "full_bleed": true when it should own the whole frame.
- "say" is the narration. One idea per sentence, sentences under {max_sentence} words, spoken English
  (contractions, plain words). Wrap 1–2 key words per scene in *asterisks* (caption colour + camera punch).
- A library scene without parts says at most {scene_words} words; a custom scene at most {custom_words}. Scenes with parts (bullets items, chart
  labels, diagram nodes, timeline events, terminal lines) say ONE sentence per part, in order, after at
  most one intro sentence.
- Maps take COUNTRY names only (Natural Earth names, e.g. "United States of America", "India"); never
  cities or regions.
{media}
- EVIDENCE: numbers in stat/chart scenes, quote text, clipping headlines and post text must be copied
  from the notes below. If the notes have no such fact, use another scene type. Never invent data,
  quotes or headlines.
- Total narration: about {words} words (hooks included, one hook counted).
- Optional "emoji" on at most 2 scenes.
- Optional "transition" into the next scene when the change means something (the page's own is used
  otherwise): burn = a jump in time, flash = a reveal, zoom = going deeper, whip = a contrast, fade = calm, cut.
- Voice directions inside "say" (spoken, never shown): [beat] = a 0.4 s pause, e.g. before a reveal
  ("And the winner is [beat] India."); [pause 0.8] = an exact pause; [slow] or [fast] = the rest of the
  sentence slower or faster. Use them where a human narrator would: 1–4 per video, never decoration.
  Punctuation directs too: "?" lifts, "..." hesitates, "—" breaks.
- WISHES: only for what is beyond the limits above even as a custom scene (real footage, a real person,
  a specific sound): do your best on screen AND add "wish": "<that thing, in at most 15 words>" to the
  scene. They tell us what to add to the pipeline next.

# The notes (the only source of facts)
<notes>
{notes}
</notes>

# The cover
Pick the most striking scene for the thumbnail (1 = the hook) and 2–4 huge words for it that add to the
title, never repeat it (PLAYBOOK: one striking visual + a few words, high contrast).

Answer with JSON only:
{{"title": "...", "hooks": [{{"family": "...", "scene": {{...}}}}, x3], "scenes": [{{...}}, ...],
 "cover": {{"scene": 2, "words": "..."}}}}"""

REPAIR = """Your storyboard below failed these checks. Fix every one, keep everything else as good as it is,
and answer with the whole corrected JSON only.

Problems:
{problems}

Your storyboard:
{draft}"""


def prompt(look: Profile, notes: str, seconds: float, words: int, stock: bool = False) -> str:
    w = look.section("writing")
    examples = "".join(f"\nAn example script this page liked:\n<example>\n{e}\n</example>\n" for e in w["examples"])
    families = _families(look)
    return PROMPT.format(
        seconds=round(seconds), format=w["format"], language=w["language"], tone=w["tone"] or "plain",
        humour=w["humour"] or "none", avoid=", ".join(f'"{a}"' for a in (*w["avoid"], *ALWAYS_AVOID)),
        examples=examples, rules=_rules(), beats=_format_beats(w["format"]), families=", ".join(families[:3]),
        hook_bank="\n".join(f"- {name}: {template}" for name, template in HOOKS.items()),
        hook_words=HOOK_WORDS, scenes=", ".join(s for s in allowed_scenes(look, stock) if s != "custom"), scene_help=SCENE_HELP,
        media=MEDIA[stock and look.section("elements")["broll"] != "off"],
        max_sentence=MAX_SENTENCE, scene_words=SCENE_WORDS, custom_words=CUSTOM_WORDS, words=words,
        notes=notes.strip(), limits=custom.LIMITS)


# ---------------------------------------------------------------- the checks


def spoken(say: Any) -> str:
    """What the voice says: no *emphasis* marks, no [directions]."""
    return direction.strip(str(say).replace("*", ""))


def _squash(text: str) -> str:
    return re.sub(r"[^\w%₹$.,]+", " ", text.lower()).strip()


def _number_in(value: Any, notes: str) -> bool:
    raw = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
    found = {n.replace(",", "") for n in NUMBER.findall(notes)}
    return raw.replace(",", "") in found


def _evidence(n: int, scene: dict[str, Any], notes: str) -> list[str]:
    kind, where, squashed = scene.get("type"), f"scene {n}", _squash(notes)
    texts = {"quote": ("text",), "clipping": ("headline",), "post": ("text",)}.get(kind, ())
    problems = [f"{where} ({kind}): its {key} is not in the notes; copy it word for word or use another scene"
                for key in texts if _squash(str(scene.get(key, ""))) not in squashed]
    numbers = [scene.get("value")] if kind == "stat" else list(scene.get("values") or []) if kind == "chart" else []
    if kind == "custom":  # data a custom scene shows; small counts (3 gears) are pictures, not claims
        numbers = [v for v in _numbers(scene.get("props")) if abs(v) >= 10]
        problems += _evidence(n, dict(scene.get("fallback") or {}), notes) if isinstance(scene.get("fallback"), dict) else []
    problems += [f"{where} ({kind}): the number {v} is not in the notes; use only numbers given there"
                 for v in numbers if not _number_in(v, notes)]
    return problems


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


def _pacing(n: int, scene: dict[str, Any]) -> list[str]:
    where, said = f"scene {n}", sentences(spoken(scene.get("say", "")))
    problems = [f"{where}: a sentence has {len(s.split())} words (at most {MAX_SENTENCE}): {s[:60]!r}"
                for s in said if len(s.split()) > MAX_SENTENCE]
    words = sum(len(s.split()) for s in said)
    parts = len(scene.get(PARTS.get(scene.get("type"), ""), None) or [])
    if parts and len(said) < parts:
        problems.append(f"{where} ({scene['type']}): {parts} parts but {len(said)} sentences; say one sentence per part")
    elif parts and len(said) > parts + 1:
        problems.append(f"{where} ({scene['type']}): {len(said)} sentences for {parts} parts; at most one intro sentence")
    limit = SCENE_WORDS + PART_WORDS * parts if parts else CUSTOM_WORDS if scene.get("type") == "custom" else SCENE_WORDS
    if words > limit:
        problems.append(f"{where}: {words} words is too long for one picture (at most {limit}); split it")
    return problems


def _avoided(scenes: list[dict[str, Any]], look: Profile) -> list[str]:
    banned = [a.lower() for a in (*look.section("writing")["avoid"], *ALWAYS_AVOID) if a]
    return [f"scene {n}: says {a!r}, which this page never says"
            for n, scene in enumerate(scenes, 1) for a in banned if a in str(scene.get("say", "")).lower()]


def _hooks(hooks: list[dict[str, Any]]) -> list[str]:
    families = [h.get("family") for h in hooks]
    problems = [f"hook {n}: family {f!r} is not one of {', '.join(HOOKS)}"
                for n, f in enumerate(families, 1) if f not in HOOKS]
    if len(set(families)) != 3:
        problems.append("the 3 hooks must come from 3 different families")
    for n, h in enumerate(hooks, 1):
        first = (sentences(spoken(h["scene"].get("say", ""))) or [""])[0]
        if len(first.split()) > HOOK_WORDS:
            problems.append(f"hook {n}: first sentence has {len(first.split())} words (at most {HOOK_WORDS})")
        if GREETINGS.match(first):
            problems.append(f"hook {n}: starts with a greeting; start with the topic or the claim")
    return problems


def _length(words: int, target: int) -> list[str]:
    low, high = round(target * 0.8), round(target * 1.2)
    return [] if low <= words <= high else [f"the narration is {words} words; it must be {low}–{high} "
                                            f"(about {target}) to fit the length"]


def _types(scenes: list[dict[str, Any]], look: Profile, stock: bool) -> list[str]:
    allowed = allowed_scenes(look, stock)
    return [f"scene {n}: type {s.get('type')!r} is not allowed here (allowed: {', '.join(allowed)})"
            for n, s in enumerate(scenes, 1) if s.get("type") not in allowed]


def _parsed(scenes: list[dict[str, Any]], folder: Path, stock: bool) -> list[str]:
    try:
        board = storyboard.parse({"scenes": scenes}, folder)
    except storyboard.StoryboardError as exc:
        return [str(exc)]
    srcs = [src for s in board.scenes for src in storyboard.files(s.fields)]
    if any(not (stock and src.startswith(storyboard.STOCK)) for src in srcs):
        return ['no "src" fields but "stock:..." on image scenes' if stock else 'no "src" fields: there are no images']
    if any(s.type == "map" for s in board.scenes) and video.WORLD.is_file():
        try:
            video.check_countries(board)
        except video.VideoError as exc:
            return [f"{exc} (maps take countries only, never cities)"]
    return []


def check(raw: Any, look: Profile, notes: str, target: int, folder: Path, stock: bool = False) -> list[str]:
    """Every problem with a model's answer (empty = usable)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("scenes"), list) or not isinstance(raw.get("hooks"), list):
        return ['answer {"title": ..., "hooks": [3 hooks], "scenes": [...]} only']
    hooks = raw["hooks"]
    if len(hooks) != 3 or not all(isinstance(h, dict) and isinstance(h.get("scene"), dict) for h in hooks):
        return ['"hooks" must be 3 objects like {"family": ..., "scene": {...}}']
    body = [s for s in raw["scenes"] if isinstance(s, dict)]
    if len(body) != len(raw["scenes"]) or not body:
        return ["every scene must be an object, and there must be scenes after the hook"]
    problems = _hooks(hooks)
    for h in hooks:
        scenes = [h["scene"], *body]
        problems += _parsed(scenes, folder, stock) + _types(scenes, look, stock)
    if any(not p.startswith("hook ") and "different families" not in p for p in problems):
        return list(dict.fromkeys(problems))  # unparsable scenes: the content checks below would misfire
    first = [raw["hooks"][0]["scene"], *body]
    for n, scene in enumerate(first, 1):
        problems += _pacing(n, scene) + _evidence(n, scene, notes)
    problems += [f"hook {n}: {p}" for n, h in enumerate(raw["hooks"][1:], 2)
                 for p in _pacing(1, h["scene"]) + _evidence(1, h["scene"], notes)]
    problems += _avoided(first + [h["scene"] for h in raw["hooks"][1:]], look)
    problems += _length(sum(len(spoken(s["say"]).split()) for s in first), target)
    return list(dict.fromkeys(problems))


def soft_notes(scenes: list[dict[str, Any]]) -> list[str]:
    """Worth a look, not worth refusing."""
    notes = []
    if sum("*" in str(s["say"]) for s in scenes) < len(scenes) // 2:
        notes.append("few *emphasised* words: fewer punch-ins and coloured caption words")
    kinds = [s["type"] for s in scenes]
    common = max(set(kinds), key=kinds.count)
    if len(kinds) >= 5 and kinds.count(common) > len(kinds) * 0.4:
        notes.append(f"{kinds.count(common)} of {len(kinds)} scenes are {common}: little visual variety")
    return notes


# ---------------------------------------------------------------- the model


def _json(text: str) -> Any:
    found = re.search(r"\{.*\}", text, re.DOTALL)
    if not found:
        raise ValueError("no JSON in the answer")
    return json.loads(found.group(0))


def _wishes(raw: Any) -> list[str]:
    """Takes every scene's "wish" out (the storyboard has no such key) → "type: wish" lines."""
    if not isinstance(raw, dict):
        return []
    scenes = [h.get("scene") for h in raw.get("hooks") or [] if isinstance(h, dict)] + list(raw.get("scenes") or [])
    found = []
    for scene in scenes:
        if isinstance(scene, dict) and "wish" in scene:
            wish = " ".join(str(scene.pop("wish")).split()[:20])
            if wish:
                found.append(f"{scene.get('type', '?')}: {wish}")
    return list(dict.fromkeys(found))


def remember(draft: Draft, home: Path, topic: str) -> Path:
    """Wishes go to $HERMES_HOME/studio/wishes.jsonl, one line each: what to build next, by demand."""
    path = home / "studio" / "wishes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for wish in draft.wishes:
            scene, _, text = wish.partition(": ")
            f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "title": draft.title,
                                "topic": topic[:120], "instead_of": scene, "wish": text}, ensure_ascii=False) + "\n")
    return path


def wishlist(home: Path, top: int = 20) -> list[tuple[int, str]]:
    """The most wished-for visuals, most first (same words counted together)."""
    path = home / "studio" / "wishes.jsonl"
    if not path.is_file():
        return []
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            wish = str(json.loads(line)["wish"]).strip().lower().rstrip(".")
        except (ValueError, KeyError, TypeError):
            continue
        counts[wish] = counts.get(wish, 0) + 1
    return sorted(((n, w) for w, n in counts.items()), key=lambda x: (-x[0], x[1]))[:top]


def target_words(look: Profile, seconds: float) -> int:
    return round(seconds / 60 * WPM * float(look.section("voice")["speed"]))


def _ask(http: Http, keys: Keys, settings: Settings, model: ModelChoice, question: str, attempt: int) -> str:
    step = "storyboard" if attempt == 0 else "storyboard-fix"
    if model.id.startswith("claude-"):
        return llm.claude(http, keys.claude, model.id, question, workflow="studio", step=step,
                          effort=settings.claude_effort)
    return llm.gemini(http, keys.gemini, model.id, question, workflow="studio", step=step,
                      json_mode=model.json_mode, max_output_tokens=8000, temperature=0.9 if attempt == 0 else 0.4)


def choose(settings: Settings, claude: bool = False, gemini: bool = False) -> bool:
    """True = Claude writes: asked for, or studio.writer (claude by default) unless Gemini was asked for."""
    return claude or (not gemini and settings.writer == "claude")


def models(settings: Settings, use_claude: bool) -> tuple[ModelChoice, ...]:
    """Claude (studio.claude_model) or Gemini's free models (studio.script_models), tried in order."""
    return (ModelChoice(settings.claude_model),) if use_claude else settings.script_models


def write(http: Http, keys: Keys, settings: Settings, look: Profile, notes: str, seconds: float = 0,
          folder: Path = Path("."), use_claude: bool = False) -> Draft:
    """``notes``: what the video is about (facts, links' text, a draft script). ``seconds``: 0 = the
    profile's ``writing.seconds``. ``use_claude``: Claude (studio.claude_model) instead of Gemini."""
    chosen = models(settings, use_claude)
    if use_claude and not keys.claude:
        raise WriterError("Writing with Claude needs ANTHROPIC_API_KEY in your .env")
    if not use_claude and not keys.gemini:
        raise WriterError("Writing a storyboard needs GEMINI_API_KEY")
    if len(notes.split()) < 3:
        raise WriterError("Give it something to work from: a topic with a few facts, or a draft script")
    seconds = seconds or float(look.section("writing")["seconds"])
    words = target_words(look, seconds)
    stock = broll.available(keys)
    ask = prompt(look, notes, seconds, words, stock)
    tried, rounds = [], 0
    for model in chosen:
        question, answer = ask, ""
        for attempt in range(2):  # the first answer, then one repair
            rounds += 1
            try:
                answer = _ask(http, keys, settings, model, question, attempt)
                raw = _json(answer)
            except (HttpError, ValueError) as exc:
                tried.append(f"{model.id}: {str(exc)[:100]}")
                break
            accepted = accept(raw, look, notes, words, folder, model.id, rounds, stock)
            if isinstance(accepted, Draft):
                return accepted
            problems = accepted
            tried.append(f"{model.id} (try {attempt + 1}): {'; '.join(problems[:3])}")
            question = REPAIR.format(problems="\n".join(f"- {p}" for p in problems),
                                     draft=json.dumps(raw, ensure_ascii=False, indent=1))
    raise WriterError("No usable storyboard: " + " | ".join(tried))


def accept(raw: Any, look: Profile, notes: str, words: int, folder: Path, model: str,
           rounds: int, stock: bool = False) -> Draft | list[str]:
    """A model's answer → a Draft, or the problems to send back (wishes are taken out either way)."""
    wishes = _wishes(raw)
    problems = check(raw, look, notes, words, folder, stock)
    cover = raw.get("cover") if isinstance(raw, dict) else None
    scenes = 1 + len(raw.get("scenes") or []) if isinstance(raw, dict) else 0
    if cover is not None and not (isinstance(cover, dict) and isinstance(cover.get("scene"), int)
                                  and 1 <= cover["scene"] <= scenes and 1 <= len(str(cover.get("words", "")).split()) <= 5):
        problems.append(f'"cover" must be {{"scene": 1–{scenes}, "words": "2–4 words"}}')
    if problems:
        return problems
    hooks = tuple(Hook(h["family"], h["scene"]) for h in raw["hooks"])
    picked = (cover["scene"], " ".join(str(cover["words"]).split())) if cover else (1, "")
    return Draft(str(raw.get("title") or "").strip(), hooks, tuple(raw["scenes"]), model, rounds,
                 tuple(soft_notes([hooks[0].scene, *raw["scenes"]])), tuple(wishes), picked)


def save(draft: Draft, out: Path, profile: str) -> list[Path]:
    """``out`` gets hook 1; ``<out>.hook2.json`` and ``.hook3.json`` the others; ``<out>.txt`` the script."""
    out.parent.mkdir(parents=True, exist_ok=True)
    paths = []
    for n in range(len(draft.hooks)):
        path = out if n == 0 else out.with_suffix(f".hook{n + 1}.json")
        path.write_text(json.dumps(draft.storyboard(n, profile), ensure_ascii=False, indent=1), encoding="utf-8")
        paths.append(path)
    lines = [f"# {draft.title}", ""]
    for n, hook in enumerate(draft.hooks, 1):
        lines.append(f"Hook {n} ({hook.family}): {hook.scene['say']}")
    lines += ["", *(f"[{s['type']}] {s['say']}" for s in draft.scenes)]
    lines += ["", f"Cover: scene {draft.cover[0]}, words: {draft.cover[1] or draft.title}"]
    out.with_suffix(".cover.json").write_text(json.dumps({"scene": draft.cover[0], "words": draft.cover[1]}),
                                              encoding="utf-8")
    script = out.with_suffix(".txt")
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [*paths, script]
