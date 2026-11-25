"""Call 0, before the script: a researcher finds the current facts on the topic with web search.

Its own job and its own prompt (``prompts/research.md``): current numbers, dates and names, surprising
details, a quote, and corrections to your notes, one line each with its site. The findings are added to
your notes under a heading, so the script writer and the director use them like anything you wrote, and
the evidence checks (``rules.py``: a number on screen must be in the notes) count them too. Their sources
travel with the video to Telegram.

Who searches (``studio.researcher``, default auto): when Claude writes, Claude researches too and Gemini is
not called: with an API key, Claude's own web search tool (``llm.claude_search``); through the handoff,
the job's first issue (``ENDING``; the repo's settings keep web search and fetch for it). Otherwise search
runs on Gemini first (``studio.research_models``; on the free tier only some models may search: the
2.5 ones could on 2026-11-24, the 3.x ones could not). A busy model hands over to the next. When none can
search and Claude writes through the handoff repo, Claude does the research too, as the job's first issue
(``ENDING``: it writes ``research.txt``); otherwise the video is written from your notes alone and you are
told why.
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
ANSWER = "research.txt"
ENDING = ("\nUse web search. Write only the fact lines to `studio/$job/research.txt`, then in one command commit, "
          "push to main and close this issue.\n")
SITE = re.compile(r"\(([\w.-]+\.[a-z]{2,})\b[^()]*\)\.?\s*$")
FACT = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+)$")
MAX_FACTS = 25


@dataclass(frozen=True)
class Findings:
    facts: tuple[str, ...]  # one line each, with its site and date
    sources: tuple[tuple[str, str], ...]  # (site, link) as the search returned them
    model: str = ""
    skipped: str = ""  # why there are none ("" = there are)

    def notes(self, notes: str, today: date) -> str:
        """Your notes with the findings added under a heading (your notes alone when there are none)."""
        if not self.facts:
            return notes
        lines = "\n".join(f"- {f}" for f in self.facts)
        return f"{notes.strip()}\n\n{HEADING} (found with web search on {today:%d %B %Y}):\n{lines}\n"

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
    """The answer's fact lines, each once: a line saying what an earlier one said in other words is dropped."""
    rows = [ln.strip() for ln in answer.splitlines() if ln.strip()]
    bulleted = [m.group(1).strip() for m in map(FACT.match, rows) if m]
    # some models drop the "- ": then every line that is a sentence (not a heading or a lead-in) is a fact
    lines = bulleted or [ln for ln in rows if not ln.startswith("#") and not ln.endswith(":")]
    kept: list[tuple[str, set[str]]] = []
    for line in lines:
        words = set(re.findall(r"\w{4,}", line.lower()))
        if len(line.split()) >= 3 and not any(len(words & seen) >= 0.7 * len(words | seen) for _l, seen in kept):
            kept.append((line, words))
    return tuple(line for line, _w in kept)[:MAX_FACTS]


def ask(notes: str, seconds: float, today: date) -> str:
    return Template(PROMPT.read_text(encoding="utf-8")).substitute(
        today=f"{today:%d %B %Y}", seconds=round(seconds), notes=notes.strip())


def for_claude(notes: str, seconds: float, today: date, job: str) -> str:
    """The same prompt as an issue body for Claude on your plan."""
    return ask(notes, seconds, today) + Template(ENDING).substitute(job=job)


def from_claude(text: str) -> Findings:
    """Claude's research.txt → findings; the sites come from each line's "(site, date)"."""
    found = facts(text)
    sites = [m.group(1) for m in map(SITE.search, found) if m]
    return Findings(found, tuple((site, "") for site in dict.fromkeys(sites)), "claude (handoff)",
                    "" if found else "Claude's research had no facts")


def by_claude(settings: Settings, how: str) -> bool:
    """Claude researches when it writes too (studio.researcher: auto), or always (claude)."""
    return settings.researcher == "claude" or (settings.researcher == "auto" and how in ("claude-api", "handoff"))


def _claude(http: Http, keys: Keys, settings: Settings, prompt: str) -> Findings:
    """A separate, smaller Claude (studio.research_claude) does the searching: search results are long and
    are read at that model's price, and the writer only gets the fact lines."""
    model = settings.research_claude or settings.claude_model
    try:
        answer, sources = llm.claude_search(http, keys.claude, model, prompt, workflow="studio", step="research",
                                            effort="medium")
    except HttpError as exc:
        return Findings((), (), skipped=f"{model}: {'no connection' if exc.status == 0 else f'HTTP {exc.status}'}")
    except ValueError as exc:
        return Findings((), (), skipped=f"{model}: {exc}")
    found = facts(answer)
    return Findings(found, tuple(sources), model) if found else Findings((), (), skipped=f"{model}: no facts in the answer")


def gather(http: Http, keys: Keys, settings: Settings, notes: str, seconds: float, today: date,
           how: str = "") -> Findings:
    """The findings, or none with the reason (research off, no key, every model unable to search). Claude
    with an API key searches itself when ``by_claude``; Gemini is not called then."""
    if not settings.research:
        return Findings((), (), skipped="studio.research is off")
    if by_claude(settings, how) and keys.claude:
        return _claude(http, keys, settings, ask(notes, seconds, today))
    if by_claude(settings, how) and how == "handoff":
        return Findings((), (), skipped="Claude researches through the handoff")
    if not keys.gemini:
        return Findings((), (), skipped="no GEMINI_API_KEY")
    prompt, tried = ask(notes, seconds, today), []
    for model in settings.research_models:
        try:
            answer, sources = llm.gemini_search(http, keys.gemini, model.id, prompt, workflow="studio", step="research")
        except HttpError as exc:  # status 0: the network or a timeout; 429: quota used up; 503: busy
            tried.append(f"{model.id}: {'no connection' if exc.status == 0 else f'HTTP {exc.status}'}")
            continue
        except ValueError:  # an answer that is not JSON
            tried.append(f"{model.id}: an unreadable answer")
            continue
        found = facts(answer)
        if found:
            return Findings(found, tuple(sources), model.id)
        tried.append(f"{model.id}: no facts in the answer")
    return Findings((), (), skipped="; ".join(tried))


def add_to(http: Http, keys: Keys, settings: Settings, notes: str, seconds: float, folder: Path,
           how: str = "") -> tuple[str, Findings]:
    """Researches, keeps the findings in ``folder`` (research.json), returns (your notes + the findings, them)."""
    today = date.today()
    found = gather(http, keys, settings, notes, seconds, today, how)
    folder.mkdir(parents=True, exist_ok=True)
    found.save(folder)
    return found.notes(notes, today), found


def summary(found: Findings) -> str:
    """One line for the job's log and your reply."""
    if not found.facts:
        return f"research skipped ({found.skipped})"
    return f"research: {len(found.facts)} facts by {found.model} from {', '.join(found.sites()[:6]) or 'web search'}"
