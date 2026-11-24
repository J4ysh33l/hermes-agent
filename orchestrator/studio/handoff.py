"""Claude on your plan, through the handoff repo (orchestrator/HANDOFF.md): used when there is no
ANTHROPIC_API_KEY (``studio.claude_via``). Asynchronous, which suits the overnight queue.

Hermes commits ``studio/<job>/request.md`` (the same writing prompt the API gets, plus the custom-scene
component contract) and opens an issue; the Claude scheduled task writes ``storyboard.json`` and, for
each custom scene, its component ``sceneNN.tsx``, commits them and closes the issue. The queue picks the
answer up, runs every check, and on problems sends one fix request (``fix-1.md`` → ``storyboard-fix1.json``).
The contract the scheduled task follows: ``studio/HANDOFF.md`` (copy it into the repo).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http
from orchestrator.handoff import Handoff, HandoffError

from . import custom, writer
from .profile import Profile

COMPONENT = re.compile(r"^[a-z0-9_-]{1,40}\.tsx$")
FIXES = 1

REQUEST = """# Studio request {job}

Write a storyboard for a vertical short video, following the brief below exactly.

**Answer files (commit them to the default branch, then close the issue):**
- `studio/{job}/{answer}`: the storyboard JSON, nothing else in the file.
- For every scene with `"type": "custom"` (hooks included): its component as `studio/{job}/sceneNN.tsx`
  (NN = the scene's number, the hook is 01), and set that scene's `"component": "sceneNN.tsx"`.
  Follow the component contract at the end. Make each one as good as a top motion designer would.

---

{prompt}

---

{contract}

A library scene for the house style:
```tsx
{example}
```
"""


def repo(http: Http, secrets: Secrets, name: str) -> Handoff:
    return Handoff(http, secrets, name)


def answer_name(round_: int) -> str:
    return "storyboard.json" if round_ == 0 else f"storyboard-fix{round_}.json"


def ask(hand: Handoff, job: str, look: Profile, notes: str, seconds: float, round_: int = 0,
        problems: list[str] | None = None, previous: Any = None) -> int:
    """Commits the request (or a fix request) and opens its issue; returns the issue number."""
    seconds = seconds or float(look.section("writing")["seconds"])
    text = writer.prompt(look, notes, seconds, writer.target_words(look, seconds))
    if round_:
        text = writer.REPAIR.format(problems="\n".join(f"- {p}" for p in problems or []),
                                    draft=json.dumps(previous, ensure_ascii=False, indent=1))
    body = REQUEST.format(job=job, answer=answer_name(round_), prompt=text, contract=custom.CONTRACT,
                          example=(custom.PROJECT / "src/scenes/Bullets.tsx").read_text(encoding="utf-8"))
    name = "request.md" if round_ == 0 else f"fix-{round_}.md"
    return hand.send({f"studio/{job}/{name}": body}, f"studio {job}" + (f" fix {round_}" if round_ else ""),
                     f"Folder: studio/{job}/ — follow studio/HANDOFF.md; the request is studio/{job}/{name}.")


def collect(hand: Handoff, job: str, round_: int, folder: Path) -> Any:
    """The answer once committed (with its components saved into ``folder``), or None while waiting."""
    text = hand.read(f"studio/{job}/{answer_name(round_)}")
    if text is None:
        return None
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise HandoffError(f"the storyboard Claude committed is not JSON: {exc}") from None
    scenes = [h.get("scene") for h in raw.get("hooks") or [] if isinstance(h, dict)] + list(raw.get("scenes") or [])
    for scene in scenes:
        name = scene.get("component", "") if isinstance(scene, dict) else ""
        if not name:
            continue
        if not COMPONENT.match(name):
            raise HandoffError(f"component name {name!r} is not like scene02.tsx")
        code = hand.read(f"studio/{job}/{name}")
        if code is None:
            scene.pop("component")  # missing: the scene is built by the API if it can, else its fallback is drawn
            continue
        folder.joinpath(name).write_text(code, encoding="utf-8")
    return raw
