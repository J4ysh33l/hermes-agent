"""Call 0, before the script: a researcher finds the current facts on the topic with Google Search.

Its own job and its own prompt (``prompts/research.md``): current numbers, dates and names, surprising
details, a quote, and corrections to your notes, one line each with its site. The findings are added to
your notes under a heading, so the script writer and the director use them like anything you wrote, and
the evidence checks (``rules.py``: a number on screen must be in the notes) count them too. Their sources
travel with the video to Telegram.

Search runs on Gemini (``studio.research_models``; on the free tier only some models may search: the 2.5
ones could on 2026-11-24, the 3.x ones could not), whoever writes the script, so Claude's sessions need no
web access. A busy model hands over to the next; when none can search, the video is written from your notes
alone and you are told why.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from string import Template

from orchestrator import llm
from orchestrator.brief.net import Http, HttpError

from .settings import Keys, Settings

PROMPT = Path(__file__).with_name("prompts") / "research.md"
HEADING = "Research"
FACT = re.compile(r"^\s*[-*•]\s+(.+)$")
MAX_FACTS = 25


@dataclass(frozen=True)
class Findings:
    facts: tuple[str, ...]  # one line each, with its site and date
    sources: tuple[tuple[str, str], ...]  # (site, link) as Google Search returned them
    model: str = ""
    skipped: str = ""  # why there are none ("" = there are)

    def notes(self, notes: str, today: date) -> str:
        """Your notes with the findings added under a heading (your notes alone when there are none)."""
        if not self.facts:
            return notes
        lines = "\n".join(f"- {f}" for f in self.facts)
        return f"{notes.strip()}\n\n{HEADING} (found with Google Search on {today:%d %B %Y}):\n{lines}\n"

    def sites(self) -> list[str]:
        return list(dict.fromkeys(site for site, _link in self.sources if site))

    def save(self, folder: Path) -> None:
        folder.joinpath("research.json").write_text(json.dumps(
            {"model": self.model, "skipped": self.skipped, "facts": list(self.facts),
             "sources": [list(s) for s in self.sources]}, ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, folder: Path) -> Findings:
        path = folder / "research.json"
        if not path.is_file():
            return cls((), (), skipped="not run")
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(tuple(raw["facts"]), tuple(tuple(s) for s in raw["sources"]), raw["model"], raw["skipped"])


def facts(answer: str) -> tuple[str, ...]:
    found = [m.group(1).strip() for m in map(FACT.match, answer.splitlines()) if m]
    return tuple(f for f in found if len(f.split()) >= 3)[:MAX_FACTS]


def gather(http: Http, keys: Keys, settings: Settings, notes: str, seconds: float, today: date) -> Findings:
    """The findings, or none with the reason (research off, no key, every model unable to search)."""
    if not settings.research:
        return Findings((), (), skipped="studio.research is off")
    if not keys.gemini:
        return Findings((), (), skipped="no GEMINI_API_KEY")
    prompt = Template(PROMPT.read_text(encoding="utf-8")).substitute(
        today=f"{today:%d %B %Y}", seconds=round(seconds), notes=notes.strip())
    tried = []
    for model in settings.research_models:
        try:
            answer, sources = llm.gemini_search(http, keys.gemini, model.id, prompt, workflow="studio", step="research")
        except HttpError as exc:
            tried.append(f"{model.id}: HTTP {exc.status}")
            continue
        found = facts(answer)
        if found:
            return Findings(found, tuple(sources), model.id)
        tried.append(f"{model.id}: no facts in the answer")
    return Findings((), (), skipped="; ".join(tried))


def add_to(http: Http, keys: Keys, settings: Settings, notes: str, seconds: float, folder: Path) -> tuple[str, Findings]:
    """Researches, keeps the findings in ``folder`` (research.json), returns (your notes + the findings, them)."""
    today = date.today()
    found = gather(http, keys, settings, notes, seconds, today)
    folder.mkdir(parents=True, exist_ok=True)
    found.save(folder)
    return found.notes(notes, today), found


def summary(found: Findings) -> str:
    """One line for the job's log and your reply."""
    if not found.facts:
        return f"research skipped ({found.skipped})"
    return f"research: {len(found.facts)} facts by {found.model} from {', '.join(found.sites()[:6]) or 'Google Search'}"
