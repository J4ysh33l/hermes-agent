"""Custom scenes: a picture the library does not have, written as a Remotion component for one video.

The library scenes are a fast track (ready, tested, quick to render), never the limit. When the writer
wants anything else it adds a ``custom`` scene with a ``brief``; here Claude writes the component, and
every component (Claude's, or one written by hand: ``"component": "x.tsx"``) must pass, in order:

1. a static check: only the allowed imports, nothing that reaches outside the page or changes between
   renders (network, storage, timers, Math.random, Date);
2. TypeScript (``tsc`` against the real scene types);
3. a probe render: frames of the scene alone, drawn by the real renderer;
4. a review (``studio.custom_review``): Claude looks at the probe frames next to the brief and fixes
   what does not match.

A problem in 1–3 goes back to Claude with the error (twice at most). A scene that still fails, or that
cannot be built (no ANTHROPIC_API_KEY), is drawn as its ``fallback`` library scene; the video is never
lost. Components that pass are cached in ``$HERMES_HOME/studio/scenes/`` (same brief, same component).

LIMITS below is the one place the real limits are written; the writer's prompt carries it too.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from orchestrator import llm
from orchestrator.brief.net import Http, HttpError

from .profile import Profile
from .settings import Keys, Settings
from .storyboard import Scene, Storyboard
from .voice import sentences

PROJECT = Path(__file__).with_name("remotion")
JOBS = PROJECT / ".jobs"  # per-job entry files live inside the project so its packages resolve
WPM = 196
FPS = 30
TSC_TIMEOUT = 180
STILL_TIMEOUT = 180
MAX_BYTES = 60_000
REPAIRS = 2

LIMITS = """What the pipeline can make (the real limits; anything inside them is fair game):
- Renderer: Remotion 4 = React + SVG + CSS (+ canvas) in headless Chrome, 1080×1920 at 30 fps. Every frame
  is drawn on its own from the frame number, so motion must be a pure function of useCurrentFrame():
  no CSS animations or transitions, timers, Math.random (use remotion's random(seed)) or Date.
- Anything drawable that way works: kinetic type, diagrams, charts, physics-looking motion, particles,
  flat or isometric illustration built from shapes, 2.5D with CSS 3D transforms, masks, gradients,
  morphing paths, counters, UI mockups, maps (d3-geo, world-atlas countries).
- Not possible: photoreal people, faces or real footage (unless a stock clip or your own image is
  provided as a file), lip-sync, true 3D models (no three.js), sounds made by the picture.
- Fonts: Inter, Montserrat, Anton, JetBrains Mono, and colour emoji. No network while rendering.
- Cost: the host has 2 CPU cores and 4 GB of memory; ~4.5 s of render per second of video. Keep a frame
  under ~2,000 SVG/DOM nodes and large blurs rare; render time is the price of a picture, not a ban.
- Voice: Kokoro or Edge TTS read English and Hindi (Devanagari); pauses and pace can be directed, single
  words cannot be stressed; on-screen *emphasis* does that job.
- Captions sit at the bottom (the lowest ~660 px); platform buttons cover the top ~230 px and right ~90 px."""

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
CODE = re.compile(r"```(?:tsx|typescript|ts|jsx)?\s*\n(.*?)```", re.DOTALL)
STUDIO = {"studio/motion": "src/motion", "studio/theme": "src/theme", "studio/types": "src/types"}

CONTRACT = """# The component contract
```tsx
import React from "react";
import {AbsoluteFill, Easing, interpolate, random, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {Arrive, usePop, revealAt, ENTERS, FEELS} from "studio/motion";   // optional helpers
import {useTheme, useProfile} from "studio/theme";                       // colours: theme.bg, panel, text, muted, accent, cool, bad, good; fonts: theme.sans, theme.monoFamily
import type {CustomScene} from "studio/types";                           // scene.props, scene.beats (s), scene.brief

export default function Scene({scene, frames}: {scene: CustomScene; frames: number}) {
  const frame = useCurrentFrame();   // 0 … frames-1, then ~10 more while the next scene comes in: clamp
  ...
}
```
- usePop(delay) is a 0→1 spring in the page's feel; revealAt(i, count, frames, scene.beats) is the frame
  item i should appear on when the narration has one sentence per item; <Arrive delay={n}> wraps a part
  in the page's entrance. The scene's own entrance, transition to the next scene, drift, punch-ins and captions are added for you.
- Layout: unless the scene says "full_bleed": true, the component draws in a 900 × ~1030 px box centred in
  the safe area (padding is done for you); full bleed owns the whole 1080×1920 frame (keep words clear of
  the bottom 660 px, where captions go).
- Allowed imports: """ + ", ".join(sorted(ALLOWED_IMPORTS)) + """. Nothing else.
- Time things to the sentences: an element appears when its sentence starts (scene.beats), never on a
  fixed timer that ignores the words.
- Refused before it runs: network, storage, timers, Math.random, Date, CSS animations or transitions,
  raw HTML. Then checked by TypeScript and by rendering real frames; a scene that fails is replaced by
  its fallback library scene.

""" + LIMITS

BUILD = """You are building ONE scene of a vertical short video as a Remotion component (React + TypeScript).
Make it look like the work of a top motion designer: clear, bold, every element earning its place,
motion that explains. The narration plays over it; the picture must show what the words say, as they say it.

# The scene
Brief (what the writer wants on screen): {brief}
Narration ({seconds:.1f} s, {frames} frames at 30 fps): {say}
Each sentence starts at (seconds from the scene's start): {beats}
Data the component receives as scene.props: {props}
Layout: {layout}

# The page's look (use these, through useTheme())
{theme}

{contract}

Here is a library scene for the house style (yours may look nothing like it):
```tsx
{example}
```

Answer with the complete component in one ```tsx block, nothing else."""

FIX = """The component below failed this check:
{problem}

Fix it and answer with the complete corrected component in one ```tsx block, nothing else.

```tsx
{code}
```"""

REVIEW = """These are frames of the scene you built, rendered for real ({stamps}). The brief was:
{brief}
Narration: {say}

Judge it as a demanding motion designer: does it show the brief clearly, is anything cut off, overlapping,
too small to read on a phone, empty, or off the page's colours? If it is good, answer exactly OK.
Otherwise answer with the complete improved component in one ```tsx block, nothing else.

```tsx
{code}
```"""


class CustomError(Exception):
    """One custom scene's problem; its fallback is drawn."""


@dataclass(frozen=True)
class Result:
    board: Storyboard  # custom scenes that failed replaced by their fallbacks
    entry: str  # entry file for the render, relative to remotion/ ("src/index.ts" when no custom scene)
    notes: tuple[str, ...]  # one line per custom scene: built, cached, given, or fell back and why


# ---------------------------------------------------------------- checks


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


def _on_disk(code: str, depth: int) -> str:
    """studio/* imports → the project's src/ (the folder is ``depth`` levels below remotion/)."""
    up = "../" * depth
    return re.sub(r"""(['"])studio/(motion|theme|types)\1""", lambda m: f'{m.group(1)}{up}src/{m.group(2)}{m.group(1)}', code)


def _write_entry(folder: Path, keys: list[str], depth: int) -> None:
    up = "../" * depth
    imports = "\n".join(f'import S{n} from "./{key}";' for n, key in enumerate(keys))
    views = ", ".join(f'"{key}": S{n} as CustomView' for n, key in enumerate(keys))
    folder.joinpath("index.tsx").write_text(
        f'import {{registerRoot}} from "remotion";\nimport {{registerCustom, type CustomView}} from "{up}src/custom";\n'
        f'import {{RemotionRoot}} from "{up}src/Root";\n{imports}\n\nregisterCustom({{{views}}});\n'
        f"registerRoot(RemotionRoot);\n", encoding="utf-8")
    folder.joinpath("tsconfig.json").write_text(json.dumps(
        {"extends": f"{up}tsconfig.json", "include": ["*.tsx"]}), encoding="utf-8")


def typecheck(folder: Path) -> str:
    done = subprocess.run([str(PROJECT / "node_modules/.bin/tsc"), "--noEmit", "-p", str(folder)], cwd=PROJECT,
                          capture_output=True, text=True, timeout=TSC_TIMEOUT, check=False)
    if done.returncode == 0:
        return ""
    errors = [ln for ln in (done.stdout + done.stderr).splitlines() if "error TS" in ln]
    return "TypeScript:\n" + "\n".join(errors[:15] or (done.stdout + done.stderr).splitlines()[-10:])


def probe(settings: Settings, folder: Path, props: dict[str, Any], at: list[int]) -> tuple[list[Path], str]:
    """Render frames ``at`` of the scene alone; (PNG files, the first error)."""
    (folder / "probe.json").write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    shots = []
    for frame in at:
        out = folder / f"probe-{frame:04d}.png"
        args = [str(PROJECT / "node_modules/.bin/remotion"), "still", str(folder.relative_to(PROJECT) / "index.tsx"),
                "Probe", str(out), f"--props={folder / 'probe.json'}", f"--frame={frame}", "--image-format=png",
                "--scale=0.5", "--log=error"]
        if settings.video_browser:
            args.append(f"--browser-executable={settings.video_browser}")
        try:
            done = subprocess.run(args, cwd=PROJECT, capture_output=True, text=True, timeout=STILL_TIMEOUT, check=False)
        except subprocess.TimeoutExpired:
            return shots, f"frame {frame} took over {STILL_TIMEOUT} s to draw"
        if done.returncode != 0 or not out.is_file():
            lines = [ln for ln in (done.stderr or done.stdout).splitlines() if ln.strip()]
            return shots, f"frame {frame} failed to draw: " + "\n".join(lines[-8:])[:1500]
        shots.append(out)
    return shots, ""


# ---------------------------------------------------------------- one scene


def estimate(say: str) -> tuple[int, list[float]]:
    """The scene's length and sentence starts before the voice exists (196 words a minute)."""
    said = sentences(say)
    counts = [len(s.split()) for s in said]
    starts, at = [], 0.0
    for n in counts:
        starts.append(round(at, 2))
        at += n / WPM * 60 + 0.15
    return max(FPS, round(at * FPS)), starts


def probe_props(scene: Scene, key: str, look: Profile) -> dict[str, Any]:
    frames, beats = estimate(scene.say)
    fields = json.loads(json.dumps(dict(scene.fields), default=dict))
    return {"profile": look.render_props(), "frames": frames,
            "scene": {"type": "custom", "key": key, "brief": fields["brief"], "props": fields["props"],
                      "full_bleed": fields["full_bleed"], "start": 0, "end": frames / FPS, "beats": beats,
                      "enter": scene.enter, "exit": scene.exit, "transition": "", "emoji": ""}}


@dataclass
class Smith:
    http: Http
    keys: Keys
    settings: Settings
    look: Profile
    folder: Path  # remotion/.jobs/<job>
    calls: int = 0

    def _claude(self, prompt: str, step: str, images: tuple[bytes, ...] = ()) -> str:
        self.calls += 1
        return llm.claude(self.http, self.keys.claude, self.settings.claude_model, prompt, workflow="studio",
                          step=step, effort=self.settings.claude_effort, images=images, max_tokens=32000)

    def check(self, key: str, code: str, scene: Scene) -> tuple[str, list[Path]]:
        """The first problem ("" = none) and the probe frames."""
        wrong = static_problems(code)
        if wrong:
            return "Not allowed:\n- " + "\n- ".join(wrong), []
        place = self.folder / key
        place.mkdir(parents=True, exist_ok=True)
        (place / f"{key}.tsx").write_text(_on_disk(code, 3), encoding="utf-8")
        _write_entry(place, [key], 3)
        types = typecheck(place)
        if types:
            return types, []
        props = probe_props(scene, key, self.look)
        frames = props["frames"]
        shots, error = probe(self.settings, place, props, sorted({min(frames - 1, 20), frames // 2, max(0, frames - 8)}))
        return error, shots

    def build(self, key: str, scene: Scene) -> str:
        """Claude writes the component; checked and repaired; returns code that passed (or raises)."""
        fields = scene.fields
        frames, beats = estimate(scene.say)
        example = (PROJECT / "src/scenes/Bullets.tsx").read_text(encoding="utf-8")
        layout = ("full bleed: you own the whole 1080×1920 frame (keep words clear of the bottom 660 px)"
                  if fields["full_bleed"] else "a 900 × ~1030 px box centred in the safe area (padding is done for you)")
        theme = json.dumps(self.look.render_props()["theme"])
        ask = BUILD.format(brief=fields["brief"], seconds=frames / FPS, frames=frames, say=scene.say, beats=beats,
                           props=json.dumps(dict(fields["props"]), ensure_ascii=False), layout=layout, theme=theme,
                           contract=CONTRACT, example=example)
        code = _code(self._claude(ask, "custom-scene"))
        for attempt in range(REPAIRS + 1):
            problem, shots = self.check(key, code, scene)
            if not problem:
                break
            if attempt == REPAIRS:
                raise CustomError(headline(problem))
            code = _code(self._claude(FIX.format(problem=problem, code=code), "custom-scene-fix"))
        if self.settings.custom_review and shots:
            stamps = ", ".join(f"frame {p.stem.split('-')[1].lstrip('0') or '0'}" for p in shots)
            answer = self._claude(REVIEW.format(stamps=stamps, brief=fields["brief"], say=scene.say, code=code),
                                  "custom-scene-review", tuple(p.read_bytes() for p in shots))
            if answer.strip() != "OK" and CODE.search(answer):
                better = _code(answer)
                problem, _shots = self.check(key, better, scene)
                code = code if problem else better  # a review that breaks the scene is ignored
        return code


def headline(problem: str) -> str:
    """The first line that says what is wrong (not a "TypeScript:" or "Not allowed:" heading)."""
    lines = [ln.strip(" -") for ln in problem.splitlines() if ln.strip() and not ln.rstrip().endswith(":")]
    return (lines[0] if lines else problem.strip())[:200]


def _code(answer: str) -> str:
    found = CODE.search(answer)
    return (found.group(1) if found else answer).strip() + "\n"


def cache_key(scene: Scene, look: Profile) -> str:
    f = scene.fields
    raw = json.dumps([f["brief"], scene.say, f["props"], f["full_bleed"], look.name], default=dict, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _fallback(scene: Scene) -> Scene:
    fields = dict(scene.fields["fallback"])
    kind = fields.pop("type")
    return replace(scene, type=kind, fields=MappingProxyType(fields))


def _one(smith: Smith, key: str, scene: Scene, folder: Path, home: Path) -> tuple[str, str]:
    """(code, how) for one custom scene; raises CustomError when it must fall back."""
    given = scene.fields["component"]
    cached = home / "studio" / "scenes" / f"{cache_key(scene, smith.look)}.tsx"
    if given or cached.is_file():
        code = (folder / given if given else cached).read_text(encoding="utf-8")
        problem, _shots = smith.check(key, code, scene)
        if problem:
            raise CustomError(f"{'its component' if given else 'the cached component'}: {headline(problem)}")
        return code, "given" if given else "cached"
    if not smith.keys.claude:
        raise CustomError("no ANTHROPIC_API_KEY to build it")
    try:
        code = smith.build(key, scene)
    except (HttpError, ValueError) as exc:
        raise CustomError(f"Claude could not build it: {str(exc)[:160]}") from None
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(code, encoding="utf-8")
    return code, "built"


def prepare(http: Http, keys: Keys, settings: Settings, home: Path, board: Storyboard, look: Profile,
            job: Path) -> Result:
    """Every custom scene built and checked, or replaced by its fallback; the render's entry file."""
    customs = [n for n, s in enumerate(board.scenes) if s.type == "custom"]
    if not customs:
        return Result(board, "src/index.ts", ())
    folder = JOBS / job.name
    smith = Smith(http, keys, settings, look, folder)
    scenes, passed, notes = list(board.scenes), {}, []
    for n in customs:
        key = f"scene{n + 1:02d}"
        scene = scenes[n]
        try:
            code, how = _one(smith, key, scene, board.folder, home)
        except CustomError as exc:
            scenes[n] = _fallback(scene)
            notes.append(f"scene {n + 1}: custom scene drawn as its fallback ({scenes[n].type}): {exc}")
            continue
        passed[key] = code
        scenes[n] = replace(scene, fields=MappingProxyType({**scene.fields, "key": key}))
        notes.append(f"scene {n + 1}: custom scene {how}")
    if not passed:
        shutil.rmtree(folder, ignore_errors=True)
        return Result(replace(board, scenes=tuple(scenes)), "src/index.ts", tuple(notes))
    for key, code in passed.items():  # the render's own entry: every component that passed
        (folder / f"{key}.tsx").write_text(_on_disk(code, 2), encoding="utf-8")
        (job / "custom").mkdir(exist_ok=True)
        (job / "custom" / f"{key}.tsx").write_text(code, encoding="utf-8")  # kept with the job
    _write_entry(folder, list(passed), 2)
    if smith.calls:
        notes.append(f"{smith.calls} Claude call(s) for custom scenes")
    return Result(replace(board, scenes=tuple(scenes)), str((folder / "index.tsx").relative_to(PROJECT)), tuple(notes))


def clean(entry: str) -> None:
    """Removes a job's entry folder after its render (the components are kept in the job folder)."""
    if entry.startswith(".jobs/"):
        shutil.rmtree(PROJECT / Path(entry).parent, ignore_errors=True)
