"""Openverse (api.openverse.org): the Creative Commons search engine, no key needed. The studio asks it for
CC0 and public-domain works only (``LICENCES``): no permission to track and no attribution owed, though we
credit anyway. Images come from Flickr, Wikimedia and others; audio (music beds) from Freesound.

Search is by words in a work's title and tags, so results drift (a "bullet train" search ranks a photo from
the film's premiere): ``relevance`` scores each result by how many of the query's words it carries, and the
callers keep only results that match most of them. Anonymous use allows 20 searches a minute and 200 a day;
the callers cache by query, so a video costs a few searches once.
"""

from __future__ import annotations

import re
from typing import Any

from orchestrator.brief.net import Http, HttpError

API = "https://api.openverse.org/v1"
LICENCES = "cc0,pdm"
LICENCE_NAMES = {"cc0": "CC0 1.0 (public domain dedication)", "pdm": "Public Domain Mark"}
STOP = {"a", "an", "the", "of", "in", "on", "at", "and", "with", "for", "to", "by", "music", "background"}


def search(http: Http, kind: str, query: str, **filters: str) -> list[dict[str, Any]]:
    """``kind`` "images" or "audio"; CC0/public-domain, non-mature results, best first ([] when Openverse
    cannot be reached or refuses: the caller falls back)."""
    params = {"q": query, "license": LICENCES, "mature": "false", "page_size": "20", **filters}
    try:
        found = http.request("GET", f"{API}/{kind}/", params=params).json()
    except (HttpError, ValueError):
        return []
    return [r for r in found.get("results") or [] if isinstance(r, dict) and r.get("url")
            and str(r.get("license", "")).lower() in LICENCE_NAMES and not r.get("unstable__sensitivity")]


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1}


def relevance(result: dict[str, Any], query: str) -> float:
    """The share of the query's words found in the result's title and tags (0–1)."""
    wanted = words(query)
    if not wanted:
        return 0.0
    tags = " ".join(str(t.get("name", "")) for t in result.get("tags") or [] if isinstance(t, dict))
    have = words(f"{result.get('title', '')} {tags}")
    # a word counts when the result has it or a longer form of it ("train" in "trains")
    return sum(1 for w in wanted if any(h.startswith(w) for h in have)) / len(wanted)


def credit(result: dict[str, Any], what: str) -> str:
    licence = LICENCE_NAMES[str(result["license"]).lower()]
    title = str(result.get("title") or "untitled")[:60]
    return (f"{what} \"{title}\" by {result.get('creator') or 'unknown'} via Openverse/{result.get('provider', '?')}, "
            f"{licence} ({result.get('foreign_landing_url', '')})")
