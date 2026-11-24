"""Claude's two jobs for the watcher, through the handoff repo (``orchestrator.handoff``):

- **setup**: for a page the script reads as plain links, Claude finds the steadiest source for what
  you care about (a job board's JSON feed, RSS, the page with a ``match`` filter) and writes
  ``spec.json``. Hermes checks it (``sources.check_spec``), switches the watch over and reads it once.
- **note**: when new items appear, Claude reads them (and the pages behind them, when it can) and
  writes ``note.md``: what is new, what matters to you and why, in a few lines.

Hermes never waits for Claude: the script's own message about a change goes out at once; Claude's
note follows on a later run. The contract Claude follows is ``HANDOFF.md`` (copy it into the repo).
"""

from __future__ import annotations

import json
from datetime import datetime

from orchestrator.handoff import Handoff

from . import sources

SETUP = """# Watch {number} setup: {name}

Page: {url}
What I care about: {what}
How the script reads it now: `{spec}` (it found {count} links)

Find the steadiest machine-readable source for **what I care about** on this page and write
`{folder}/spec.json`, following `HANDOFF.md` § Setup. Then close this issue.
"""

NOTE = """# Watch {number}: {name} — {count} new

Page: {url}
What I care about: {what}
About me: {about}

New since {since}:
{new}
{gone}
Write `{folder}/note.md` following `HANDOFF.md` § Change note. Then close this issue.
"""


def folder(number: str, now: datetime, job: str) -> str:
    return f"watch/{number}-{job}-{now:%Y%m%d-%H%M%S}"


def ask_setup(repo: Handoff, number: str, w: dict, count: int, now: datetime) -> dict:
    where = folder(number, now, "setup")
    body = SETUP.format(number=number, name=w["name"], url=w["url"], what=w["what"] or "anything new",
                        spec=json.dumps(w["spec"]), count=count, folder=where)
    issue = repo.send({f"{where}/request.md": body}, f"Watch {number} setup: {w['name']}", body)
    return {"job": "setup", "folder": where, "issue": issue, "asked": now.isoformat()}


def ask_note(repo: Handoff, number: str, w: dict, new: list[sources.Item], gone: int, about: str,
             since: str, now: datetime) -> dict:
    where = folder(number, now, "note")
    body = NOTE.format(number=number, name=w["name"], url=w["url"], what=w["what"] or "anything new",
                       about=about or "(not given)", count=len(new), since=since,
                       new="\n".join(f"- {i.title} — {i.link}" for i in new),
                       gone=f"\n{gone} items are gone since then.\n" if gone else "", folder=where)
    issue = repo.send({f"{where}/request.md": body}, f"Watch {number}: {w['name']} — {len(new)} new", body)
    return {"job": "note", "folder": where, "issue": issue, "asked": now.isoformat()}


def answer(repo: Handoff, ask: dict) -> str | None:
    """Claude's file for this request, or None while it is not written."""
    return repo.read(f"{ask['folder']}/{'spec.json' if ask['job'] == 'setup' else 'note.md'}")


def parse_spec(text: str) -> tuple[dict | None, list[str]]:
    try:
        spec = json.loads(text)
    except ValueError as exc:
        return None, [f"spec.json is not JSON: {exc}"]
    problems = sources.check_spec(spec)
    return (None, problems) if problems else (spec, [])
