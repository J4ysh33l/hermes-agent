#!/usr/bin/env python3
"""Daily usage tier: you read the Claude usage percentage, this applies the matching tier. No LLM, standard library only.

A tier = a percent band + the bots paused while usage is in that band. Applying a tier uses pausectl's own
flag files (so `pausectl check` gates every routine) with a timed restore: the pause lifts itself after
`restore_after` (default 5h, the usage window) unless you set the percentage again.

Config: $AGENT_STATE_DIR/usage_tiers.json  (create an example with `init`; the bands and bot names in it are PLACEHOLDERS)
  {"restore_after": "5h",
   "tiers": [{"name": "normal", "min_pct": 0,  "pause_bots": []},
             {"name": "saving", "min_pct": 85, "pause_bots": ["kabir", "bhuvam"]},   # "*" = pause everything
             ...]}
A tier applies from its min_pct up to the next tier's min_pct. The first tier must start at 0.

  usagetier.py init                   write the example config (never overwrites)
  usagetier.py set PCT                apply the tier for PCT (0-100); resumes bots this script paused earlier and that the new tier no longer lists
  usagetier.py status                 current tier and what it paused

It only touches pauses it made (reason starts with "usage-tier:"). A pause you set by hand is left alone, in both directions.
Optional Telegram notice (one message per change, not per bot): TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
Exit codes: 0 ok, 2 bad config or input (nothing is changed).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pausectl as pc

OWNER = "usage-tier:"
EXAMPLE = {
    "restore_after": "5h",
    "tiers": [
        {"name": "normal", "min_pct": 0, "pause_bots": []},
        {"name": "light", "min_pct": 60, "pause_bots": ["bhuvam"]},
        {"name": "saving", "min_pct": 85, "pause_bots": ["bhuvam", "kabir", "chitra", "drishti"]},
        {"name": "stop", "min_pct": 95, "pause_bots": ["*"]},
    ],
}


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)


def cfg_file(a):
    return Path(a.config) if a.config else pc.state_dir() / "usage_tiers.json"


def load_cfg(path):
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"usagetier: no config at {path}; run: usagetier.py init")
    except ValueError as e:
        die(f"usagetier: config is not valid JSON: {e}")
    errs, tiers = [], cfg.get("tiers")
    if not isinstance(tiers, list) or not tiers:
        die("usagetier: config needs a non-empty 'tiers' list")
    for i, t in enumerate(tiers):
        if not isinstance(t.get("name"), str) or not t["name"]:
            errs.append(f"tier {i}: name missing")
        if isinstance(t.get("min_pct"), bool) or not isinstance(t.get("min_pct"), (int, float)) or not 0 <= t["min_pct"] <= 100:
            errs.append(f"tier {i}: min_pct must be a number 0..100")
        bots = t.get("pause_bots")
        if not isinstance(bots, list) or any(b != "*" and not (isinstance(b, str) and pc.BOT_RE.match(b)) for b in bots):
            errs.append(f"tier {i}: pause_bots must be a list of bot names or \"*\"")
    if not errs:
        starts = sorted(t["min_pct"] for t in tiers)
        if starts[0] != 0:
            errs.append("the lowest tier must start at min_pct 0")
        if len(set(starts)) != len(starts):
            errs.append("two tiers share a min_pct")
    try:
        pc.parse_duration(cfg.get("restore_after", "5h"))
    except SystemExit as e:
        errs.append(f"restore_after: {e}")
    if errs:
        die("usagetier: bad config:\n  " + "\n  ".join(errs))
    return cfg


def scope_path(scope):
    return pc.flag_path(None if scope == "*" else scope.lower())


def ours(flag):
    return bool(flag) and str(flag.get("reason", "")).startswith(OWNER)


def pct_arg(text):
    try:
        v = float(text)
    except ValueError:
        v = -1
    if not 0 <= v <= 100:
        raise argparse.ArgumentTypeError(f"PCT must be a number 0..100, got {text!r}")
    return v


def cmd_init(a):
    p = cfg_file(a)
    if p.exists():
        die(f"usagetier: {p} already exists; edit it instead")
    pc.write_atomic(p, EXAMPLE)
    print(f"wrote {p} - bands and bot names are placeholders; edit before use")


def cmd_set(a):
    cfg = load_cfg(cfg_file(a))
    tier = [t for t in sorted(cfg["tiers"], key=lambda t: t["min_pct"]) if t["min_pct"] <= a.pct][-1]
    until = pc.now() + pc.parse_duration(cfg.get("restore_after", "5h"))
    sf = pc.state_dir() / "usage_tier.json"
    prev = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {}
    targets = {b.lower() if b != "*" else b for b in tier["pause_bots"]}
    resumed, paused, kept = [], [], []
    for s in sorted(set(prev.get("applied", [])) - targets):
        p = scope_path(s)
        if ours(pc.read_flag(p)):
            p.unlink(missing_ok=True)
            resumed.append(s)
    for s in sorted(targets):
        p = scope_path(s)
        if pc.read_flag(p) and not ours(pc.read_flag(p)):
            kept.append(s)
            continue
        pc.write_atomic(p, {"reason": f"{OWNER} {tier['name']} ({a.pct:g}%)", "since": pc.now().isoformat(timespec="seconds"),
                            "until": until.isoformat(timespec="seconds")})
        paused.append(s)
    pc.write_atomic(sf, {"pct": a.pct, "tier": tier["name"], "at": pc.now().isoformat(timespec="seconds"), "applied": paused})
    msg = f"Usage {a.pct:g}% -> tier {tier['name']}. Paused: {', '.join(paused) or 'none'}."
    if resumed:
        msg += f" Resumed: {', '.join(resumed)}."
    if kept:
        msg += f" Already paused by hand, left alone: {', '.join(kept)}."
    print(msg)
    if prev.get("tier") != tier["name"] or set(prev.get("applied", [])) != set(paused):
        pc.notify(msg)


def cmd_status(_a):
    sf = pc.state_dir() / "usage_tier.json"
    if not sf.exists():
        print("no tier applied yet")
        return
    st = json.loads(sf.read_text(encoding="utf-8"))
    print(f"tier {st['tier']} at {st['pct']:g}% (set {st['at']}); paused by it: {', '.join(st['applied']) or 'none'}")


def main():
    ap = argparse.ArgumentParser(prog="usagetier", description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", help="config file (default $AGENT_STATE_DIR/usage_tiers.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    s = sub.add_parser("set"); s.add_argument("pct", type=pct_arg); s.set_defaults(fn=cmd_set)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
