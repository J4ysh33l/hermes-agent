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

MAX_OUTPUT_TOKENS = 2000  # up to top_items + work_items lines of JSON

INSTRUCTIONS = """You write a busy founder's 8am brief (Mumbai, India). It has two lists.
"news": the {n} most important news items, by these interests and weights: {topics}.
"work": up to {w} Slack, Gmail and Outlook items worth reading, most important first. Items that need
a reply, a decision or carry a deadline come first. Slack groups, by weight: {groups}.
Skip routine notifications, automated alerts that need no action, and duplicates of the same story.
Each line: one sentence, max 22 words, what it is and why it matters. Do not start with or repeat the
sender's name; the brief shows it next to the line.
Return JSON only: {{"news": [{{"id": "<item id>", "line": "..."}}], "work": [{{"id": "<item id>", "line": "..."}}]}}
Use only ids from the list. Never invent facts.

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
        " | ".join((key, i.source, " · ".join(p for p in (i.topic, i.where) if p), i.sender[:40], i.title,
                    i.snippet[:200]))
        for key, i in by_id.items()
    ]
    topics = ", ".join(f"{t.name} ({t.weight:g})" for t in settings.all_topics())
    groups = ", ".join(f"{g} ({w:g})" for g, w in settings.slack_group_weights) or "all equal"
    text = INSTRUCTIONS.format(topics=topics, groups=groups, n=settings.top_items, w=settings.work_items,
                              items="\n".join(rows))
    return text, by_id


def _limits(settings: Settings) -> dict[bool, int]:
    """Keyed by 'is news'."""
    return {True: settings.top_items, False: settings.work_items}


def parse_answer(text: str, by_id: dict[str, Item], limits: dict[bool, int]) -> tuple[list[Item], dict[str, str]]:
    """Both lists are read; an item counts against news or work by its real source, whichever
    list the model put it in."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON in the answer")
    answer = json.loads(match.group(0))
    picked: list[Item] = []
    lines: dict[str, str] = {}
    room = dict(limits)
    for entry in (answer.get("work") or []) + (answer.get("news") or []):
        item = by_id.get(str(entry.get("id", "")).strip())
        if item is None or item.uid in lines or not room[item.source == "news"]:
            continue  # unknown, repeated or over its list's limit: ignore rather than trust it
        room[item.source == "news"] -= 1
        picked.append(item)
        lines[item.uid] = " ".join(str(entry.get("line", "")).split())[:220]
    if not picked:
        raise ValueError("answer named no known item")
    return picked, lines


def _call(http: Http, api_key: str, model: ModelChoice, prompt: str) -> str:
    return llm.gemini(http, api_key, model.id, prompt, workflow="brief", step="rank", json_mode=model.json_mode,
                      max_output_tokens=MAX_OUTPUT_TOKENS)


def unranked(items: list[Item], limits: dict[bool, int]) -> list[Item]:
    """Fallback order: newest work items, then news taking one item per topic in turn."""
    work = sorted((i for i in items if i.source != "news"), key=lambda i: i.ts, reverse=True)
    by_topic: dict[str, list[Item]] = {}
    for item in items:
        if item.source == "news":
            by_topic.setdefault(item.topic, []).append(item)
    news: list[Item] = []
    while any(by_topic.values()):
        news += [queue.pop(0) for queue in by_topic.values() if queue]
    return work[:limits[False]] + news[:limits[True]]


def rank(http: Http, api_key: str, items: list[Item], settings: Settings) -> Ranked:
    if not items:
        return Ranked((), {}, "")
    if not api_key:
        return Ranked(tuple(unranked(items, _limits(settings))), {}, "", ("GEMINI_API_KEY not set",))
    prompt, by_id = build_prompt(items, settings)
    errors: list[str] = []
    for model in settings.models:
        try:
            picked, lines = parse_answer(_call(http, api_key, model, prompt), by_id, _limits(settings))
            return Ranked(tuple(picked), lines, model.id, tuple(errors))
        except (HttpError, ValueError, KeyError, IndexError) as exc:
            errors.append(f"{model.id}: {exc}")
    return Ranked(tuple(unranked(items, _limits(settings))), {}, "", tuple(errors))
