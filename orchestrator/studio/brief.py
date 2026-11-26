"""The three writing calls' prompts, filled for one job (``prompts/*.md``), and the job's ``rules.Params``.

1. ``script``: the head writer: words only (the page's voice, the format's beats, hooks, jokes, how to
   write for a text-to-speech voice, the notes).
2. ``direction``: the director: pictures only, the script locked (the page's look, how these videos look,
   the scene library and its limits, custom scenes, the notes for on-screen facts).
3. ``animation``: the motion designer: every custom scene's component in one answer (the look, every
   scene in order, the briefs, the component contract, one library scene as an example).

A prompt ends with how to answer: ``HANDOFF`` (Claude on your plan writes the file in the handoff repo and
runs ``tools/check.py``) or ``API`` (the model answers with the JSON or the components). ``fix`` wraps a
stage's prompt with the problems found and the previous answer.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from string import Template
from typing import Any

from . import custom, rules, storyboard, video
from .profile import Profile

PROMPTS = Path(__file__).with_name("prompts")
PLAYBOOK = Path(__file__).with_name("PLAYBOOK.md")
WPM = 170  # words a minute at voice speed 1.0 with directions and pauses, measured on a real 55 s short
# (152 words); scales with the profile's speed (1.15 by default → ~196)
FORMATS = {"explainer": "A", "news": "B", "how-it-works": "C", "business-case": "D", "hindi-explainer": "E"}
LANGUAGES = {"en": "English", "hi": "Hindi, written in Devanagari",
             "hinglish": "Hinglish: Hindi typed in Latin script, mixed with English, as people text"}
NEEDS_FILE = ("image", "meme")  # image comes back as stock b-roll when the page allows it (broll.py)
MEDIA = {
    False: '- No "src" fields: there are no image files, so no image or meme scenes (a custom scene can draw instead).',
    True: '- Image scenes are stock photos: "src": "stock:<2–4 plain words naming a common subject>" (e.g. '
          '"stock:bullet train", "stock:city street at night"), searched among public-domain photos and shown '
          'full screen with a slow push. Name things that are photographed often, not moments ("stock:train '
          'cleaning crew" finds nothing); add a "caption". At most 1 in 3 scenes; a scene with nothing found '
          'becomes a title card. No other "src".',
}
STAGES = ("script", "direction", "animation")
WRITING = "script + direction"  # the handoff's first call: both, in one run (``writing``)
ANSWERS = {"script": "script.json", "direction": "storyboard.json"}

# Every step of a run re-sends the whole run so far, so a run hands in with as few commands as it can:
# the answer files, the check and the hand-in in ONE command (26 Nov: 9 steps, ~230k tokens re-read).
HAND_IN = ' && git add studio/$job && git commit -qm "studio $job" && sh tools/close.sh'
ONE_COMMAND = ("Write the files with quoted heredocs (cat > file <<'EOF'), check and hand in, all in ONE shell command:\n"
               "    {files} && {check}" + HAND_IN + "\n"
               "If a check prints problems, fix exactly those and run the same command again. Run nothing else: no reading "
               "files back, no listing folders, no git status, no summary.\n")
HANDOFF = {
    "script": "\n" + ONE_COMMAND.format(files="<write studio/$job/script.json>",
                                        check="python3 tools/check.py script studio/$job"),
    "direction": "\n" + ONE_COMMAND.format(files="<write studio/$job/storyboard.json>",
                                           check="python3 tools/check.py direction studio/$job"),
    "animation": "\n" + ONE_COMMAND.format(files="<write each component to studio/$job/<its file name>>",
                                           check="python3 tools/check.py animation studio/$job")
                 + "That check refuses imports and APIs outside the contract. TypeScript and a real render run on my "
                   "server after you finish; a scene that fails comes back to you once with its error.\n",
}
API = {
    "script": "\nAnswer with that JSON only.\n",
    "direction": "\nAnswer with that JSON only.\n",
    "animation": "\nAnswer with one ```tsx block per scene, each starting with the line `// file: <its file name>`.\n",
}


def _fill(name: str, **values: Any) -> str:
    return Template((PROMPTS / f"{name}.md").read_text(encoding="utf-8")).substitute(
        {k: str(v) for k, v in values.items()})


def _ending(stage: str, job: str, handoff: bool) -> str:
    return Template((HANDOFF if handoff else API)[stage]).substitute(job=job)


# ---------------------------------------------------------------- the page


def target_words(look: Profile, seconds: float) -> int:
    return round(seconds / 60 * WPM * float(look.section("voice")["speed"]))


def seconds_of(look: Profile, seconds: float) -> float:
    return seconds or float(look.section("writing")["seconds"])


def footage(look: Profile) -> bool:
    return look.section("elements")["broll"] != "off"


def allowed_scenes(look: Profile) -> list[str]:
    """The library types this page uses (all unless its profile lists some), plus custom, always; image
    scenes (as stock b-roll) when the page allows b-roll."""
    listed = list(look.section("elements")["scenes"]) or [s for s in storyboard.SCHEMA if s != "custom"]
    return [s for s in listed if s in storyboard.SCHEMA and s != "custom"
            and (s not in NEEDS_FILE or (footage(look) and s == "image"))] + ["custom"]


def countries() -> tuple[str, ...]:
    """The map's country names, when the renderer is installed here (otherwise checked at render time)."""
    if not video.WORLD.is_file():
        return ()
    data = json.loads(video.WORLD.read_text(encoding="utf-8"))
    return tuple(sorted(g["properties"]["name"] for g in data["objects"]["countries"]["geometries"]))


def params(look: Profile, notes: str, seconds: float) -> rules.Params:
    return rules.Params(target_words(look, seconds_of(look, seconds)), tuple(look.section("writing")["avoid"]),
                        tuple(allowed_scenes(look)), footage(look), notes.strip(), countries())


def _section(pattern: str) -> str:
    found = re.search(pattern, PLAYBOOK.read_text(encoding="utf-8"), re.MULTILINE | re.DOTALL)
    return found.group(0).strip() if found else ""


def _families(look: Profile) -> list[str]:
    wanted = [h for h in look.section("writing")["hooks"] if h in rules.HOOKS]
    return wanted + [h for h in rules.HOOKS if h not in wanted]


def look_lines(look: Profile) -> str:
    t, m, c = look.section("theme"), look.section("motion"), look.section("captions")
    return "\n".join([
        *([f"- {look.description}"] if look.description else []),
        f"- Colours: background {t['bg']}, panels {t['panel']}, text {t['text']}, muted {t['muted']}, accent "
        f"{t['accent']} (the spoken caption word, big numbers), cool {t['cool']} (*emphasised* words), bad "
        f"{t['bad']}, good {t['good']}; background style {t['background']}.",
        f"- Fonts: {t['font']} for text, {t['mono']} for code.",
        f"- Motion: a {m['feel']} feel; scenes enter with {m['enter']} and leave with {m['exit']}; "
        f"{m['transition']} between scenes.",
        f"- Captions: {c['words']} words at a time, {c['size']} px{', upper case' if c['upper'] else ''}, "
        f"in the bottom 660 px."])


# ---------------------------------------------------------------- the three prompts


def script(look: Profile, notes: str, seconds: float, job: str, handoff: bool) -> str:
    return _script(look, notes, seconds, job) + _ending("script", job, handoff)


def _script(look: Profile, notes: str, seconds: float, job: str) -> str:
    w, p = look.section("writing"), params(look, notes, seconds)
    examples = "".join(f"\nA script this page liked:\n<example>\n{e}\n</example>\n" for e in w["examples"])
    wpm = round(WPM * float(look.section("voice")["speed"]))
    return _fill("script", job=job, format=w["format"], language=LANGUAGES[w["language"]],
                 seconds=round(seconds_of(look, seconds)), words=p.words, low=p.low, high=p.high, wpm=wpm,
                 tone=w["tone"] or "plain", humour=w["humour"] or "none",
                 avoid=", ".join(f'"{a}"' for a in dict.fromkeys((*w["avoid"], *rules.ALWAYS_AVOID))),
                 examples=examples, beats=_section(rf"^### {FORMATS[w['format']]}\. .*?(?=^### |^---)"),
                 families=", ".join(_families(look)[:3]),
                 hook_bank="\n".join(f"- {name}: {template}" for name, template in rules.HOOKS.items()),
                 notes=notes.strip())


def direction(look: Profile, notes: str, script_raw: dict[str, Any], job: str, handoff: bool) -> str:
    return _direction(look, notes.strip(), json.dumps(script_raw, ensure_ascii=False, indent=1), job,
                      str(script_raw.get("title", ""))) + _ending("direction", job, handoff)


def _direction(look: Profile, notes: str, script_text: str, job: str, title: str) -> str:
    return _fill("direction", job=job, script=script_text, look=look_lines(look),
                 types=", ".join(allowed_scenes(look)), scene_library=storyboard.__doc__ or "",
                 media=MEDIA[footage(look)], limits=custom.LIMITS, notes=notes, title=title)


WRITING_HEAD = """# Studio job $job · script + direction, in one run

Two jobs in order, both in this run. Part 1: as the head writer, write the script and check it.
Part 2: as the director, write the storyboard for the script you wrote, and check it. The custom
scenes' animation is a separate, later job: in part 2 you only describe them (brief and props).

"""
WRITING_END = """
## Handing in both, in ONE command
Think both parts through first (the storyboard copies the script's words), then write every file with
quoted heredocs (cat > file <<'EOF'), check and hand in, all in ONE shell command:
    <write studio/$job/research.txt, script.json and storyboard.json> && python3 tools/check.py script studio/$job && python3 tools/check.py direction studio/$job""" + HAND_IN + """
If a check prints problems, fix exactly those and run the same command again. Run nothing else: no reading
files back, no listing folders, no git status, no summary.
"""


RESEARCH_PART = """## Part 0: research, by a subagent
Before part 1, start ONE subagent with the Agent tool, model "$model", with exactly this prompt:
"Read studio/$job/research-brief.md and do what it says with web search. Reply with only the fact lines."
Its fact lines, as they are, go in `studio/$job/research.txt` (written in your one final command). They count as part of the notes below:
use them in parts 1 and 2 like the notes (the checks read research.txt too). Do no searching yourself.
If the subagent finds nothing, write an empty research.txt and go on with the notes alone.

"""


def writing(look: Profile, notes: str, seconds: float, job: str, researcher: str = "") -> str:
    """The handoff's first call: the script, then the direction for it, in one run (one fixed cost
    instead of two; the director works with the script fresh in mind). The same checks gate each part.
    ``researcher`` ("sonnet" / "haiku"): a part 0 first, where a subagent on that model does the web
    search from research-brief.md, so the long search results stay in its context, not this run's."""
    part2 = _direction(look, "(the same notes as in part 1)", "(your script.json from part 1)", job,
                       "(your script's title)")
    part0 = Template(RESEARCH_PART).substitute(model=researcher, job=job) if researcher else ""
    return (Template(WRITING_HEAD).substitute(job=job) + part0 + "---\n\n" + _script(look, notes, seconds, job)
            + "\n\n---\n\n" + part2 + Template(WRITING_END).substitute(job=job))


def _outline(board: dict[str, Any]) -> str:
    scenes = [("1 (hook 1)", board["hooks"][0]), *((str(n), s) for n, s in enumerate(board["scenes"], 2))]
    return "\n".join(f"{n}. [{s.get('type')}] {s.get('say', '')}" for n, s in scenes)


def _customs(board: dict[str, Any], only: set[str] | None = None) -> str:
    names = rules.component_names(board)
    scenes = {f"hook {n}": h for n, h in enumerate(board["hooks"], 1)}
    scenes.update({f"scene {n}": s for n, s in enumerate(board["scenes"], 2)})
    blocks = []
    for where, name in names.items():
        if only is not None and name not in only:
            continue
        s = scenes[where]
        layout = "full bleed (the whole 1080×1920 frame)" if s.get("full_bleed") else "the 900 × ~1030 px box"
        blocks.append(f"### {name} ({where})\nSays: {s.get('say', '')}\nBrief: {s.get('brief', '')}\n"
                      f"Props: {json.dumps(s.get('props') or {}, ensure_ascii=False)}\nLayout: {layout}")
    return "\n\n".join(blocks)


def animation(look: Profile, board: dict[str, Any], title: str, job: str, handoff: bool,
              only: set[str] | None = None) -> str:
    """``board``: the director's storyboard.json; ``only``: just these files (a fix)."""
    example = (custom.PROJECT / "src/scenes/Bullets.tsx").read_text(encoding="utf-8").strip()
    return _fill("animation", job=job, title=title, look=look_lines(look), outline=_outline(board),
                 customs=_customs(board, only), feel=look.section("motion")["feel"], contract=custom.CONTRACT,
                 example=example) + _ending("animation", job, handoff)


def fix(stage: str, job: str, prompt: str, problems: list[str], previous: str) -> str:
    return _fill("fix", job=job, stage=stage, problems="\n".join(f"- {p}" for p in problems),
                 previous=previous.strip(), prompt=prompt)
