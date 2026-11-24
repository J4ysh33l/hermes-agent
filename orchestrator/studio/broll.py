"""Stock b-roll for image scenes: ``"src": "stock:<what the footage shows>"`` is searched on Pexels, then
Pixabay (portrait clips first, then photos), downloaded once into ``$HERMES_HOME/studio/broll/`` and
credited in the job's notes ("Video by … on Pexels (link)"), which travel with the preview.

Keys in ``$HERMES_HOME/.env``: ``PEXELS_API_KEY`` and/or ``PIXABAY_API_KEY`` (both free). Without a key,
with ``elements.broll: off``, or when nothing is found, the scene is drawn as a title card with its
caption (or the search words), and the notes say why: a video never fails over b-roll.

Both licences allow use in videos without attribution; we credit anyway (Pexels asks for it where possible).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from orchestrator.brief.net import Http, HttpError

from .profile import Profile
from .settings import Keys
from .storyboard import STOCK, Storyboard

MIN_HEIGHT = 1280  # a portrait clip or photo at least this tall (the video is 1920; the Ken Burns push hides a little)
MIN_SECONDS = 3


@dataclass(frozen=True)
class Found:
    url: str
    ext: str  # .mp4 or .jpg
    credit: str


def _portrait(files: list[dict], width: str = "width", height: str = "height") -> dict | None:
    """The smallest file that is portrait and tall enough (smaller = faster to fetch and render)."""
    fits = [f for f in files if (f.get(height) or 0) >= MIN_HEIGHT and (f.get(width) or 0) < (f.get(height) or 0)]
    return min(fits, key=lambda f: f[height]) if fits else None


def pexels_video(http: Http, key: str, query: str) -> Found | None:
    found = http.request("GET", "https://api.pexels.com/videos/search", headers={"Authorization": key},
                         params={"query": query, "orientation": "portrait", "per_page": 15}).json()
    for video in found.get("videos") or []:
        best = _portrait(video.get("video_files") or [])
        if best and (video.get("duration") or 0) >= MIN_SECONDS and best.get("link"):
            return Found(best["link"], ".mp4", f"Video by {video['user']['name']} on Pexels ({video['url']})")
    return None


def pexels_photo(http: Http, key: str, query: str) -> Found | None:
    found = http.request("GET", "https://api.pexels.com/v1/search", headers={"Authorization": key},
                         params={"query": query, "orientation": "portrait", "per_page": 15}).json()
    for photo in found.get("photos") or []:
        if (photo.get("height") or 0) >= MIN_HEIGHT and (photo.get("src") or {}).get("portrait"):
            return Found(photo["src"]["portrait"], ".jpg", f"Photo by {photo['photographer']} on Pexels ({photo['url']})")
    return None


def pixabay_video(http: Http, key: str, query: str) -> Found | None:
    found = http.request("GET", "https://pixabay.com/api/videos/", params={
        "key": key, "q": query, "safesearch": "true", "per_page": 20}).json()
    for hit in found.get("hits") or []:
        best = _portrait(list((hit.get("videos") or {}).values()))
        if best and (hit.get("duration") or 0) >= MIN_SECONDS and best.get("url"):
            return Found(best["url"], ".mp4", f"Video by {hit.get('user', '?')} on Pixabay ({hit.get('pageURL', '')})")
    return None


def pixabay_photo(http: Http, key: str, query: str) -> Found | None:
    found = http.request("GET", "https://pixabay.com/api/", params={
        "key": key, "q": query, "orientation": "vertical", "image_type": "photo", "safesearch": "true",
        "per_page": 20}).json()
    for hit in found.get("hits") or []:
        if (hit.get("imageHeight") or 0) >= MIN_HEIGHT and hit.get("largeImageURL"):
            return Found(hit["largeImageURL"], ".jpg", f"Photo by {hit.get('user', '?')} on Pixabay ({hit.get('pageURL', '')})")
    return None


# Tried in order: moving footage first, Pexels before Pixabay. Each entry: (which key, search).
SOURCES: tuple[tuple[str, Callable[[Http, str, str], Found | None]], ...] = (
    ("pexels", pexels_video), ("pixabay", pixabay_video), ("pexels", pexels_photo), ("pixabay", pixabay_photo))


def available(keys: Keys) -> bool:
    return bool(keys.pexels or keys.pixabay)


def search(http: Http, keys: Keys, query: str) -> Found | None:
    for which, find in SOURCES:
        key = getattr(keys, which)
        if not key:
            continue
        try:
            found = find(http, key, query)
        except (HttpError, ValueError, KeyError, TypeError):  # one source down or odd: try the next
            continue
        if found:
            return found
    return None


def fetch(http: Http, keys: Keys, home: Path, query: str) -> tuple[Path, str] | None:
    """The cached file and its credit for ``query`` (searched and downloaded the first time)."""
    folder = home / "studio" / "broll"
    stem = hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]
    meta = folder / f"{stem}.json"
    if meta.is_file():
        saved = json.loads(meta.read_text(encoding="utf-8"))
        if (folder / saved["file"]).is_file():
            return folder / saved["file"], saved["credit"]
    found = search(http, keys, query)
    if not found:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stem}{found.ext}"
    path.write_bytes(http.request("GET", found.url).body)
    meta.write_text(json.dumps({"file": path.name, "credit": found.credit, "query": query}), encoding="utf-8")
    return path, found.credit


def _title(scene: Any, query: str) -> Any:
    text = scene.fields.get("caption") or query[:1].upper() + query[1:]
    return replace(scene, type="title", fields=MappingProxyType({"text": text, "kicker": ""}))


def resolve(http: Http, keys: Keys, home: Path, board: Storyboard, look: Profile) -> tuple[Storyboard, tuple[str, ...]]:
    """Every ``stock:`` image found and downloaded (its scene's src now the file), or drawn as a title card;
    one note per such scene."""
    scenes, notes = list(board.scenes), []
    use = look.section("elements")["broll"]
    for n, scene in enumerate(scenes):
        src = str(scene.fields.get("src", "")) if scene.type == "image" else ""
        if not src.startswith(STOCK):
            continue
        query = src[len(STOCK):].strip()
        why = "b-roll is off for this page" if use == "off" else "" if available(keys) else \
            "no PEXELS_API_KEY or PIXABAY_API_KEY"
        got = None if why else fetch(http, keys, home, query)
        if got:
            scenes[n] = replace(scene, fields=MappingProxyType({**scene.fields, "src": str(got[0])}))
            notes.append(f"scene {n + 1} b-roll: {got[1]}")
        else:
            scenes[n] = _title(scene, query)
            notes.append(f"scene {n + 1}: no b-roll for {query!r} ({why or 'nothing found'}); drawn as a title card")
    return replace(board, scenes=tuple(scenes)), tuple(notes)
