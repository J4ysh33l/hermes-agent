"""Every Telegram command this fork adds, in one table. Rule for every command: its first word
``help``, ``-help``, ``--help``, ``-h`` or ``?`` prints its own help, and ``/menu`` lists them all.
None of this calls a model.

Hermes owns ``/help`` (its own commands), so ours is ``/menu``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

HELP_WORDS = frozenset({"help", "-help", "--help", "-h", "?"})


@dataclass(frozen=True)
class ChatCommand:
    name: str
    summary: str  # one line, shown in /menu
    help_text: str  # full usage, shown by /<name> help
    run: Callable[[str], str]  # raw arguments -> reply


def _brief(args: str) -> str:
    from orchestrator.brief.cli import handle_chat_command

    return handle_chat_command(args)


def _brief_help() -> str:
    from orchestrator.brief.cli import CHAT_HELP

    return CHAT_HELP


def table() -> tuple[ChatCommand, ...]:
    return (
        ChatCommand("brief", "Morning brief: full list, topics, watchlist, mutes", _brief_help(), _brief),
    )


def menu_text() -> str:
    lines = ["**Your commands** (none of these uses the AI model)", ""]
    lines += [f"/{c.name} — {c.summary}" for c in table()]
    lines += ["", "Add `help` after any command for its options, e.g. /brief help",
              "Hermes' own commands: /help"]
    return "\n".join(lines)


def dispatch(name: str, raw_args: str) -> str:
    if name == "menu":
        return menu_text()
    command = next((c for c in table() if c.name == name), None)
    if command is None:
        return menu_text()
    first = (raw_args or "").strip().split(" ", 1)[0].lower()
    if not first or first in HELP_WORDS:
        return command.help_text
    return command.run(raw_args)
