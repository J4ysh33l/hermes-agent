"""Hermes plugin: registers every command in orchestrator/commands.py plus /menu.

Installed as a symlink to this folder from $HERMES_HOME/plugins/orchestrator (install.sh), so the
checkout is found from the link target. No command calls a model."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _commands():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from orchestrator import commands

    return commands


def _handler(name: str):
    return lambda raw_args="": _commands().dispatch(name, raw_args or "")


def register(ctx) -> None:
    commands = _commands()
    ctx.register_command("menu", _handler("menu"), description="List your commands (no model call)")
    for command in commands.table():
        ctx.register_command(command.name, _handler(command.name), description=f"{command.summary} (/{command.name} help)",
                             args_hint="help | <subcommand> [value]")
