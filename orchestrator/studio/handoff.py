"""Claude on your plan, through the handoff repo (orchestrator/HANDOFF.md): used when there is no
ANTHROPIC_API_KEY (``studio.claude_via``). Asynchronous, which suits the overnight queue.

The three writing calls (``brief.py``) become two issues, one at a time, each body the whole prompt:

1. ``script + direction`` (``brief.writing``): in one run, Claude writes and checks
   ``studio/<job>/script.json``, then ``studio/<job>/storyboard.json`` for it;
2. ``animation`` (when there are custom scenes): one ``sceneNN.tsx`` per custom scene.

A fix goes back as its own issue: a failed script redoes both; a failed storyboard, the direction only.

Before the first, Hermes commits ``studio/<job>/rules.json`` (the job's ``rules.Params``) and keeps
``tools/check.py`` plus ``tools/studio/`` (``rules.py`` and the modules it needs, copied as they are) up to
date, so Claude runs the same checks as Hermes before handing in. An answer is read once Claude has closed
its issue; ``queue.py`` checks it again and moves the job on, or sends a fix request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http
from orchestrator.handoff import Handoff

from . import brief, rules

HERE = Path(__file__).parent
TOOLS = ("direction.py", "text.py", "storyboard.py", "rules.py")  # standard library only, copied as they are

CHECK = '''"""Checks a studio answer before it is handed in. Written by Hermes; the rules are tools/studio/rules.py.

    python3 tools/check.py script studio/<job>       script.json
    python3 tools/check.py direction studio/<job>    storyboard.json (against script.json)
    python3 tools/check.py animation studio/<job>    the custom scenes' components
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from studio import rules  # noqa: E402


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except (OSError, ValueError) as exc:
        return None, f"{path.name}: {exc}"


def problems(stage, folder):
    params = rules.Params.loads((folder / "rules.json").read_text(encoding="utf-8"))
    script, wrong = load(folder / "script.json")
    if stage == "script":
        return [wrong] if wrong else rules.check_script(script, params)
    board, wrong_board = load(folder / "storyboard.json")
    if wrong or wrong_board:
        return [w for w in (wrong, wrong_board) if w]
    board = rules.take_wishes(board)[0]
    if stage == "direction":
        return rules.check_direction(board, script, params)
    names = list(rules.component_names(board).values())
    codes = {n: (folder / n).read_text(encoding="utf-8") if (folder / n).is_file() else None for n in names}
    return rules.check_components(codes, names)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("script", "direction", "animation"):
        sys.exit(__doc__)
    found = problems(sys.argv[1], Path(sys.argv[2]))
    print("\\n".join(f"- {p}" for p in found) if found else "OK: ready to hand in")
    sys.exit(1 if found else 0)
'''


def repo(http: Http, secrets: Secrets, name: str) -> Handoff:
    return Handoff(http, secrets, name)


def tools() -> dict[str, str]:
    files = {"tools/check.py": CHECK, "tools/studio/__init__.py": ""}
    files.update({f"tools/studio/{name}": (HERE / name).read_text(encoding="utf-8") for name in TOOLS})
    return files


def start(hand: Handoff, job: str, params: rules.Params, prompt: str) -> int:
    """The job's first issue (script and direction), with its rules and the up-to-date checker."""
    for path, text in tools().items():
        hand.put(path, text)
    return hand.send({f"studio/{job}/rules.json": params.dumps()}, f"studio {job}: {brief.WRITING}", prompt)


def ask(hand: Handoff, job: str, stage: str, prompt: str, round_: int = 0) -> int:
    """A later call (direction, animation) or a fix request; returns the issue number."""
    return hand.send({}, f"studio {job}: {stage}" + (f" fix {round_}" if round_ else ""), prompt)


def answer(hand: Handoff, job: str, stage: str) -> tuple[Any, str]:
    """(the stage's JSON answer, "") or (None, what is wrong with it)."""
    name = brief.ANSWERS[stage]
    text = hand.read(f"studio/{job}/{name}")
    if text is None:
        return None, f"{name} is missing: write it to studio/{job}/{name}"
    try:
        return json.loads(text), ""
    except ValueError as exc:
        return None, f"{name} is not JSON: {exc}"


def components(hand: Handoff, job: str, names: list[str]) -> dict[str, str | None]:
    return {name: hand.read(f"studio/{job}/{name}") for name in names}

