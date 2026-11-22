"""The one model call: rank and summarise what the scripts kept. Gemini free tier only.

Each model in ``ranking.models`` is tried in order; a rate limit, server error, timeout or
unparseable answer moves to the next. If all fail the brief still goes out, unranked (newest
first per source) and says so.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from orchestrator import llm

from .items import Item
from .net import Http, HttpError
from .settings import ModelChoice, Settings

MAX_OUTPUT_TOKENS = 1200

INSTRUCTIONS = """You pick the most important items for a busy founder's 8am brief (Mumbai, India).
Interests, by weight: {topics}.
Slack groups, by weight: {groups}.
Work items (Slack, Gmail, Outlook) that need a reply, a decision or carry a deadline outrank news.
Skip routine notifications, automated alerts that need no action, and duplicates of the same story.
Return JSON only: {{"top": [{{"id": "<item id>", "line": "<one sentence, max 22 words, what it is and why it matters>"}}]}}
Pick at most {n} items, most important first. Use only ids from the list. Never invent facts.

Items (id | source | where | from | title | detail):
{items}"""


@dataclass(frozen=True)
class Ranked:
    items: tuple[Item, ...]
    lines: dict[str, str]
    model: str  # '' when no model answered
    errors: tuple[str, ...] = ()


def build_prompt(items: list[Item], settings: Settings) -> tuple[str, dict[str, Item]]:
    """Short positional ids (i1, i2, ...) keep the prompt small and the answer checkable."""
    by_id = {f"i{n}": item for n, item in enumerate(items, start=1)}
    rows = [
        " | ".join((key, i.source, i.topic or i.where, i.sender[:40], i.title, i.snippet[:200]))
        for key, i in by_id.items()
    ]
    topics = ", ".join(f"{t.name} ({t.weight:g})" for t in settings.all_topics())
    groups = ", ".join(f"{g} ({w:g})" for g, w in settings.slack_group_weights) or "all equal"
    text = INSTRUCTIONS.format(topics=topics, groups=groups, n=settings.top_items, items="\n".join(rows))
    return text, by_id


def parse_answer(text: str, by_id: dict[str, Item], limit: int) -> tuple[list[Item], dict[str, str]]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON in the answer")
    top = json.loads(match.group(0)).get("top") or []
    picked: list[Item] = []
    lines: dict[str, str] = {}
    for entry in top:
        item = by_id.get(str(entry.get("id", "")).strip())
        if item is None or item.uid in lines:
            continue  # unknown or repeated id: ignore rather than trust it
        picked.append(item)
        lines[item.uid] = " ".join(str(entry.get("line", "")).split())[:220]
        if len(picked) >= limit:
            break
    if not picked:
        raise ValueError("answer named no known item")
    return picked, lines


def _call(http: Http, api_key: str, model: ModelChoice, prompt: str) -> str:
    return llm.gemini(http, api_key, model.id, prompt, workflow="brief", step="rank", json_mode=model.json_mode,
                      max_output_tokens=MAX_OUTPUT_TOKENS)


def unranked(items: list[Item], limit: int) -> list[Item]:
    """Fallback order: newest work items, then news taking one item per topic in turn."""
    work = sorted((i for i in items if i.source != "news"), key=lambda i: i.ts, reverse=True)
    by_topic: dict[str, list[Item]] = {}
    for item in items:
        if item.source == "news":
            by_topic.setdefault(item.topic, []).append(item)
    news: list[Item] = []
    while any(by_topic.values()):
        news += [queue.pop(0) for queue in by_topic.values() if queue]
    return (work + news)[:limit]


def rank(http: Http, api_key: str, items: list[Item], settings: Settings) -> Ranked:
    if not items:
        return Ranked((), {}, "")
    if not api_key:
        return Ranked(tuple(unranked(items, settings.top_items)), {}, "", ("GEMINI_API_KEY not set",))
    prompt, by_id = build_prompt(items, settings)
    errors: list[str] = []
    for model in settings.models:
        try:
            picked, lines = parse_answer(_call(http, api_key, model, prompt), by_id, settings.top_items)
            return Ranked(tuple(picked), lines, model.id, tuple(errors))
        except (HttpError, ValueError, KeyError, IndexError) as exc:
            errors.append(f"{model.id}: {exc}")
    return Ranked(tuple(unranked(items, settings.top_items)), {}, "", tuple(errors))
