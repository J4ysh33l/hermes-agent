#!/usr/bin/env python3
"""File-based ticket queue: the hand-off between scripts, Hermes and Claude.
No LLM, standard library only.

A ticket is one small JSON file holding only a header and a path to the
content. Nobody has to load the content to know what a ticket is.

  $AGENT_STATE_DIR/queue/<state>/<id>.json      states: pending, approved, claimed, done, rejected, failed

Header fields: id, lane (claude|hermes|script|private), kind, path, note,
created, updated, state, history.

Usage:
  queuectl add --lane claude --kind x-reply-drafts --path /files/drafts.md [--note TEXT]
  queuectl list [--state pending] [--lane claude]
  queuectl move ID --to approved|rejected|claimed|done|failed [--note TEXT]
  queuectl claim --lane claude        take the oldest approved/pending ticket for a lane
  queuectl counts

`claim` is what a Claude scheduled task runs first: if it prints nothing and
exits 3, there is no work and the run can stop in one cheap turn.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone, UTC
from pathlib import Path

STATES = ("pending", "approved", "claimed", "done", "rejected", "failed")
LANES = ("claude", "hermes", "script", "private")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,40}$")
EXIT_EMPTY = 3


def qdir() -> Path:
    base = Path(os.environ.get("AGENT_STATE_DIR") or Path.home() / ".agent-state")
    q = base / "queue"
    for s in STATES:
        (q / s).mkdir(parents=True, exist_ok=True)
    return q


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def write_atomic(path: Path, data):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def find(tid):
    if not ID_RE.match(tid):
        sys.exit(f"queuectl: bad ticket id {tid!r}")
    for s in STATES:
        p = qdir() / s / f"{tid}.json"
        if p.exists():
            return s, p
    return None, None


def all_tickets(state=None, lane=None):
    out = []
    for s in ([state] if state else STATES):
        for p in sorted((qdir() / s).glob("*.json")):
            try:
                t = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if lane and t.get("lane") != lane:
                continue
            out.append(t)
    return sorted(out, key=lambda t: t["created"])


def add(a):
    if a.lane not in LANES:
        sys.exit(f"queuectl: lane must be one of {', '.join(LANES)}")
    tid = uuid.uuid4().hex[:8]
    t = {
        "id": tid, "lane": a.lane, "kind": a.kind, "path": a.path,
        "note": (a.note or "")[:300], "created": now(), "updated": now(),
        "state": "pending", "history": [["pending", now()]],
    }
    write_atomic(qdir() / "pending" / f"{tid}.json", t)
    print(tid)


def move_ticket(tid, to, note=None):
    if to not in STATES:
        sys.exit(f"queuectl: state must be one of {', '.join(STATES)}")
    cur, p = find(tid)
    if not p:
        sys.exit(f"queuectl: no ticket {tid}")
    t = json.loads(p.read_text(encoding="utf-8"))
    t["state"], t["updated"] = to, now()
    t["history"].append([to, now()] + ([note[:200]] if note else []))
    write_atomic(qdir() / to / f"{tid}.json", t)
    if cur != to:
        p.unlink()
    return t


def list_(a):
    for t in all_tickets(a.state, a.lane):
        print(f"{t['id']}  {t['state']:<8} {t['lane']:<7} {t['kind']}  {t['created']}  {t['note']}")


def claim(a):
    for state in ("approved", "pending") if not a.approved_only else ("approved",):
        for t in all_tickets(state, a.lane):
            t = move_ticket(t["id"], "claimed")
            print(json.dumps({k: t[k] for k in ("id", "lane", "kind", "path", "note")}))
            return
    sys.exit(EXIT_EMPTY)


def counts(_a):
    print(", ".join(f"{s}={len(list((qdir() / s).glob('*.json')))}" for s in STATES))


def main():
    ap = argparse.ArgumentParser(prog="queuectl", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("--lane", required=True); p.add_argument("--kind", required=True)
    p.add_argument("--path", required=True); p.add_argument("--note")
    p.set_defaults(fn=add)
    p = sub.add_parser("list")
    p.add_argument("--state"); p.add_argument("--lane")
    p.set_defaults(fn=list_)
    p = sub.add_parser("move")
    p.add_argument("id"); p.add_argument("--to", required=True); p.add_argument("--note")
    p.set_defaults(fn=lambda a: print(f"{a.id} -> {move_ticket(a.id, a.to, a.note)['state']}"))
    p = sub.add_parser("claim")
    p.add_argument("--lane", required=True)
    p.add_argument("--approved-only", action="store_true")
    p.set_defaults(fn=claim)
    p = sub.add_parser("counts")
    p.set_defaults(fn=counts)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
