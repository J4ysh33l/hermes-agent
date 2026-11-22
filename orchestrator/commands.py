"""Every Telegram command this fork adds, in one table. Rules for every command (checked by
tests/test_commands.py): its first word ``help``, ``-help``, ``--help``, ``-h`` or ``?`` prints its
own help and ``/menu`` lists it. A command calls a model only when you ask it to read a sentence or
write drafts (``/slack draft``, ``/meet <sentence>``), always through the logged ``orchestrator.llm``.

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


def _usage(args: str) -> str:
    from orchestrator.usage import handle_chat_command

    return handle_chat_command(args)


def _usage_help() -> str:
    from orchestrator.usage import USAGE_HELP

    return USAGE_HELP


def _slack(args: str) -> str:
    from orchestrator.outreach.chat import handle_slack

    return handle_slack(args)


def _meet(args: str) -> str:
    from orchestrator.outreach.chat import handle_meet

    return handle_meet(args)


def _outreach_help(name: str) -> str:
    from orchestrator.outreach import chat

    return {"slack": chat.SLACK_HELP, "meet": chat.MEET_HELP}[name]


def _hr(args: str) -> str:
    from orchestrator.hr.chat import handle

    return handle(args)


def _hr_help() -> str:
    from orchestrator.hr.chat import HR_HELP

    return HR_HELP


def table() -> tuple[ChatCommand, ...]:
    return (
        ChatCommand("brief", "Morning brief: full list, topics, watchlist, mutes", _brief_help(), _brief),
        ChatCommand("usage", "Tokens used per workflow and model, paid-tier cost, what to trim", _usage_help(),
                    _usage),
        ChatCommand("slack", "Send Slack messages as you: send, schedule, draft, approve", _outreach_help("slack"),
                    _slack),
        ChatCommand("meet", "Book Outlook meetings + Slack notes: 1:1s, all-hands, approve", _outreach_help("meet"),
                    _meet),
        ChatCommand("hr", "Payslips from the salary sheet; interviews on one Teams link", _hr_help(), _hr),
    )


def menu_text() -> str:
    lines = ["**Your commands** (only /slack draft and sentences to /slack or /meet use the AI model)", ""]
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
