"""Notes → a checked storyboard in three calls, one job each (prompts in ``brief.py``):

1. **script**: the words (title, 3 hooks, the lines after the hook);
2. **direction**: the pictures, the script's words locked;
3. **animation**: every custom scene's component, in one answer (skipped when there is none).

Each answer is checked in code (``rules.py``). A failing one goes back to the same model with its problems
(the script once, direction ``studio.direction_retries`` times, the components once); the next model in
``studio.script_models`` starts over when a model cannot get the script or direction right. A component
that still fails is drawn as its scene's fallback at render time: a video is never lost over one scene.

Here the calls go through an API (Gemini, or Claude with ANTHROPIC_API_KEY). Claude on your plan makes the
same three calls through the handoff repo instead (``handoff.py``, ``queue.py``), with the same prompts
and checks. Either way the job folder gets ``script.json``, ``direction.json`` and the components, and
``finish`` turns them into the storyboards the queue renders.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from orchestrator import llm
from orchestrator.brief.net import Http, HttpError
from orchestrator.brief.settings import ModelChoice

from . import brief, rules
from .profile import Profile
from .settings import Keys, Settings
from .text import said_words

SCRIPT_RETRIES = 1  # Claude checks its own script before handing it in; this is the safety net
COMPONENT_FIXES = 1  # failing components go back once, then fall back to their library scene
CODE = re.compile(r"```(?:tsx|typescript|ts|jsx)?[^\n]*\n(.*?)```", re.DOTALL)
FILE = re.compile(r"^\s*//\s*file:\s*([\w.-]+)\s*$", re.MULTILINE)


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
    wishes: tuple[str, ...] = ()  # visuals the director wanted but we cannot make yet (scene type: wish)
    cover: tuple[int, str] = (1, "")  # the scene the cover shows (1 = the hook) and its 2–4 big words

    def storyboard(self, hook: int, profile: str) -> dict[str, Any]:
        return {"title": self.title, "profile": profile, "scenes": [self.hooks[hook].scene, *self.scenes]}

    def script(self, hook: int = 0) -> str:
        return "\n".join(s["say"] for s in (self.hooks[hook].scene, *self.scenes))

    def words(self, hook: int = 0) -> int:
        return said_words(self.script(hook))


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


# ---------------------------------------------------------------- answers


def parse_json(text: str) -> Any:
    found = re.search(r"\{.*\}", text, re.DOTALL)
    if not found:
        raise ValueError("no JSON in the answer")
    return json.loads(found.group(0))


def parse_components(text: str) -> dict[str, str]:
    """```tsx blocks, each starting with ``// file: sceneNN.tsx`` → file name → code."""
    found = {}
    for block in CODE.findall(text):
        name = FILE.search(block.split("\n", 1)[0] + "\n")
        if name:
            found[name.group(1)] = block.split("\n", 1)[1].strip() + "\n" if "\n" in block else ""
    if not found:
        raise ValueError("no ```tsx block starting with // file: <name>")
    return found


def save_components(folder: Path, codes: dict[str, str | None], wanted: list[str]) -> list[str]:
    """Writes each wanted component that passes the static checks; returns the files written."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name in wanted:
        code = codes.get(name)
        if code and not rules.static_problems(code):
            folder.joinpath(name).write_text(code, encoding="utf-8")
            written.append(name)
    return written


def finish(folder: Path, model: str, rounds: int, wishes: list[str]) -> Draft:
    """The job folder's ``script.json`` + ``direction.json`` + components → the Draft to render; a custom
    scene whose component is missing is drawn as its fallback."""
    script = json.loads(folder.joinpath("script.json").read_text(encoding="utf-8"))
    board = json.loads(folder.joinpath("direction.json").read_text(encoding="utf-8"))
    merged = rules.merge(script, board)
    for scene in [h["scene"] for h in merged["hooks"]] + merged["scenes"]:
        if scene.get("component") and not folder.joinpath(scene["component"]).is_file():
            _to_fallback(scene)
    hooks = tuple(Hook(h["family"], h["scene"]) for h in merged["hooks"])
    cover = merged["cover"]
    return Draft(merged["title"], hooks, tuple(merged["scenes"]), model, rounds,
                 tuple(soft_notes([hooks[0].scene, *merged["scenes"]])), tuple(wishes),
                 (cover["scene"], " ".join(str(cover["words"]).split())))


def _to_fallback(scene: dict[str, Any]) -> None:
    """A custom scene without its component becomes its fallback library scene, saying the same words."""
    fallback = dict(scene.pop("fallback"))
    for key in ("brief", "props", "full_bleed", "component", "type"):
        scene.pop(key, None)
    scene.update(fallback)


# ---------------------------------------------------------------- the model


@dataclass
class Model:
    """One model answering the three calls (and their fixes)."""
    http: Http
    keys: Keys
    settings: Settings
    choice: ModelChoice
    calls: int = 0

    def ask(self, prompt: str, step: str, code: bool = False) -> str:
        self.calls += 1
        if self.choice.id.startswith("claude-"):
            return llm.claude(self.http, self.keys.claude, self.choice.id, prompt, workflow="studio", step=step,
                              effort=self.settings.claude_effort, max_tokens=32000 if code else 16000)
        return llm.gemini(self.http, self.keys.gemini, self.choice.id, prompt, workflow="studio", step=step,
                          json_mode=self.choice.json_mode and not code, max_output_tokens=32000 if code else 8000,
                          temperature=0.4 if step.endswith("-fix") else 0.9)


def stage(model: Model, name: str, job: str, prompt: str, check: Callable[[Any], list[str]], retries: int) -> Any:
    """One call, checked; its problems go back ``retries`` times. Returns the answer or raises."""
    question, problems = prompt, []
    for attempt in range(retries + 1):
        answer = model.ask(question, name if attempt == 0 else f"{name}-fix")
        try:
            raw = parse_json(answer)
        except ValueError as exc:
            problems, previous = [f"the answer is not JSON: {exc}"], answer[:6000]
        else:
            problems, previous = check(raw), json.dumps(raw, ensure_ascii=False, indent=1)
            if not problems:
                return raw
        question = brief.fix(name, job, prompt, problems, previous)
    raise WriterError(f"{name}: " + "; ".join(problems[:3]))


def animate(model: Model, look: Profile, board: dict[str, Any], title: str, folder: Path,
            failed: dict[str, str] | None = None) -> list[str]:
    """The custom scenes' components into ``folder`` (all of them, or a fix of ``failed``: file → problem).
    Returns the files written; one that still fails is left out (its scene falls back)."""
    job, wanted = folder.name, list(rules.component_names(board).values())
    only = set(failed) if failed else None
    prompt = brief.animation(look, board, title, job, False, only)
    question = prompt if not failed else brief.fix(
        "animation", job, prompt, [f"{n}: {p}" for n, p in failed.items()],
        "\n\n".join(f"// file: {n}\n{folder.joinpath(n).read_text(encoding='utf-8')}" for n in failed
                    if folder.joinpath(n).is_file()))
    targets, codes = (list(failed) if failed else wanted), {}
    for attempt in range(COMPONENT_FIXES + 1):
        try:
            codes.update(parse_components(model.ask(question, "animation" if attempt == 0 and not failed else "animation-fix",
                                                    code=True)))
        except (HttpError, ValueError):
            break
        problems = rules.check_components(codes, targets)
        if not problems or attempt == COMPONENT_FIXES:
            break
        bad = {p.split(":", 1)[0] for p in problems}
        question = brief.fix("animation", job, brief.animation(look, board, title, job, False, bad), problems,
                             "\n\n".join(f"// file: {n}\n{codes[n]}" for n in bad if codes.get(n)))
    return save_components(folder, codes, targets)


def write(http: Http, keys: Keys, settings: Settings, look: Profile, notes: str, seconds: float = 0,
          folder: Path = Path("."), use_claude: bool = False) -> Draft:
    """``notes``: what the video is about (facts, links' text, a draft script). ``seconds``: 0 = the
    profile's ``writing.seconds``. ``use_claude``: Claude (studio.claude_model) instead of Gemini.
    The job's files go to ``folder`` (its name is the job id in the prompts)."""
    if use_claude and not keys.claude:
        raise WriterError("Writing with Claude needs ANTHROPIC_API_KEY in your .env")
    if not use_claude and not keys.gemini:
        raise WriterError("Writing a storyboard needs GEMINI_API_KEY")
    if len(notes.split()) < 3:
        raise WriterError("Give it something to work from: a topic with a few facts, or a draft script")
    p, job, tried = brief.params(look, notes, seconds), folder.name, []
    for choice in models(settings, use_claude):
        model = Model(http, keys, settings, choice)
        try:
            script = stage(model, "script", job, brief.script(look, notes, seconds, job, False),
                           lambda raw: rules.check_script(raw, p), SCRIPT_RETRIES)
            raw = stage(model, "direction", job, brief.direction(look, notes, script, job, False),
                        lambda raw: rules.check_direction(rules.take_wishes(raw)[0], script, p),
                        settings.direction_retries)
        except (HttpError, ValueError) as exc:  # ValueError: a refusal or a cut-off answer (llm), or WriterError
            tried.append(f"{choice.id}: {str(exc)[:200]}")
            continue
        board, wishes = rules.take_wishes(raw)
        keep(folder, script, board)
        if rules.component_names(board):
            animate(model, look, board, script["title"], folder)
        return finish(folder, choice.id, model.calls, wishes)
    raise WriterError("No usable storyboard: " + " | ".join(tried))


def keep(folder: Path, script: dict[str, Any], board: dict[str, Any]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    folder.joinpath("script.json").write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    folder.joinpath("direction.json").write_text(json.dumps(board, ensure_ascii=False, indent=1), encoding="utf-8")


def choose(settings: Settings, claude: bool = False, gemini: bool = False) -> bool:
    """True = Claude writes: asked for, or studio.writer (claude by default) unless Gemini was asked for."""
    return claude or (not gemini and settings.writer == "claude")


def models(settings: Settings, use_claude: bool) -> tuple[ModelChoice, ...]:
    """Claude (studio.claude_model) or Gemini's free models (studio.script_models), tried in order."""
    return (ModelChoice(settings.claude_model),) if use_claude else settings.script_models


# ---------------------------------------------------------------- saving


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
