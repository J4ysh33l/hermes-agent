"""Claude's job for the watcher, through the handoff repo (``orchestrator.handoff``): setup research.

For a page the script reads as plain links, Claude finds the steadiest source for what you care about
(a job board's JSON feed, RSS, the JSON the page loads, the page with a ``match`` filter) and writes
``spec.json``. Hermes checks it (``sources.check_spec``), switches the watch over and reads it once.
Notes on changes are Gemini's (``note``), not Claude's. The issue body (``SETUP``) is Claude's whole task.
"""

from __future__ import annotations

import json
from datetime import datetime

from orchestrator.handoff import Handoff

from . import sources

SETUP = """# Watch {number} setup: {name}

Hermes watches web pages with a script and tells its owner on Telegram when something is added. Your
one job: find the best way for the script to read this page.

Page: {url}
What the owner cares about: {what}
How the script reads it now: `{spec}` (it found {count} links)

The script reads the page as plain links, which is noisy and breaks when the page is redesigned. Find
the **steadiest machine-readable source** for what the owner cares about, in this order:

1. **The site's job board API**, if the careers page is hosted by one. Look at the page source and
   network calls (`curl -sL`): links or scripts mentioning greenhouse, lever, ashbyhq, smartrecruiters,
   workable, keka, darwinbox, zohorecruit, freshteam, recruitee, bamboohr, personio, teamtailor,
   workday. Use its public, unauthenticated JSON endpoint for this company.
2. **An RSS/Atom feed** (`<link rel="alternate" type="application/rss+xml">`, `/feed`, `/rss`).
3. **A JSON endpoint the page itself loads** (no login, no cookies, a stable URL).
4. **The page's links**, with a `match` pattern so only the relevant links count (e.g. `/jobs/|/careers/`
   or `\\.pdf$` for uploads).

Rules:
- Use only what you can see on the pages. Never invent a job, a date, a salary, a location or a
  deadline. If a page won't open, say so.
- Public pages only: don't sign in anywhere, don't submit forms.
- **Test before you write it:** fetch your URL with `curl -sL` and check that it returns the items
  (count them). Write nothing you haven't fetched successfully.

## Your answer: `{folder}/spec.json`, one JSON object

```json
{{"kind": "json", "url": "https://api.lever.co/v0/postings/acme?mode=json",
 "items": "", "title": "text", "link": "hostedUrl",
 "note": "Lever job feed: 14 open roles, steadier than the careers page"}}
```

- `kind`: `json`, `feed` (RSS/Atom) or `html` (the page's links).
- `url`: what to fetch (http or https).
- For `json`: `items` is the dot path to the list of items (`""` when the answer itself is the list,
  `jobs`, `data.postings`); `title` is the field holding the item's name (a dot path is fine); then
  either `link` (the field with the item's public URL) or `link_template` (built from the item's
  top-level fields: `"https://jobs.example.com/{{id}}"`).
- `match` (optional): a regular expression; only items whose title or link match are kept. Use it to
  cut noise, not to guess the owner's preferences: a wider watch is better than a missed opening.
- `note`: one line for the owner: what source you chose and why, with the item count you saw.

If nothing beats the page's links, write `{{"kind": "html", "url": "<the page>", "match": "…", "note": "…"}}`
with a `match` that keeps the relevant links. If the page can't be read at all, write
`{{"kind": "html", "url": "<the page>", "note": "Couldn't open it: <why>"}}`.

Write only that file, commit it to main, push, then close this issue. Hermes checks the spec (kind,
url, a valid `match`), reads it once and keeps the old way if it fails.
"""


def folder(number: str, now: datetime, job: str) -> str:
    return f"watch/{number}-{job}-{now:%Y%m%d-%H%M%S}"


def ask_setup(repo: Handoff, number: str, w: dict, count: int, now: datetime) -> dict:
    where = folder(number, now, "setup")
    body = SETUP.format(number=number, name=w["name"], url=w["url"], what=w["what"] or "anything new",
                        spec=json.dumps(w["spec"]), count=count, folder=where)
    issue = repo.send({f"{where}/request.md": body}, f"Watch {number} setup: {w['name']}", body)
    return {"job": "setup", "folder": where, "issue": issue, "asked": now.isoformat()}


def answer(repo: Handoff, ask: dict) -> str | None:
    """Claude's file for this request, or None while it is not written."""
    return repo.read(f"{ask['folder']}/spec.json")


def parse_spec(text: str) -> tuple[dict | None, list[str]]:
    try:
        spec = json.loads(text)
    except ValueError as exc:
        return None, [f"spec.json is not JSON: {exc}"]
    problems = sources.check_spec(spec)
    return (None, problems) if problems else (spec, [])
