"""The watcher's run (the ``watch`` cron, every 30 minutes; prints nothing when nothing changed):

1. every watch whose time has come is read (``sources.read``) and compared with what was seen last;
   new items are listed for you at once (no model); with Claude on, Claude is also asked for a note;
2. Claude's answers are collected: a better ``spec`` (setup) or a note on a change.

A page that fails ``fail_after`` times in a row is reported once; it keeps being tried. A read that
finds nothing where there were items counts as a failure, so a broken page never looks like
"everything was removed".
"""

from __future__ import annotations

import fcntl
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http, UrllibHttp
from orchestrator.handoff import Handoff, HandoffError

from . import claude, settings, sources
from .store import Store

IST = ZoneInfo("Asia/Kolkata")
FORGET_ASK = timedelta(days=3)  # a Claude request with no answer by then is dropped (and said so)


@dataclass
class Context:
    home: Path
    http: Http
    now: float

    @cached_property
    def settings(self) -> settings.Settings:
        return settings.load(self.home / "brief")

    @cached_property
    def store(self) -> Store:
        return Store(self.home)

    @cached_property
    def repo(self) -> Handoff:
        return Handoff(self.http, Secrets(self.home / ".env", self.home / "brief" / "tokens"),
                       self.settings.handoff_repo)

    @property
    def local(self) -> datetime:
        return datetime.fromtimestamp(self.now, IST)

    def claude_for(self, w: dict) -> bool:
        return w["claude"] and self.repo.ready


def context(home: Path, http: Http | None = None, now: float | None = None) -> Context:
    return Context(home, http or UrllibHttp(), time.time() if now is None else now)


@contextmanager
def one_at_a_time(home: Path):
    path = home / "watch" / ".lock"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def name_for(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.strip("/")
    return parts.netloc.removeprefix("www.") + (f"/{path}" if path else "")[:40]


def when(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, IST).strftime("%-d %b %H:%M") if stamp else "never"


def _ask(ctx: Context, number: str, w: dict, make) -> str:
    """Open a Claude request; "" or a line saying why it could not be opened."""
    try:
        w["asks"].append(make())
    except HandoffError as exc:
        return f"(Claude was not asked: {exc})"
    return ""


def check(ctx: Context, number: str) -> str:
    """Read one watch now; the message for you ("" when nothing changed)."""
    w = ctx.store.watches[number]
    w["checked"] = ctx.now
    try:
        items = sources.read(ctx.http, w["spec"])
        if not items and w["items"]:
            raise sources.SourceError("found no items where there were some (page changed or blocked?)")
    except sources.SourceError as exc:
        w["fails"], w["error"] = w["fails"] + 1, str(exc)
        if w["fails"] == ctx.settings.fail_after:
            return f"⚠️ Watch {number} ({w['name']}) failed {w['fails']} times in a row: {exc}. Still trying."
        return ""
    w["fails"], w["error"] = 0, ""
    now_items = {i.key: [i.title, i.link] for i in items}
    if w["items"] is None:  # the first read: what is there now is the baseline
        w["items"] = now_items
        return f"👀 Watch {number} ({w['name']}): {len(items)} items now. You'll hear when one is added."
    new = [i for i in items if i.key not in w["items"]]
    gone = sum(1 for k in w["items"] if k not in now_items)
    since = when(w["changed"] or w["checked"])
    w["items"] = now_items
    if not new:
        return ""
    w["changed"] = ctx.now
    shown = new[: ctx.settings.max_lines]
    lines = [f"👀 **{w['name']}** — {len(new)} new" + (f", {gone} gone" if gone else "")]
    lines += [f"• {i.title}" + (f"\n  {i.link}" if i.link else "") for i in shown]
    if len(new) > len(shown):
        lines.append(f"…and {len(new) - len(shown)} more")
    if ctx.claude_for(w):
        note = _ask(ctx, number, w, lambda: claude.ask_note(ctx.repo, number, w, new, gone, ctx.settings.about,
                                                             since, ctx.local))
        lines.append(note or "Claude's note on these will follow.")
    lines.append(f"/watch list · /watch pause {number}")
    return "\n".join(lines)


def setup(ctx: Context, number: str) -> str:
    """Ask Claude to research a page the script can only read as links. "" when not asked."""
    w = ctx.store.watches[number]
    if not ctx.claude_for(w):
        return ""
    count = len(w["items"] or {})
    return _ask(ctx, number, w, lambda: claude.ask_setup(ctx.repo, number, w, count, ctx.local)) or \
        "🔎 Claude is looking for the best way to watch it; you'll hear when it's set up."


def _collect(ctx: Context, number: str, w: dict) -> list[str]:
    out, still = [], []
    for ask in w["asks"]:
        try:
            text = claude.answer(ctx.repo, ask)
        except HandoffError as exc:
            out.append(f"⚠️ Watch {number}: {exc}")
            still.append(ask)
            continue
        if text is None:
            if ctx.local - datetime.fromisoformat(ask["asked"]) > FORGET_ASK:
                out.append(f"⌛ Watch {number}: Claude never answered issue #{ask['issue']}; dropped.")
            else:
                still.append(ask)
        elif ask["job"] == "note":
            out.append(f"🔎 Claude on {w['name']}:\n{text.strip()}")
        else:
            out.append(_apply_spec(ctx, number, w, text))
    w["asks"] = still
    return out


def _apply_spec(ctx: Context, number: str, w: dict, text: str) -> str:
    spec, problems = claude.parse_spec(text)
    if spec is None:
        return f"⚠️ Watch {number}: Claude's setup was not used ({'; '.join(problems)}). It keeps reading the page."
    old_spec, old_items = w["spec"], w["items"]
    w["spec"], w["items"] = spec, None
    first = check(ctx, number)
    if w["items"] is None:  # the new source can't be read: keep the old one
        w["spec"], w["items"], w["fails"] = old_spec, old_items, 0
        return f"⚠️ Watch {number}: Claude's source {spec['url']} could not be read ({w['error']}); kept the page."
    why = spec.get("note") or f"now reads {spec['kind']} from {spec['url']}"
    return f"🔧 Watch {number} set up by Claude: {why}\n{first}"


def tick(ctx: Context) -> str:
    out = []
    for number, w in ctx.store.watches.items():
        if not w["paused"] and ctx.now - w["checked"] >= w["every"] * 3600:
            out.append(check(ctx, number))
        if w["asks"]:
            out += _collect(ctx, number, w)
    ctx.store.save()
    return "\n\n".join(m for m in out if m)
