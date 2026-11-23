"""Hermes plugin for this fork:

- registers every command in orchestrator/commands.py plus /menu;
- registers the ``outreach`` and ``hr-payslips`` skills, so Hermes' agent can draft Slack messages and meetings (it
  cannot send them: only /slack yes and /meet yes, typed by you, do);
- adds the My day badge (streak · level · points) under every Hermes reply on Telegram
  (``transform_llm_output``: only the reply being finished is touched, never earlier turns);
- logs one usage line per Hermes model call: agent turns (``post_api_request``), failed turn
  requests (``api_request_error``) and side calls such as titles or compression
  (``post_auxiliary_call``), using the token counts Hermes already has. No extra model call.

Installed as a symlink to this folder from $HERMES_HOME/plugins/orchestrator (install.sh), so the
checkout is found from the link target."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


def _modules():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from orchestrator import commands, usage
    from orchestrator.myday import game

    return commands, usage, game


def _handler(name: str):
    return lambda raw_args="": _modules()[0].dispatch(name, raw_args or "")


def _tokens(summary: dict[str, Any] | None) -> dict[str, int]:
    s = summary or {}
    return {"input_tokens": s.get("prompt_tokens") or s.get("input_tokens") or 0,
            "output_tokens": s.get("output_tokens") or 0,
            "cached": s.get("cache_read_tokens") or 0,
            "reasoning": s.get("reasoning_tokens") or 0}


def _log(step: str, kw: dict[str, Any], *, ok: bool, note: str = "") -> None:
    # A hook must never break the turn it observes.
    try:
        _modules()[1].log_call("hermes", step, str(kw.get("provider") or ""), str(kw.get("model") or ""),
                               ok=ok, ms=int(float(kw.get("api_duration") or 0) * 1000), note=note,
                               **_tokens(kw.get("usage")))
    except Exception as exc:  # health: allow BLE001 -- observer hook: logging failure must not fail the turn
        print(f"orchestrator usage hook: {exc}", file=sys.stderr)


def on_api_request(**kw: Any) -> None:
    _log(kw.get("platform") or "agent", kw, ok=True)


def on_api_error(**kw: Any) -> None:
    _log(kw.get("platform") or "agent", kw, ok=False, note=str(kw.get("error_type") or kw.get("error") or "")[:200])


def on_aux_call(**kw: Any) -> None:
    _log(f"aux:{kw.get('aux_task') or 'other'}", kw, ok=kw.get("error") is None,
         note=str(kw.get("error") or "")[:200])


def on_llm_output(response_text: str = "", platform: str = "", **_kw: Any) -> str | None:
    """Badge under Telegram replies. None leaves the text unchanged (no badge before My day is set up)."""
    if platform != "telegram" or not response_text:
        return None
    text = _modules()[2].with_badge(response_text)
    return text if text != response_text else None


def register(ctx) -> None:
    commands = _modules()[0]
    ctx.register_command("menu", _handler("menu"), description="List your commands (no model call)")
    for command in commands.table():
        ctx.register_command(command.name, _handler(command.name),
                             description=f"{command.summary} (/{command.name} help)",
                             args_hint="help | <subcommand> [value]")
    ctx.register_skill("outreach", REPO_ROOT / "orchestrator/outreach/SKILL.md",
                       description="Draft Slack messages and Outlook meetings; the user approves in Telegram")
    ctx.register_skill("hr-payslips", REPO_ROOT / "orchestrator/hr/SKILL.md",
                       description="Make payslips from a salary sheet; the user sends them with /hr")
    ctx.register_hook("transform_llm_output", on_llm_output)
    ctx.register_hook("post_api_request", on_api_request)
    ctx.register_hook("api_request_error", on_api_error)
    ctx.register_hook("post_auxiliary_call", on_aux_call)
