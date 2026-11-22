"""Script-side filtering: everything that decides what the model never needs to see."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .items import Item
from .settings import Settings

CHARS_PER_TOKEN = 4  # rough budget estimate; real counts are checked by the provider


@dataclass(frozen=True)
class Dropped:
    seen: int = 0
    newsletters: int = 0
    noise: int = 0
    private: int = 0
    muted: int = 0
    over_budget: int = 0


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(n and n in low for n in needles)


def _is_newsletter(item: Item, settings: Settings) -> bool:
    return item.newsletter and not _contains_any(item.sender, settings.keep_newsletters_from)


def _is_mail(item: Item) -> bool:
    return item.source in ("gmail", "outlook")


def _is_noise(item: Item, settings: Settings) -> bool:
    """One-time codes and sign-in links: expired by the time the brief arrives."""
    return _is_mail(item) and any(re.search(p, item.title, re.IGNORECASE) for p in settings.noise_subject_patterns)


def _is_private(item: Item, settings: Settings) -> bool:
    """Money and HR mail: listed by the script, never sent to the model. Whole words only, so
    'tax' does not match 'syntax'."""
    if not _is_mail(item):
        return False
    words = settings.private_subject_words
    return _contains_any(item.sender, settings.private_senders) or any(
        re.search(rf"\b{re.escape(w)}\b", item.title, re.IGNORECASE) for w in words if w)


def _is_muted(item: Item, settings: Settings) -> bool:
    return _contains_any(item.sender, settings.all_muted_senders()) or _contains_any(
        f"{item.title} {item.snippet}", settings.all_muted_words())


def keep(items: list[Item], settings: Settings, is_seen) -> tuple[list[Item], list[Item], Dropped]:
    """Split items into (for the model, private: listed without the model, counts of what was
    dropped). Drops seen, newsletters, one-time codes and muted items. Order is kept."""
    counts = {"seen": 0, "newsletters": 0, "noise": 0, "private": 0, "muted": 0}
    kept, private = [], []
    for item in items:
        reason = ("seen" if is_seen(item.uid) else
                  "newsletters" if _is_newsletter(item, settings) else
                  "noise" if _is_noise(item, settings) else
                  "muted" if _is_muted(item, settings) else
                  "private" if _is_private(item, settings) else "")
        if reason:
            counts[reason] += 1
        if reason == "private":
            private.append(item)
        elif not reason:
            kept.append(item)
    return kept, private, Dropped(**counts)


def cap_news(news: list[Item], settings: Settings) -> list[Item]:
    """At most ``per_run`` newest items per topic go to the model."""
    limits = {t.name: t.per_run for t in settings.all_topics()}
    used: dict[str, int] = {}
    out = []
    for item in news:
        used[item.topic] = used.get(item.topic, 0) + 1
        if used[item.topic] <= limits.get(item.topic, 5):
            out.append(item)
    return out


def item_cost(item: Item) -> int:
    return (len(item.title) + len(item.snippet) + len(item.sender) + len(item.where) + 40) // CHARS_PER_TOKEN


def fit_budget(items: list[Item], budget_tokens: int) -> tuple[list[Item], list[Item]]:
    """Fill the prompt budget round-robin across sources so one noisy source cannot crowd out
    the rest. Returns (fits, left_over); left_over still appears in /brief more."""
    queues: dict[str, list[Item]] = {}
    for item in items:
        queues.setdefault(item.source, []).append(item)
    fits: list[Item] = []
    spent = 0
    while any(queues.values()):
        for source in list(queues):
            if not queues[source]:
                continue
            item = queues[source][0]
            if spent + item_cost(item) > budget_tokens:
                queues[source] = []
                continue
            fits.append(queues[source].pop(0))
            spent += item_cost(item)
    chosen = {i.uid for i in fits}
    return fits, [i for i in items if i.uid not in chosen]
