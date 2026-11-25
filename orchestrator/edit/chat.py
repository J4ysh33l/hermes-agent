"""``/edit`` in Telegram: your own footage, edited in a style."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from orchestrator.brief.net import Http
from orchestrator.brief.store import default_state_dir
from orchestrator.notes.errors import NotesError
from orchestrator.studio.chat import Context as StudioContext

from . import plan as plans
from . import queue, settings, style, words

HELP = """**/edit** — your own footage, cut and finished in a style
/edit <Drive link or file> [style] [what you want] — a new job. Drive files: share as "anyone with the link".
  e.g. /edit https://drive.google.com/file/d/… zero1 CAT reel, my name is … , keep the ending
  It is transcribed, the editor (Claude) plans the cut and graphics, the plan comes here for /edit approve,
  then it renders and the video comes here (and to Drive when signed in).
/edit styles — the styles · /edit style <name> — one in full · /edit style new <name> [from <style>]
/edit queue — the jobs · /edit plan <job> — the plan and transcript · /edit approve <job> · /edit cancel <job>
/edit run — move the queue on now (the cron does it every 5 minutes)
Your styles: $HERMES_HOME/edit/styles/<name>.yaml (only what differs from the style they extend).
Logo and brand files: $HERMES_HOME/edit/brand/ · pictures a plan may show: the job's assets/ folder."""
HELP_WORDS = {"help", "-help", "--help", "-h", "?"}
REPO = Path(__file__).resolve().parents[2]


class Context(StudioContext):
    def __init__(self, home: Path, http: Http | None = None) -> None:
        super().__init__(home, http)
        self.edit, _studio = settings.load(home / "brief")


def _new(ctx: Context, text: str) -> str:
    parts = text.split()
    if not parts:
        return HELP
    source, rest = parts[0], parts[1:]
    look = ctx.edit.style
    if rest and rest[0].lower() in style.names(ctx.home):
        look, rest = rest[0].lower(), rest[1:]
    job = queue.add(ctx.home, source, look, " ".join(rest))
    _kick(ctx)
    return (f"📥 Edit job {job.id} · style {look}. I'll fetch and transcribe it, then the editor plans the cut; "
            f"the plan comes here for approval.")


def _kick(ctx: Context) -> None:
    log = ctx.home / "edit" / "run.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as out:  # detached: ingest and render take minutes; the queue reports to Telegram itself
        subprocess.Popen([sys.executable, "-m", "orchestrator.edit", "queue"], cwd=REPO,
                         env={**os.environ, "HERMES_HOME": str(ctx.home)}, stdout=out, stderr=out, start_new_session=True)


def _styles(ctx: Context, _text: str) -> str:
    return "\n".join(style.summary(style.load(n, ctx.home)) for n in style.names(ctx.home)) + \
        f"\nDefault: {ctx.edit.style} (edit.style in brief.yaml)"


def _style(ctx: Context, text: str) -> str:
    parts = text.split()
    if not parts:
        return _styles(ctx, "")
    if parts[0] == "new" and len(parts) >= 2:
        base = parts[3] if len(parts) >= 4 and parts[2] == "from" else style.DEFAULT
        path = style.create(parts[1], ctx.home, base)
        return f"✏️ Style {parts[1]} (extends {base}) is at {path}: change what you want, then /edit style {parts[1]}"
    look = style.load(parts[0], ctx.home)
    body = [f"**{look.name}** — {look.description}"]
    for key, section in look.as_dict().items():
        if isinstance(section, dict):
            body.append(f"{key}: " + ", ".join(f"{k}={v}" for k, v in section.items()))
    return "\n".join(body)


def _plan(ctx: Context, text: str) -> str:
    job = queue.load(ctx.home, text.strip())
    if not (job.folder / "plan.json").is_file():
        return f"Job {job.id} is {job.state}; no plan yet."
    ws = words.load(job.folder / "transcript.json")
    return queue.summary(ctx, job) + "\n\n" + words.numbered(words.sentences(ws))


STEPS = {
    "styles": _styles, "style": _style, "queue": lambda ctx, _t: queue.status(ctx.home), "plan": _plan,
    "approve": lambda ctx, t: (queue.approve(ctx.home, t.strip()), _kick(ctx), f"🎬 Job {t.strip()} approved: rendering now; the video comes here.")[2],
    "cancel": lambda ctx, t: f"✖️ Job {queue.cancel(ctx.home, t.strip()).id} cancelled.",
    "run": lambda ctx, _t: (_kick(ctx), "▶️ Moving the edit queue on now.")[1],
}


def handle(raw: str, home: Path | None = None, http: Http | None = None) -> str:
    word, _, rest = (raw or "").strip().partition(" ")
    if not word or word.lower() in HELP_WORDS:
        return HELP
    try:
        ctx = Context(home or default_state_dir().parent, http)
        step = STEPS.get(word.lower())
        return step(ctx, rest) if step else _new(ctx, raw)
    except (queue.QueueError, style.StyleError, plans.PlanError, NotesError, ValueError) as exc:
        return f"⚠️ {exc}"
