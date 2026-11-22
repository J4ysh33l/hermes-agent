"""Hermes plugin: the /brief chat command. Installed as a symlink to this folder from
$HERMES_HOME/plugins/brief (orchestrator/brief/install.sh), so the checkout is found from the
link target. Every subcommand is a script; none calls a model."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _brief(raw_args: str) -> str:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from orchestrator.brief.cli import handle_chat_command

    return handle_chat_command(raw_args)


def register(ctx) -> None:
    ctx.register_command(
        "brief", _brief,
        description="Morning brief: more | topics | watch SYMBOL | follow TOPIC | mute WORD (no model call)",
        args_hint="<more|topics|watch|unwatch|follow|unfollow|mute|unmute|mutesender|unmutesender> [value]",
    )
