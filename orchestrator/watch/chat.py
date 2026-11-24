"""``/watch`` in Telegram: add, list and change watches. No model; Claude is asked through the
handoff repo when a page needs research or a change needs a note."""

from __future__ import annotations

import re
from pathlib import Path

from orchestrator.brief.net import Http
from orchestrator.brief.store import default_state_dir

from . import sources, work

HELP = """**/watch** — tells you when a page adds something: job openings, new uploads, new posts
/watch add <link> [what you care about] — e.g. /watch add https://jobs.lever.co/acme backend roles in India
  Careers pages on Greenhouse, Lever, Ashby, SmartRecruiters or Workable are read from their job feed;
  RSS/Atom as a feed; any other page as its list of links. Claude then researches the page for a
  steadier source (through your handoff repo).
/watch list — every watch: how often, last change, Claude on/off
/watch check 2 — read it now · /watch check — all of them
/watch every 2 6 — every 6 hours (default watch.every_hours, 12)
/watch match 2 engineer|developer — keep only items that match · /watch match 2 off
/watch pause 2 · resume 2 · remove 2
/watch claude 2 off — no Claude notes for it (on to turn back) · /watch ask 2 — Claude researches it again
A script checks; you hear only when something is new. /menu — all your commands"""

URL = re.compile(r"https?://\S+")


def _add(ctx: work.Context, rest: str) -> str:
    found = URL.search(rest)
    if not found:
        return "Give the page's link: /watch add https://… [what you care about]"
    url = found.group(0).rstrip(").,")
    what = " ".join((rest[: found.start()] + rest[found.end():]).split())
    spec = sources.detect(url)
    s = ctx.settings
    number = ctx.store.add(url, work.name_for(url), what, spec, s.every_hours, s.claude)
    first = work.check(ctx, number)
    w = ctx.store.watches[number]
    if w["items"] is None:
        del ctx.store.watches[number]
        ctx.store.save()
        return f"Couldn't read {url}: {w['error']}. Nothing was added."
    how = {"json": "its job board's feed", "feed": "its RSS/Atom feed", "html": "its links"}[spec["kind"]]
    lines = [f"✅ Watch {number}: {w['name']}, read from {how}, every {w['every']:g} h.", first]
    if spec["kind"] == "html":
        lines.append(work.setup(ctx, number) or "Claude is off or not set up: it reads the page's links.")
    ctx.store.save()
    return "\n".join(x for x in lines if x)


def _list(ctx: work.Context, _rest: str) -> str:
    if not ctx.store.watches:
        return "No watches yet. /watch add <link> [what you care about]"
    lines = ["**Watches**"]
    for number, w in ctx.store.watches.items():
        state = "⏸ paused" if w["paused"] else f"every {w['every']:g} h"
        claude = "Claude on" if ctx.claude_for(w) else "Claude off"
        lines.append(f"{number}. {w['name']}" + (f" — {w['what']}" if w["what"] else ""))
        lines.append(f"   {len(w['items'] or {})} items · {state} · changed {work.when(w['changed'])} · {claude}"
                     + (f" · match {w['spec']['match']}" if w["spec"].get("match") else "")
                     + (f" · ⚠️ {w['error']}" if w["error"] else ""))
    if ctx.settings.claude and not ctx.repo.ready:
        lines.append("Claude notes need the handoff repo: watch.handoff_repo (or notes.handoff_repo) + "
                     "GITHUB_HANDOFF_TOKEN.")
    return "\n".join(lines)


def _pick(ctx: work.Context, rest: str) -> tuple[str, dict | None, str]:
    number, _, more = rest.strip().partition(" ")
    return number, ctx.store.get(number) if number else None, more.strip()


def _check(ctx: work.Context, rest: str) -> str:
    numbers = [rest.strip()] if rest.strip() else list(ctx.store.watches)
    if not numbers:
        return "No watches yet."
    if any(ctx.store.get(n) is None for n in numbers):
        return f"No watch {rest.strip()}. See /watch list."
    out = [work.check(ctx, n) or f"Watch {n}: nothing new." for n in numbers]
    ctx.store.save()
    return "\n\n".join(out)


def _setter(apply):
    def step(ctx: work.Context, rest: str) -> str:
        number, w, more = _pick(ctx, rest)
        if w is None:
            return f"Which watch? A number from /watch list, e.g. /watch {apply.__name__} 2"
        reply = apply(ctx, number, w, more)
        ctx.store.save()
        return reply
    return step


def every(_ctx, number: str, w: dict, more: str) -> str:
    try:
        hours = float(more.lower().rstrip("h"))
    except ValueError:
        return "How many hours? e.g. /watch every 2 6"
    if hours < 0.5:
        return "Every 30 minutes at most (the cron runs every 30 minutes)."
    w["every"] = hours
    return f"Watch {number} is checked every {hours:g} h."


def match(_ctx, number: str, w: dict, more: str) -> str:
    if more.lower() in ("", "off", "none"):
        w["spec"].pop("match", None)
        return f"Watch {number} keeps every item again."
    try:
        re.compile(more)
    except re.error as exc:
        return f"That pattern doesn't work: {exc}"
    w["spec"]["match"], w["items"] = more, None
    return f"Watch {number} keeps only items matching {more!r}. Its next check starts afresh (no alert for what's there)."


def pause(_ctx, number: str, w: dict, _more: str) -> str:
    w["paused"] = True
    return f"⏸ Watch {number} paused. /watch resume {number}"


def resume(_ctx, number: str, w: dict, _more: str) -> str:
    w["paused"] = False
    return f"▶️ Watch {number} resumed."


def remove(ctx, number: str, _w: dict, _more: str) -> str:
    del ctx.store.watches[number]
    return f"Removed watch {number}."


def claude(_ctx, number: str, w: dict, more: str) -> str:
    if more.lower() not in ("on", "off"):
        return f"/watch claude {number} on · off"
    w["claude"] = more.lower() == "on"
    return f"Claude notes for watch {number}: {more.lower()}."


def ask(ctx, number: str, _w: dict, _more: str) -> str:
    return work.setup(ctx, number) or "Claude is off for this watch, or the handoff repo is not set up."


STEPS = {"add": _add, "list": _list, "show": _list, "check": _check, "every": _setter(every),
         "match": _setter(match), "pause": _setter(pause), "resume": _setter(resume), "remove": _setter(remove),
         "delete": _setter(remove), "claude": _setter(claude), "ask": _setter(ask)}
HELP_WORDS = {"help", "-help", "--help", "-h", "?"}


def handle(raw: str, home: Path | None = None, http: Http | None = None, now: float | None = None) -> str:
    word, _, rest = (raw or "").strip().partition(" ")
    step = STEPS.get(word.lower())
    if step is None or word.lower() in HELP_WORDS:
        return HELP
    ctx = work.context(home or default_state_dir().parent, http, now)
    with work.one_at_a_time(ctx.home) as mine:
        if not mine:
            return "The watcher is busy checking; try again in a minute."
        return step(ctx, rest)
