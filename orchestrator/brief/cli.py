"""``python -m orchestrator.brief <command>``. The cron launcher calls ``run``; the Hermes plugin's
``/brief <command>`` calls ``handle_chat_command``. Chat commands never call a model."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path

from orchestrator.myday.game import with_badge

from . import auth, pipeline, render, settings
from .creds import Secrets
from .net import HttpError, UrllibHttp
from .settings import Prefs, Symbol
from .sources import markets
from .store import Store, default_state_dir, now

TICKER = re.compile(r"^[A-Z0-9^][A-Z0-9.^=\-]{0,14}$")
MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"

CHAT_HELP = """**/brief** — morning brief (sent 8:15 IST). No command here uses the AI model.
/brief more — every item from today's brief
/brief topics — topics, watchlist and mutes
/brief watch NVDA — add a stock to the markets block (Yahoo symbol, e.g. RELIANCE.NS)
/brief unwatch NVDA
/brief follow electric vehicles — add a news topic
/brief unfollow electric vehicles
/brief mute cricket — drop items containing a word
/brief unmute cricket
/brief mutesender noreply@example.com — drop a sender
/brief unmutesender noreply@example.com
/brief help (or -help) — this list · /menu — all your commands"""


class Context:
    def __init__(self, state_dir: Path, http=None) -> None:
        self.state_dir = state_dir
        self.http = http or UrllibHttp()
        self.store = Store(state_dir)
        self.prefs_path = state_dir / "prefs.json"

    def settings(self) -> settings.Settings:
        return settings.load(self.state_dir)

    def secrets(self) -> Secrets:
        home = self.state_dir.parent
        return Secrets(home / ".env", self.state_dir / "tokens")

    def prefs(self) -> Prefs:
        return Prefs.load(self.prefs_path)


# ------------------------------------------------------------------ chat commands (no model)
def _add(values: tuple[str, ...], value: str) -> tuple[str, ...]:
    return values if value in values else (*values, value)


def _remove(values: tuple[str, ...], value: str) -> tuple[str, ...]:
    return tuple(v for v in values if v.lower() != value.lower())


def _update(ctx: Context, field: str, change: Callable[[tuple[str, ...]], tuple[str, ...]]) -> None:
    prefs = ctx.prefs()
    data = {k: getattr(prefs, k) for k in Prefs.__dataclass_fields__}
    data[field] = change(data[field])
    Prefs(**data).save(ctx.prefs_path)


def cmd_watch(ctx: Context, arg: str) -> str:
    symbol = arg.strip().upper()
    if not TICKER.match(symbol):
        return "Give one Yahoo Finance symbol, e.g. /brief watch NVDA or /brief watch RELIANCE.NS"
    try:
        q = markets.quote(ctx.http, Symbol(symbol, symbol))
    except HttpError as exc:
        reason = "no such symbol" if exc.status == 404 else f"Yahoo Finance error {exc.status or 'network'}"
        return f"Could not add {symbol}: {reason}. Nothing changed."
    except (ValueError, KeyError, IndexError):
        return f"Could not add {symbol}: no price data. Nothing changed."
    _update(ctx, "watchlist", lambda v: _add(v, symbol))
    return f"Added {symbol} (last {q.price:,.2f}) to the markets block."


def cmd_topics(ctx: Context, _arg: str = "") -> str:
    s = ctx.settings()
    lines = ["**Topics**"] + [f"• {render.plain(t.name)} (weight {t.weight:g})" for t in s.topics]
    lines += [f"• {render.plain(f)} (followed)" for f in s.prefs.followed]
    lines += ["", "**Watchlist**: " + (", ".join(s.prefs.watchlist) or "none")]
    lines += ["**Muted words**: " + (", ".join(s.all_muted_words()) or "none")]
    lines += ["**Muted senders**: " + (", ".join(s.all_muted_senders()) or "none")]
    return "\n".join(lines)


def cmd_more(ctx: Context, _arg: str = "") -> str:
    edition = ctx.store.latest_edition()
    return render.more_text(edition) if edition else "No brief has run yet."


def _pref_command(field: str, adding: bool, label: str) -> Callable[[Context, str], str]:
    def handler(ctx: Context, arg: str) -> str:
        value = " ".join(arg.split()).lower() if field != "watchlist" else arg.strip().upper()
        if not value:
            return f"Usage: /brief {'' if adding else 'un'}{label} <text>"
        _update(ctx, field, (lambda v: _add(v, value)) if adding else (lambda v: _remove(v, value)))
        return f"{'Added' if adding else 'Removed'} '{value}' {'to' if adding else 'from'} {field.replace('_', ' ')}."
    return handler


CHAT_COMMANDS: dict[str, Callable[[Context, str], str]] = {
    "more": cmd_more,
    "topics": cmd_topics,
    "watch": cmd_watch,
    "unwatch": _pref_command("watchlist", False, "watch"),
    "follow": _pref_command("followed", True, "follow"),
    "unfollow": _pref_command("followed", False, "follow"),
    "mute": _pref_command("muted_words", True, "mute"),
    "unmute": _pref_command("muted_words", False, "mute"),
    "mutesender": _pref_command("muted_senders", True, "mutesender"),
    "unmutesender": _pref_command("muted_senders", False, "mutesender"),
}


def handle_chat_command(raw_args: str, state_dir: Path | None = None, http=None) -> str:
    name, _, arg = (raw_args or "").strip().partition(" ")
    handler = CHAT_COMMANDS.get(name.lower())
    if handler is None:
        return CHAT_HELP
    return handler(Context(state_dir or default_state_dir(), http), arg)


# ------------------------------------------------------------------ host commands
def cmd_run(ctx: Context, dry_run: bool) -> int:
    result = pipeline.run(ctx.http, ctx.settings(), ctx.secrets(), ctx.store, now(), dry_run=dry_run)
    print(with_badge(result.text))
    return 0


def cmd_models(ctx: Context) -> int:
    key = ctx.secrets().get("GEMINI_API_KEY", "GOOGLE_API_KEY")
    if not key:
        print("GEMINI_API_KEY is not set in $HERMES_HOME/.env")
        return 1
    data = ctx.http.request("GET", MODELS_URL, params={"pageSize": 200}, headers={"x-goog-api-key": key}).json()
    wanted = {m.id for m in ctx.settings().models}
    for model in data.get("models") or []:
        name = model.get("name", "").removeprefix("models/")
        if "generateContent" in model.get("supportedGenerationMethods", []):
            print(("* " if name in wanted else "  ") + name)
    print("\n* = in your ranking chain. Any chain id not listed above will fail; fix brief.yaml.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.brief")
    parser.add_argument("--state-dir", type=Path, default=None, help="default: $HERMES_HOME/brief")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="build and print today's brief")
    run_p.add_argument("--dry-run", action="store_true", help="do not save or mark anything as seen")
    sub.add_parser("models", help="list the Gemini models your key can call")
    auth_p = sub.add_parser("auth", help="one-time login")
    auth_p.add_argument("service", choices=["google", "microsoft"])
    auth_p.add_argument("--account", default="main", help="google only: your label for this Gmail account")
    chat = sub.add_parser("chat", help="the same commands as /brief in Telegram")
    chat.add_argument("words", nargs="*")
    args = parser.parse_args(argv)
    ctx = Context(args.state_dir or default_state_dir())
    if args.command == "run":
        return cmd_run(ctx, args.dry_run)
    if args.command == "models":
        return cmd_models(ctx)
    if args.command == "auth":
        if args.service == "google":
            auth.google(ctx.http, ctx.secrets(), account=args.account)
        else:
            auth.microsoft(ctx.http, ctx.secrets())
        return 0
    print(handle_chat_command(" ".join(args.words), ctx.state_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
