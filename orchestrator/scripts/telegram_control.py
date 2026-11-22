#!/usr/bin/env python3
"""Telegram control bot: fixed commands, zero LLM tokens. Standard library only.

Use a SECOND Telegram bot token for this (make it with @BotFather). Hermes keeps
its own token for free-text conversation. Two programs cannot share one token.

Environment:
  TELEGRAM_CONTROL_TOKEN   token of the control bot (required)
  TELEGRAM_ALLOWED_CHATS   comma-separated numeric chat ids allowed to command it (required)
  AGENT_STATE_DIR          shared state folder (default ~/.agent-state)
  TELEGRAM_API_BASE        only for tests (default https://api.telegram.org)

Security: messages from any chat not on the allowlist are ignored silently.
Commands are an exact allowlist; arguments are validated and passed to the
helper scripts as a list, never through a shell. The token is never logged.

Commands:
  /status                      what is paused
  /pause [bot] [6h|90m|2d]     pause everything, or one bot, optionally for a time
  /resume [bot|all]            resume everything (no arg), one bot, or all
  /summary [24h|7d]            one line per bot
  /tier [PCT]                  show the usage tier, or apply the tier for PCT (0-100)
  /line BOT                    latest status line for a bot
  /queue                       ticket counts, then the pending tickets
  /approve ID   /reject ID     move a ticket (approve = ready for Claude or a script)
  /help
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOT_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
DUR_RE = re.compile(r"^\d+[mhd]$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,40}$")
MAX_REPLY = 3500


def run(script, *args):
    r = subprocess.run(
        [sys.executable, str(HERE / script), *args],
        capture_output=True, text=True, timeout=30, check=False,
    )
    out = (r.stdout + r.stderr).strip()
    return out or ("done" if r.returncode == 0 else f"failed (exit {r.returncode})")


def handle(text: str) -> str:
    """Turn one command message into a reply. Pure function, easy to test."""
    parts = text.strip().split()
    if not parts or not parts[0].startswith("/"):
        return "Fixed commands only. Try /help. (Free-text goes to the Hermes bot.)"
    cmd = parts[0].split("@")[0].lower()  # strips /cmd@botname
    args = parts[1:]

    if cmd in ("/help", "/start"):
        return __doc__.split("Commands:")[1].strip()
    if cmd == "/status":
        return run("pausectl.py", "status")
    if cmd == "/pause":
        bot, dur = None, None
        for x in args:
            if DUR_RE.match(x):
                dur = x
            elif BOT_RE.match(x):
                bot = x
            else:
                return f"Can't read {x!r}. Use /pause [bot] [6h]"
        cmd_args = ["pause", "--reason", "via Telegram"]
        if bot:
            cmd_args += ["--bot", bot]
        if dur:
            cmd_args += ["--for", dur]
        return run("pausectl.py", *cmd_args)
    if cmd == "/resume":
        if not args:
            return run("pausectl.py", "resume")
        if args[0] == "all":
            return run("pausectl.py", "resume", "--all")
        if BOT_RE.match(args[0]):
            return run("pausectl.py", "resume", "--bot", args[0])
        return "Use /resume, /resume all or /resume BOT"
    if cmd == "/tier":
        if not args:
            return run("usagetier.py", "status")
        if len(args) == 1 and re.fullmatch(r"\d{1,3}(\.\d+)?", args[0]):
            return run("usagetier.py", "set", args[0])
        return "Use /tier or /tier PCT (0-100)"
    if cmd == "/summary":
        since = args[0] if args and re.fullmatch(r"\d+[hd]", args[0]) else "24h"
        return run("statusupdate.py", "--summary", "--since", since)
    if cmd == "/line":
        if len(args) == 1 and BOT_RE.match(args[0]):
            return run("statusupdate.py", "--line", args[0])
        return "Use /line BOT"
    if cmd == "/queue":
        return run("queuectl.py", "counts") + "\n" + run("queuectl.py", "list", "--state", "pending")
    if cmd in ("/approve", "/reject"):
        if len(args) == 1 and ID_RE.match(args[0]):
            to = "approved" if cmd == "/approve" else "rejected"
            return run("queuectl.py", "move", args[0], "--to", to, "--note", "via Telegram")
        return f"Use {cmd} TICKET_ID"
    return "Unknown command. Try /help."


def api(base, token, method, params, timeout):
    url = f"{base}/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(url, data, timeout=timeout) as resp:
        return json.load(resp)


def main():
    token = os.environ.get("TELEGRAM_CONTROL_TOKEN")
    allowed = {c.strip() for c in os.environ.get("TELEGRAM_ALLOWED_CHATS", "").split(",") if c.strip()}
    base = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")
    if not token or not allowed:
        sys.exit("telegram_control: set TELEGRAM_CONTROL_TOKEN and TELEGRAM_ALLOWED_CHATS")
    offset = 0
    print("control bot running", flush=True)
    while True:
        try:
            res = api(base, token, "getUpdates", {"timeout": 50, "offset": offset}, 60)
        except Exception as e:
            print(f"poll failed ({type(e).__name__}); retrying in 5s", file=sys.stderr, flush=True)
            time.sleep(5)
            continue
        for upd in res.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            chat = str(msg.get("chat", {}).get("id", ""))
            if chat not in allowed or "text" not in msg:
                continue  # silent ignore
            try:
                reply = handle(msg["text"])[:MAX_REPLY]
            except Exception as e:
                reply = f"error: {type(e).__name__}"
            try:
                api(base, token, "sendMessage", {"chat_id": chat, "text": reply}, 15)
            except Exception as e:
                print(f"send failed ({type(e).__name__})", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
