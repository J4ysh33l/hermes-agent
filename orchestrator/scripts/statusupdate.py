#!/usr/bin/env python3
"""Shared status-update script for all bots. No LLM, standard library only.

Replaces the "write fresh Python to update the status file" step every bot
does after every run. One call, one fixed format.

State lives in $AGENT_STATE_DIR (default ~/.agent-state)/status:
  <bot>.json     latest result per routine for that bot
  events.jsonl   append-only history, one line per call (rotated at 5 MB)

Usage:
  statusupdate BOT ROUTINE STATE [--note TEXT] [--count key=value ...]
  statusupdate --summary [--since 24h]     one line per bot, for the nightly report
  statusupdate --line BOT                  single fixed-format status line for Donna

STATE is one of: ok, nochange, failed, skipped, paused.

Examples:
  statusupdate kabir x-reply-drafts ok --count drafted=45 --count skipped=3
  statusupdate vivek factcheck-batch nochange
  statusupdate teenzyn x-post-8pm failed --note "API 403"
"""
import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path

STATES = ("ok", "nochange", "failed", "skipped", "paused")
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,60}$")
MAX_LOG_BYTES = 5 * 1024 * 1024


def status_dir() -> Path:
    base = Path(os.environ.get("AGENT_STATE_DIR") or Path.home() / ".agent-state")
    d = base / "status"
    d.mkdir(parents=True, exist_ok=True)
    return d


def now() -> datetime:
    return datetime.now(UTC)


def write_atomic(path: Path, data):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def parse_counts(items):
    out = {}
    for item in items or []:
        k, sep, v = item.partition("=")
        if not sep or not NAME_RE.match(k):
            sys.exit(f"statusupdate: --count needs key=value, got {item!r}")
        out[k] = int(v) if re.fullmatch(r"-?\d+", v) else v
    return out


def record(a):
    for label, val in (("bot", a.bot), ("routine", a.routine)):
        if not NAME_RE.match(val):
            sys.exit(f"statusupdate: bad {label} name {val!r}")
    if a.state not in STATES:
        sys.exit(f"statusupdate: STATE must be one of {', '.join(STATES)}")

    ts = now().isoformat(timespec="seconds")
    entry = {"state": a.state, "at": ts}
    if a.note:
        entry["note"] = a.note[:500]
    counts = parse_counts(a.count)
    if counts:
        entry["counts"] = counts

    d = status_dir()
    bot_file = d / f"{a.bot.lower()}.json"
    doc = load(bot_file)
    doc.setdefault("bot", a.bot)
    doc.setdefault("routines", {})[a.routine] = entry
    doc["updated"] = ts
    write_atomic(bot_file, doc)

    log = d / "events.jsonl"
    if log.exists() and log.stat().st_size > MAX_LOG_BYTES:
        log.replace(d / "events.1.jsonl")
    with log.open("a") as f:
        f.write(json.dumps({"bot": a.bot, "routine": a.routine, **entry}) + "\n")

    print(f"{a.bot}/{a.routine}: {a.state}")


def parse_since(text):
    m = re.fullmatch(r"(\d+)([hd])", text.strip().lower())
    if not m:
        sys.exit("statusupdate: --since takes e.g. 24h or 7d")
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(hours=n) if unit == "h" else timedelta(days=n)


def summary(a):
    cutoff = now() - parse_since(a.since)
    rows = []
    for f in sorted(status_dir().glob("*.json")):
        if f.name.startswith("events"):
            continue
        doc = load(f)
        tally = {s: 0 for s in STATES}
        failed = []
        for name, e in doc.get("routines", {}).items():
            if datetime.fromisoformat(e["at"]) < cutoff:
                continue
            tally[e["state"]] += 1
            if e["state"] == "failed":
                failed.append(name)
        total = sum(tally.values())
        if total == 0:
            rows.append(f"{doc.get('bot', f.stem)}: no runs in last {a.since}")
            continue
        parts = [f"{n} {s}" for s, n in tally.items() if n]
        line = f"{doc.get('bot', f.stem)}: " + ", ".join(parts)
        if failed:
            line += f" (failed: {', '.join(failed)})"
        rows.append(line)
    print("\n".join(rows) if rows else "no status files yet")


def line(a):
    doc = load(status_dir() / f"{a.line.lower()}.json")
    if not doc:
        print(f"{a.line}: no status yet")
        return
    routines = doc.get("routines", {})
    latest = max(routines.items(), key=lambda kv: kv[1]["at"])
    name, e = latest
    extra = ""
    if e.get("counts"):
        extra = " [" + ", ".join(f"{k}={v}" for k, v in e["counts"].items()) + "]"
    note = f" - {e['note']}" if e.get("note") else ""
    print(f"{doc.get('bot', a.line)} | {name} | {e['state']} | {e['at']}{extra}{note}")


def main():
    ap = argparse.ArgumentParser(prog="statusupdate", description=__doc__.split("\n\n")[0])
    ap.add_argument("bot", nargs="?")
    ap.add_argument("routine", nargs="?")
    ap.add_argument("state", nargs="?")
    ap.add_argument("--note")
    ap.add_argument("--count", action="append")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--since", default="24h")
    ap.add_argument("--line")
    a = ap.parse_args()

    if a.summary:
        summary(a)
    elif a.line:
        line(a)
    elif a.bot and a.routine and a.state:
        record(a)
    else:
        ap.error("give BOT ROUTINE STATE, or --summary, or --line BOT")


if __name__ == "__main__":
    main()
