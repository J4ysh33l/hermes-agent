"""Script-side filtering: everything that decides what the model never needs to see."""

from __future__ import annotations

from dataclasses import dataclass

from .items import Item
from .settings import Settings

CHARS_PER_TOKEN = 4  # rough budget estimate; real counts are checked by the provider


@dataclass(frozen=True)
class Dropped:
    seen: int = 0
    newsletters: int = 0
    excluded_mail: int = 0
    muted: int = 0
    over_budget: int = 0


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(n and n in low for n in needles)


def _is_newsletter(item: Item, settings: Settings) -> bool:
    return item.newsletter and not _contains_any(item.sender, settings.keep_newsletters_from)


def _is_excluded_mail(item: Item, settings: Settings) -> bool:
    """Finance and HR mail never reaches the model."""
    if item.source not in ("gmail", "outlook"):
        return False
    return _contains_any(item.sender, settings.exclude_senders) or _contains_any(
        item.title, settings.exclude_subject_words)


def _is_muted(item: Item, settings: Settings) -> bool:
    return _contains_any(item.sender, settings.all_muted_senders()) or _contains_any(
        f"{item.title} {item.snippet}", settings.all_muted_words())


def keep(items: list[Item], settings: Settings, is_seen) -> tuple[list[Item], Dropped]:
    """Drop seen, newsletter, finance/HR and muted items. Order is kept."""
    counts = {"seen": 0, "newsletters": 0, "excluded_mail": 0, "muted": 0}
    kept = []
    for item in items:
        reason = ("seen" if is_seen(item.uid) else
                  "newsletters" if _is_newsletter(item, settings) else
                  "excluded_mail" if _is_excluded_mail(item, settings) else
                  "muted" if _is_muted(item, settings) else "")
        if reason:
            counts[reason] += 1
        else:
            kept.append(item)
    return kept, Dropped(**counts)


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
