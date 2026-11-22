#!/usr/bin/env python3
"""Weekly digest for Claude's review. Replaces the weekly "read 20+ transcripts" review.
No LLM, standard library only.

Reads events.jsonl written by statusupdate.py and the ticket queue, and prints
one compact markdown page (a few hundred tokens). The weekly Claude review
reads ONLY this page, never transcripts.

Usage:  weekly_digest.py [--days 7] [--out FILE]
"""
import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path


def base() -> Path:
    return Path(os.environ.get("AGENT_STATE_DIR") or Path.home() / ".agent-state")


def events(since):
    out = []
    for name in ("events.1.jsonl", "events.jsonl"):
        p = base() / "status" / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if datetime.fromisoformat(e["at"]) >= since:
                out.append(e)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out")
    a = ap.parse_args()
    since = datetime.now(UTC) - timedelta(days=a.days)
    ev = events(since)

    by_bot = defaultdict(Counter)
    fails = Counter()
    nochange = Counter()
    routines = defaultdict(Counter)
    for e in ev:
        by_bot[e["bot"]][e["state"]] += 1
        routines[(e["bot"], e["routine"])][e["state"]] += 1
        if e["state"] == "failed":
            fails[(e["bot"], e["routine"])] += 1
    for k, c in routines.items():
        if c["nochange"] and c["nochange"] >= max(3, 0.8 * sum(c.values())):
            nochange[k] = c["nochange"]

    lines = [f"# Weekly digest, last {a.days} days", f"Runs logged: {len(ev)}", "",
             "| Bot | ok | nochange | failed | skipped | paused |", "|---|---|---|---|---|---|"]
    for bot in sorted(by_bot):
        c = by_bot[bot]
        lines.append(f"| {bot} | {c['ok']} | {c['nochange']} | {c['failed']} | {c['skipped']} | {c['paused']} |")
    if not by_bot:
        lines.append("| (no runs logged) | | | | | |")

    lines += ["", "## Repeated failures"]
    lines += [f"- {b}/{r}: {n} failed" for (b, r), n in fails.most_common(10)] or ["- none"]
    lines += ["", "## Mostly 'nochange' (candidates to turn into a script gate or drop)"]
    lines += [f"- {b}/{r}: {n} nochange runs" for (b, r), n in nochange.most_common(10)] or ["- none"]

    q = base() / "queue"
    if q.exists():
        counts = {s.name: len(list(s.glob("*.json"))) for s in sorted(q.iterdir()) if s.is_dir()}
        lines += ["", "## Queue", "- " + ", ".join(f"{k}={v}" for k, v in counts.items())]

    lines += ["", "## Review prompt",
              "Using only the above: which routines should run less often, be merged, become a pure script, or be retired? "
              "Give at most 5 changes, each with one line of evidence."]
    text = "\n".join(lines)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
