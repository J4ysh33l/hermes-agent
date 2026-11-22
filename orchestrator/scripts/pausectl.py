#!/usr/bin/env python3
"""Central pause/resume switch for the bot team. No LLM, standard library only.

State lives in $AGENT_STATE_DIR (default ~/.agent-state):
  pause.json          global pause (everything)
  pause.<bot>.json    pause for one bot

Usage:
  pausectl pause  [--bot NAME] [--for 6h|90m|2d | --until 2026-11-22T09:00] [--reason TEXT]
  pausectl resume [--bot NAME]          (no --bot: clears the global pause only)
  pausectl resume --all                 (clears global and every per-bot pause)
  pausectl status
  pausectl check [--bot NAME]           exit 0 = run, exit 10 = paused

Put this as the first line of every scheduled routine:
  pausectl check --bot kabir || exit 0

A pause with --for/--until lifts itself the first time `check` or `status`
sees that the time has passed. Times are stored and compared in UTC; --until
without a timezone is read as UTC.

Optional Telegram notices: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
Without them nothing is sent. The token is never printed or logged.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path

EXIT_PAUSED = 10
BOT_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def state_dir() -> Path:
    d = Path(os.environ.get("AGENT_STATE_DIR") or Path.home() / ".agent-state")
    d.mkdir(parents=True, exist_ok=True)
    return d


def now() -> datetime:
    return datetime.now(UTC)


def flag_path(bot):
    if bot is None:
        return state_dir() / "pause.json"
    if not BOT_RE.match(bot):
        sys.exit(f"pausectl: bad bot name {bot!r} (letters, digits, - and _ only)")
    return state_dir() / f"pause.{bot.lower()}.json"


def write_atomic(path: Path, data: dict):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def read_flag(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (ValueError, OSError):
        # Unreadable flag: fail safe, treat as an open-ended pause.
        return {"reason": "unreadable flag file", "until": None}


def parse_duration(text: str) -> timedelta:
    m = re.fullmatch(r"(\d+)\s*([mhd])", text.strip().lower())
    if not m:
        sys.exit("pausectl: --for takes a number plus m, h or d (e.g. 90m, 6h, 2d)")
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[unit]: n})


def parse_until(text: str) -> datetime:
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        sys.exit("pausectl: --until needs an ISO time like 2026-11-22T09:00")
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def notify(text: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    body = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=10
        ).read()
    except Exception as e:  # never fail a routine because Telegram is down
        print(f"pausectl: Telegram notice failed ({type(e).__name__})", file=sys.stderr)


def expire_if_due(path: Path, label: str):
    """Return the flag if still active; delete and announce it if its time has passed."""
    flag = read_flag(path)
    if flag is None:
        return None
    until = flag.get("until")
    if until:
        try:
            if datetime.fromisoformat(until) <= now():
                path.unlink(missing_ok=True)
                notify(f"Auto-resumed: {label}")
                return None
        except ValueError:
            pass
    return flag


def active_flags(bot):
    """Active pauses that apply to `bot` (global always applies)."""
    out = []
    g = expire_if_due(flag_path(None), "everything")
    if g:
        out.append(("everything", g))
    if bot:
        b = expire_if_due(flag_path(bot), bot)
        if b:
            out.append((bot, b))
    return out


def describe(scope, flag):
    until = flag.get("until")
    when = f" until {until}" if until else " (no end time)"
    reason = f": {flag['reason']}" if flag.get("reason") else ""
    return f"{scope} paused{when}{reason}"


def cmd_pause(a):
    until = None
    if a.until_ts and a.duration:
        sys.exit("pausectl: use --for or --until, not both")
    if a.duration:
        until = now() + parse_duration(a.duration)
    elif a.until_ts:
        until = parse_until(a.until_ts)
        if until <= now():
            sys.exit("pausectl: --until is in the past")
    flag = {
        "reason": a.reason or "",
        "since": now().isoformat(timespec="seconds"),
        "until": until.isoformat(timespec="seconds") if until else None,
    }
    write_atomic(flag_path(a.bot), flag)
    msg = describe(a.bot or "everything", flag)
    print(msg)
    notify(msg)


def cmd_resume(a):
    if a.all:
        cleared = [p for p in state_dir().glob("pause*.json")]
        for p in cleared:
            p.unlink(missing_ok=True)
        msg = f"Resumed everything ({len(cleared)} pause flag(s) cleared)"
    else:
        p = flag_path(a.bot)
        existed = p.exists()
        p.unlink(missing_ok=True)
        label = a.bot or "everything"
        msg = f"Resumed {label}" if existed else f"{label} was not paused"
        if not existed:
            print(msg)
            return
    print(msg)
    notify(msg)


def cmd_status(_a):
    found = False
    for p in sorted(state_dir().glob("pause*.json")):
        name = p.name[len("pause."):-len(".json")] if p.name != "pause.json" else None
        flag = expire_if_due(p, name or "everything")
        if flag:
            found = True
            print(describe(name or "everything", flag))
    if not found:
        print("running (nothing paused)")


def cmd_check(a):
    flags = active_flags(a.bot)
    if flags:
        print(describe(*flags[0]), file=sys.stderr)
        sys.exit(EXIT_PAUSED)


def main():
    ap = argparse.ArgumentParser(prog="pausectl", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pause")
    p.add_argument("--bot")
    p.add_argument("--for", dest="duration")
    p.add_argument("--until", dest="until_ts")
    p.add_argument("--reason")
    p.set_defaults(fn=cmd_pause)

    r = sub.add_parser("resume")
    r.add_argument("--bot")
    r.add_argument("--all", action="store_true")
    r.set_defaults(fn=cmd_resume)

    s = sub.add_parser("status")
    s.set_defaults(fn=cmd_status)

    c = sub.add_parser("check")
    c.add_argument("--bot")
    c.set_defaults(fn=cmd_check)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
