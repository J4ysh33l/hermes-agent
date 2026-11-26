"""Openverse (api.openverse.org): the Creative Commons search engine, no key needed. The studio asks it for
CC0 and public-domain works only (``LICENCES``): no permission to track and no attribution owed, though we
credit anyway. Images come from Flickr, Wikimedia and others; audio (music beds) from Freesound.

Search is by words in a work's title and tags, so results drift (a "bullet train" search ranks a photo from
the film's premiere): ``relevance`` scores each result by how many of the query's words it carries, and the
callers keep only results that match most of them. Anonymous use allows 20 searches a minute and 200 a day;
the callers cache by query, so a video costs a few searches once.

When Openverse throttles (HTTP 429, "available in N seconds") no further search is sent until then, and
``blocked()`` says so, so a caller can tell "rate-limited" from "nothing found". A registered client
(``OPENVERSE_CLIENT_ID`` + ``OPENVERSE_CLIENT_SECRET`` in $HERMES_HOME/.env; free, see
https://api.openverse.org/v1/#tag/auth) gets a far higher limit; its token is fetched once per run.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from orchestrator.brief.net import Http, HttpError

API = "https://api.openverse.org/v1"
LICENCES = "cc0,pdm"
LICENCE_NAMES = {"cc0": "CC0 1.0 (public domain dedication)", "pdm": "Public Domain Mark", "by": "CC BY"}
STOP = {"a", "an", "the", "of", "in", "on", "at", "and", "with", "for", "to", "by", "music", "background"}


_state: dict[str, Any] = {"until": 0.0, "token": None}  # throttled until (epoch s); the client token


def reset() -> None:
    """Forget a throttle and the token (a new run; tests)."""
    _state.update(until=0.0, token=None)


def blocked(now: float | None = None) -> str:
    """Why searches are not being sent right now ("" = they are)."""
    left = _state["until"] - (time.time() if now is None else now)
    return f"Openverse is rate-limiting this server for ~{max(1, round(left / 60))} more min" if left > 0 else ""


def _secret(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    env = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name:
                return value.strip().strip('"').strip("'")
    return ""


def _headers(http: Http) -> dict[str, str]:
    """A registered client's bearer token, when one is configured (fetched once per run)."""
    if _state["token"] is None:
        _state["token"] = ""
        cid, secret = _secret("OPENVERSE_CLIENT_ID"), _secret("OPENVERSE_CLIENT_SECRET")
        if cid and secret:
            try:
                _state["token"] = str(http.request("POST", f"{API}/auth_tokens/token/", form={
                    "client_id": cid, "client_secret": secret, "grant_type": "client_credentials"}).json()
                    .get("access_token") or "")
            except (HttpError, ValueError):
                pass  # anonymous, then
    return {"Authorization": f"Bearer {_state['token']}"} if _state["token"] else {}


def search(http: Http, kind: str, query: str, licences: str = LICENCES, **filters: str) -> list[dict[str, Any]]:
    """``kind`` "images" or "audio"; ``licences`` (CC0/public-domain unless asked), non-mature results, best
    first ([] when Openverse cannot be reached, refuses or is throttling us: see ``blocked``)."""
    if blocked():
        return []
    params = {"q": query, "license": licences, "mature": "false", "page_size": "20", **filters}
    allowed = set(licences.split(","))
    try:
        found = http.request("GET", f"{API}/{kind}/", params=params, headers=_headers(http)).json()
    except HttpError as exc:
        if exc.status == 429:  # "Expected available in 3336 seconds."
            wait = re.search(r"available in (\d+) seconds", str(exc))
            _state["until"] = time.time() + (int(wait.group(1)) if wait else 3600)
        return []
    except ValueError:
        return []
    return [r for r in found.get("results") or [] if isinstance(r, dict) and r.get("url")
            and str(r.get("license", "")).lower() in allowed and not r.get("unstable__sensitivity")]


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1}


def relevance(result: dict[str, Any], query: str) -> float:
    """The share of the query's words found in the result's title and tags (0–1)."""
    wanted = words(query)
    if not wanted:
        return 0.0
    tags = " ".join(str(t.get("name", "")) for t in result.get("tags") or [] if isinstance(t, dict))
    genres = " ".join(map(str, result.get("genres") or []))
    have = words(f"{result.get('title', '')} {tags} {genres}")
    # a word counts when the result has it or a longer form of it ("train" in "trains")
    return sum(1 for w in wanted if any(h.startswith(w) for h in have)) / len(wanted)


def credit(result: dict[str, Any], what: str) -> str:
    licence = licence_name(result)
    title = str(result.get("title") or "untitled")[:60]
    return (f"{what} \"{title}\" by {result.get('creator') or 'unknown'} via Openverse/{result.get('provider', '?')}, "
            f"{licence} ({result.get('foreign_landing_url', '')})")


def licence_name(result: dict[str, Any]) -> str:
    """"CC BY 3.0" for an attribution licence (with its version), else the public-domain names."""
    code = str(result["license"]).lower()
    version = str(result.get("license_version") or "")
    return f"{LICENCE_NAMES[code]} {version}".strip() if code == "by" else LICENCE_NAMES[code]
