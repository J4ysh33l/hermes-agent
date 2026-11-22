#!/usr/bin/env python3
"""Small team dashboard from our own state: what is paused, usage tier, queue, latest status per bot.
Replaces the 397k generated dashboard with a page of a few KB. No LLM, standard library only, never sends anything.

  dashboard.py                 print it as text
  dashboard.py --html FILE     write a static HTML page (atomic; serve or open it anywhere)

Reads $AGENT_STATE_DIR: pause*.json, usage_tier.json, queue/, status/<bot>.json. Run it from cron whenever you want a fresh page.
Not the weekly review: use weekly_digest.py for that.
"""
import argparse
import html
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pausectl as pc
import queuectl as qc
import statusupdate as su

MAX_PENDING = 20


def passed(ts):
    try:
        return datetime.fromisoformat(ts) <= pc.now()
    except ValueError:
        return False


def sections():
    rows = []
    for p in sorted(pc.state_dir().glob("pause*.json")):
        f = pc.read_flag(p)
        if f.get("until") and passed(f["until"]):
            continue
        rows.append(("everything" if p.name == "pause.json" else p.name[6:-5], f.get("reason") or "-", f"until {f['until']}" if f.get("until") else "open-ended"))
    out = [("Paused", ("scope", "reason", "lifts"), rows or [("nothing", "", "")])]

    t = su.load(pc.state_dir() / "usage_tier.json")
    out.append(("Usage tier", ("tier", "usage %", "set at"), [(t["tier"], f"{t['pct']:g}", t["at"])] if t else [("not set", "", "")]))

    out.append(("Queue", tuple(qc.STATES), [tuple(str(len(list((qc.qdir() / s).glob("*.json")))) for s in qc.STATES)]))
    pend = qc.all_tickets("pending")
    prow = [(t["id"], t.get("lane", ""), t.get("kind", ""), (t.get("note") or "")[:60]) for t in pend[:MAX_PENDING]]
    if len(pend) > MAX_PENDING:
        prow.append((f"+{len(pend) - MAX_PENDING} more", "", "", ""))
    out.append(("Pending tickets", ("id", "lane", "kind", "note"), prow or [("none", "", "", "")]))

    cutoff, bots = pc.now() - timedelta(hours=24), []
    for f in sorted(su.status_dir().glob("*.json")):
        if f.name.startswith("events") or not (doc := su.load(f)).get("routines"):
            continue
        name, e = max(doc["routines"].items(), key=lambda kv: kv[1]["at"])
        failed = sorted(n for n, r in doc["routines"].items() if r["state"] == "failed" and datetime.fromisoformat(r["at"]) >= cutoff)
        bots.append((doc.get("bot", f.stem), name, e["state"], e["at"], ", ".join(failed) or "-"))
    out.append(("Bots (latest routine)", ("bot", "routine", "state", "at", "failed in 24h"), bots or [("no status yet", "", "", "", "")]))
    return out


def as_text(secs):
    lines = [f"# Team dashboard {pc.now().isoformat(timespec='seconds')}"]
    for title, head, rows in secs:
        lines += ["", f"## {title}", " | ".join(head)] + [" | ".join(r) for r in rows]
    return "\n".join(lines)


def as_html(secs):
    e = html.escape
    body = "".join(
        f"<h2>{e(title)}</h2><table><tr>{''.join(f'<th>{e(h)}</th>' for h in head)}</tr>"
        + "".join(f"<tr>{''.join(f'<td>{e(c)}</td>' for c in r)}</tr>" for r in rows) + "</table>"
        for title, head, rows in secs)
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Team dashboard</title>"
            "<style>body{font:15px system-ui;margin:16px;max-width:900px}table{border-collapse:collapse;width:100%}"
            "td,th{border-bottom:1px solid #8884;padding:4px 8px;text-align:left}h2{margin:1.2em 0 .3em}</style>"
            f"<h1>Team dashboard</h1><p>{e(pc.now().isoformat(timespec='seconds'))}</p>{body}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--html", metavar="FILE")
    a = ap.parse_args()
    secs = sections()
    if not a.html:
        print(as_text(secs))
        return
    p = Path(a.html)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".")
    with os.fdopen(fd, "w") as f:
        f.write(as_html(secs))
    os.replace(tmp, p)
    print(f"wrote {p} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
