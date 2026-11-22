"""The ``outreach:`` section of ``$HERMES_HOME/brief/brief.yaml`` → frozen Settings.

The message texts are templates here so you can replace them with your own drafts without a code
change. Placeholders: {first} {name} {topic} {length} {day} {start} {end} {join}.

How drafted messages sound comes from ``$HERMES_HOME/brief/outreach/style.md`` when it exists
(free text: registers, rules, a few example messages). It lives outside the repo because its
examples are real workplace messages. The facts-only rules are added by ``understand`` either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from orchestrator.brief.settings import EXAMPLE, ModelChoice


@dataclass(frozen=True)
class Templates:
    meeting_subject: str = "{topic} | 1:1"
    meeting_body: str = ("Hi {first},<br><br>Setting up {length} minutes to discuss {topic}. "
                         "The Teams link is below.<br><br>Thanks")
    meeting_note: str = ("Hi {first}, I've sent you a calendar invite for {day}, {start}–{end} IST "
                         "({length} min) to discuss {topic}.{join} "
                         "If the time doesn't work, let me know and I'll move it.")
    allhands_subject: str = "All hands: {topic}"
    allhands_body: str = "Hi all,<br><br>All hands on {topic}. The Teams link is below.<br><br>Thanks"
    allhands_post: str = ("Hi everyone, we have an all-hands on {day}, {start}–{end} IST: {topic}. "
                          "A calendar invite has been sent to everyone in this channel.{join}")


DEFAULT_STYLE = "Professional, warm and concise. Greet the person by first name. No emojis, no sign-off."
STYLE_FILE = "outreach/style.md"
STYLE_LIMIT = 6000  # characters; the style rides on every draft call, so it stays well under the budget


@dataclass(frozen=True)
class Settings:
    timezone: str = "Asia/Kolkata"
    daily_cap: int = 50  # Slack messages + invites + channel posts sent for you per day
    preview_minutes: int = 30  # a plan not approved by then expires
    gap_minutes: int = 5
    default_length: int = 30
    allhands_length: int = 60
    teams: bool = True
    detect_days: int = 3
    detect_words: tuple[str, ...] = ("call", "meet", "meeting", "sync", "discuss", "catch up", "chat",
                                     "available", "free", "time", "slot", "1:1", "connect", "talk")
    big_from_people: int = 4  # this many people or more → the big-batch model chain
    models_small: tuple[ModelChoice, ...] = (ModelChoice("gemma-4-31b-it", False),
                                             ModelChoice("gemini-3.1-flash-lite"))
    models_big: tuple[ModelChoice, ...] = (ModelChoice("gemini-3.1-flash-lite"),
                                           ModelChoice("gemini-3.5-flash-lite"),
                                           ModelChoice("gemma-4-31b-it", False))
    templates: Templates = field(default_factory=Templates)
    style: str = DEFAULT_STYLE

    def models_for(self, people: int) -> tuple[ModelChoice, ...]:
        return self.models_big if people >= self.big_from_people else self.models_small


def _models(raw: Any, default: tuple[ModelChoice, ...]) -> tuple[ModelChoice, ...]:
    if not raw:
        return default
    return tuple(ModelChoice(str(m["id"]), bool(m.get("json_mode", True))) for m in raw)


def parse(raw: dict[str, Any], style: str = "") -> Settings:
    out = raw.get("outreach") or {}
    base = Settings()
    known = Templates.__dataclass_fields__
    return Settings(
        timezone=str(raw.get("timezone", base.timezone)),
        daily_cap=int(out.get("daily_cap", base.daily_cap)),
        preview_minutes=int(out.get("preview_minutes", base.preview_minutes)),
        gap_minutes=int(out.get("gap_minutes", base.gap_minutes)),
        default_length=int(out.get("default_length", base.default_length)),
        allhands_length=int(out.get("allhands_length", base.allhands_length)),
        teams=bool(out.get("teams", base.teams)),
        detect_days=int(out.get("detect_days", base.detect_days)),
        detect_words=tuple(str(w).lower() for w in out.get("detect_words") or base.detect_words),
        big_from_people=int(out.get("big_from_people", base.big_from_people)),
        models_small=_models(out.get("models_small"), base.models_small),
        models_big=_models(out.get("models_big"), base.models_big),
        templates=Templates(**{k: str(v) for k, v in (out.get("templates") or {}).items() if k in known}),
        style=style.strip()[:STYLE_LIMIT] or base.style,
    )


def load(state_dir: Path) -> Settings:
    path = state_dir / "brief.yaml"
    raw = yaml.safe_load((path if path.is_file() else EXAMPLE).read_text(encoding="utf-8")) or {}
    style = state_dir / STYLE_FILE
    return parse(raw, style.read_text(encoding="utf-8") if style.is_file() else "")
