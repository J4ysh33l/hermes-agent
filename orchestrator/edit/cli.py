"""``python -m orchestrator.edit …`` on the host (HERMES_HOME set, or ~/.hermes):

    run <video> [--style mine] [--plan plan.json] [--notes "what you want"] [--out edited.mp4] [--job DIR]
        ingest → transcribe → plan (the given plan.json, else cuts and captions only) → render
    prompt <job dir> [--notes "..."]     the editor's prompt for a prepared job (to plan by hand with Claude)
    check <job dir>                      check <job dir>/plan.json against its transcript and style
    queue                                one pass over the edit jobs (cron: every 5 minutes)
    styles                               the styles, one line each
    style new <name> [--from mine]       a style of yours to edit ($HERMES_HOME/edit/styles/<name>.yaml)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from orchestrator.brief.store import default_state_dir

from . import cuts, editor, media, plan as plans, render, settings, style, transcript, words


def _home() -> Path:
    return default_state_dir().parent


def _job_style(job: Path, home: Path) -> style.Style:
    name = (job / "style.txt").read_text(encoding="utf-8").strip() if (job / "style.txt").is_file() else settings.load(home / "brief")[0].style
    return style.load(name, home)


def cmd_run(a: argparse.Namespace, home: Path) -> int:
    edit, studio = settings.load(home / "brief")
    look = style.load(a.style or edit.style, home)
    src = Path(a.video).resolve()
    job = Path(a.job) if a.job else home / "edit" / "jobs" / f"{datetime.now():%Y%m%d-%H%M%S}"
    job.mkdir(parents=True, exist_ok=True)
    (job / "style.txt").write_text(look.name, encoding="utf-8")
    (job / "asked.txt").write_text(a.notes or "", encoding="utf-8")
    t = time.monotonic()
    if not (job / "source.mp4").is_file():
        info = media.prepare(src, job, look, edit.fps, edit.mezzanine_crf, edit.threads)
        print(f"ingest: {info.describe()} → 1080×1920 {edit.fps} fps ({time.monotonic() - t:.0f} s)", flush=True)
    t = time.monotonic()
    if not (job / "transcript.json").is_file():
        transcript.transcribe(edit, studio, home, job / "voice16.wav", job / "transcript.json")
        print(f"transcript: {time.monotonic() - t:.0f} s", flush=True)
    ws = words.load(job / "transcript.json")
    found = words.sentences(ws)
    chosen = plans.load(Path(a.plan).read_text(encoding="utf-8")) if a.plan else plans.basic(found, look)
    cut = cuts.build(ws, found, look, chosen.drop, chosen.trim, chosen.keep)
    problems = plans.check(chosen, found, cut, look, a.notes or "")
    if problems:
        print("plan problems:\n" + "\n".join(f"- {p}" for p in problems), file=sys.stderr)
        return 1
    (job / "plan.json").write_text(json.dumps(chosen.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    t = time.monotonic()
    out = Path(a.out) if a.out else job / "edited.mp4"
    result = render.render(job, look, chosen, ws, found, edit, studio, home, out)
    print(f"render: {result.seconds:.1f} s of video in {time.monotonic() - t:.0f} s → {result.video}")
    print(result.report)
    for note in result.notes:
        print(f"note: {note}")
    return 0


def cmd_prompt(a: argparse.Namespace, home: Path) -> int:
    job = Path(a.job)
    look = _job_style(job, home)
    ws = words.load(job / "transcript.json")
    asked = a.notes or ((job / "asked.txt").read_text(encoding="utf-8") if (job / "asked.txt").is_file() else "")
    print(editor.prompt(job.name, look, ws, words.sentences(ws), asked, str(job)))
    return 0


def cmd_check(a: argparse.Namespace, home: Path) -> int:
    job = Path(a.job)
    look = _job_style(job, home)
    ws = words.load(job / "transcript.json")
    found = words.sentences(ws)
    chosen = plans.load((job / "plan.json").read_text(encoding="utf-8"))
    asked = (job / "asked.txt").read_text(encoding="utf-8") if (job / "asked.txt").is_file() else ""
    problems = plans.check(chosen, found, cuts.build(ws, found, look, chosen.drop, chosen.trim, chosen.keep), look, asked)
    print("\n".join(f"- {p}" for p in problems) if problems else "OK")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.edit", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("video")
    r.add_argument("--style")
    r.add_argument("--plan")
    r.add_argument("--notes", default="")
    r.add_argument("--out")
    r.add_argument("--job")
    p = sub.add_parser("prompt")
    p.add_argument("job")
    p.add_argument("--notes", default="")
    c = sub.add_parser("check")
    c.add_argument("job")
    sub.add_parser("styles")
    sub.add_parser("queue", help="one pass over the edit jobs (the cron runs this every 5 minutes)")
    s = sub.add_parser("style")
    s.add_argument("action", choices=["new"])
    s.add_argument("name")
    s.add_argument("--from", dest="base", default=style.DEFAULT)
    a = parser.parse_args(argv)
    home = _home()
    try:
        if a.cmd == "run":
            return cmd_run(a, home)
        if a.cmd == "prompt":
            return cmd_prompt(a, home)
        if a.cmd == "check":
            return cmd_check(a, home)
        if a.cmd == "queue":
            from . import chat, queue
            said = queue.run(chat.Context(home))
            if said:
                print(said)
            return 0
        if a.cmd == "styles":
            print("\n".join(style.summary(style.load(n, home)) for n in style.names(home)))
            return 0
        print(f"Edit {style.create(a.name, home, a.base)}")
        return 0
    except (style.StyleError, media.MediaError, transcript.TranscriptError, plans.PlanError, FileNotFoundError) as exc:
        print(f"⚠️ {exc}", file=sys.stderr)
        return 1
