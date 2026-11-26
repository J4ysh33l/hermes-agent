"""Duties and responsibilities per position: written once by a model, then kept.

``$HERMES_HOME/hr/duties.json`` (0600) holds one entry per position, keyed by its normalised title
("Marketing Intern", "marketing  intern." → ``marketing intern``)::

    {"marketing intern": {"position": "Marketing Intern", "duties": ["...", ...],
                          "by": "gemma-4-31b-it", "saved": "2026-11-26"}}

The next offer for the same position reads it, so only a new position costs a model call. You can
set or change an entry yourself (``/hr duties <position> = a; b; c``), or forget it so the next offer
asks the model again.

Every kind of offer (internship, full-time, consultant) uses the same table, keyed by position.

The call: one ``generateContent`` with only the position title, the kind of offer and what the company
does (never a person's name, pay or dates), on its own key ``HR_GEMINI_API_KEY``. Models are tried in order (``hr.duties_models``: Gemma 4 31B, Gemma 4
26B, then Gemini Flash-Lite); the next is tried only when one fails or its answer does not pass the
checks, so a normal run is exactly one call.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from orchestrator import llm
from orchestrator.brief.net import Http, HttpError

FILE = "duties.json"
KEY_NAME = "HR_GEMINI_API_KEY"  # the duties call's own key in $HERMES_HOME/.env (GEMINI_API_KEY if it is not set)
MIN_DUTIES, MAX_DUTIES = 4, 6
MIN_WORDS, MAX_WORDS = 5, 40

PROMPT = """List the duties and responsibilities for an offer letter.
Company: {company}, {about}.
Position: {position} ({role})
Rules:
- Exactly {count} duties, each ONE sentence of 8 to 25 words, starting with a verb (e.g. "Assist", "Prepare").
- Specific to this position's day-to-day work; suitable for a formal offer letter in Indian English.
- No names, numbers, dates, targets, pay, tools you are unsure the company uses, or promises.
- No bullets or numbering inside the sentences.
Answer JSON only: {{"duties": ["...", "..."]}}"""
SCHEMA = {"type": "object", "properties": {"duties": {"type": "array", "items": {"type": "string"}}},
          "required": ["duties"]}


class DutiesError(Exception):
    """Shown to you as it is; no letter was made."""


@dataclass(frozen=True)
class Duties:
    position: str
    items: tuple[str, ...]
    by: str  # a model id, "you", or "" for an empty result
    saved: bool  # True when read from the table (no call was made)


def key(position: str) -> str:
    return " ".join(re.sub(r"[^\w&+/ -]", " ", position.lower()).split())


class Table:
    def __init__(self, home: Path) -> None:
        self.path = home / FILE
        self.rows: dict[str, dict] = (json.loads(self.path.read_text(encoding="utf-8"))
                                      if self.path.is_file() else {})

    def get(self, position: str) -> Duties | None:
        row = self.rows.get(key(position))
        return Duties(row["position"], tuple(row["duties"]), row.get("by", ""), True) if row else None

    def put(self, position: str, items: list[str] | tuple[str, ...], by: str, today: date) -> None:
        self.rows[key(position)] = {"position": position.strip(), "duties": list(items), "by": by,
                                    "saved": today.isoformat()}
        self._save()

    def forget(self, position: str) -> bool:
        gone = self.rows.pop(key(position), None) is not None
        if gone:
            self._save()
        return gone

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.rows, fh, indent=1, ensure_ascii=False)
        tmp.replace(self.path)


def clean(items: list[str]) -> list[str]:
    """One sentence each: bullets and numbering stripped, a full stop added."""
    out = []
    for item in items:
        text = re.sub(r"^\s*(?:[-*•·]|\d+[.)])\s*", "", " ".join(str(item).split())).strip()
        if text:
            out.append(text[0].upper() + text[1:] + ("" if text.endswith((".", "!")) else "."))
    return out


def problems(items: list[str]) -> list[str]:
    found = []
    if not MIN_DUTIES <= len(items) <= MAX_DUTIES:
        found.append(f"{len(items)} duties (need {MIN_DUTIES} to {MAX_DUTIES})")
    for item in items:
        words = len(item.split())
        if not MIN_WORDS <= words <= MAX_WORDS:
            found.append(f"a duty of {words} words: {item[:60]!r}")
        if re.search(r"[\[\]{}<>@]|https?:", item):
            found.append(f"a placeholder, link or address in {item[:60]!r}")
    return found


def _answer(text: str) -> list[str]:
    """JSON {"duties": [...]}; a model without JSON mode (Gemma) may wrap it in prose or a code fence,
    or answer a plain bulleted list."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            items = json.loads(match.group(0)).get("duties")
        except (json.JSONDecodeError, AttributeError):
            items = None
        if isinstance(items, list) and all(isinstance(i, str) for i in items):
            return clean(items)
    lines = [ln for ln in text.splitlines() if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+\S", ln)]
    if lines:
        return clean(lines)
    raise ValueError("no duties list in the answer")


def write(http: Http, key_: str, models, position: str, company: str, about: str,
          count: int = 5, role: str = "internship") -> Duties:
    """One model call that passed the checks; the next model only when one fails."""
    if not key_:
        raise DutiesError(f"{KEY_NAME} is not set in $HERMES_HOME/.env, and no duties are saved for "
                          f"{position!r}. Set them yourself: /hr duties {position} = first duty; second duty; …")
    prompt = PROMPT.format(company=company, about=about, position=position.strip(), count=count, role=role)
    failures = []
    for model in models:
        try:
            raw = llm.gemini(http, key_, model.id, prompt, workflow="hr", step="duties",
                             json_mode=model.json_mode, schema=SCHEMA if model.json_mode else None,
                             max_output_tokens=1500, temperature=0.3)
            items = _answer(raw)
        except (HttpError, ValueError) as exc:
            failures.append(f"{model.id}: {str(exc)[:120]}")
            continue
        found = problems(items)
        if found:
            failures.append(f"{model.id}: " + "; ".join(found)[:200])
            continue
        return Duties(position.strip(), tuple(items), model.id, False)
    raise DutiesError("No model wrote duties that passed the checks:\n" + "\n".join(f"• {f}" for f in failures) +
                      f"\nSet them yourself: /hr duties {position} = first duty; second duty; …")


def find_or_write(table: Table, http: Http, key_: str, models, position: str, company: str, about: str,
                  today: date, count: int = 5, role: str = "internship") -> Duties:
    """The saved duties for this position, else one model call whose answer is saved for next time."""
    saved = table.get(position)
    if saved:
        return saved
    made = write(http, key_, models, position, company, about, count, role)
    table.put(position, made.items, made.by, today)
    return made
