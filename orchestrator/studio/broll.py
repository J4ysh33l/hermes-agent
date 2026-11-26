"""Stock b-roll for image scenes: ``"src": "stock:<what the footage shows>"`` is searched, downloaded once
into ``$HERMES_HOME/studio/broll/`` and credited in the job's notes, which travel with the preview.

Sources, in order: Pexels and Pixabay clips and photos when their keys are in ``$HERMES_HOME/.env``
(``PEXELS_API_KEY``, ``PIXABAY_API_KEY``), then Openverse (openverse.py): CC0 and public-domain photos, no
key needed, kept only when they carry most of the search's words and are big enough for a 1080×1920 frame.
With ``elements.broll: off``, or when nothing fits, the scene is drawn as a title card with its caption (or
the search words), and the notes say why: a video never fails over b-roll.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from itertools import islice
from pathlib import Path
from types import MappingProxyType
from typing import Any

from orchestrator.brief.net import Http, HttpError

from . import openverse
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


def pexels_video(http: Http, key: str, query: str) -> list[Found]:
    found = http.request("GET", "https://api.pexels.com/videos/search", headers={"Authorization": key},
                         params={"query": query, "orientation": "portrait", "per_page": 15}).json()
    out = []
    for video in found.get("videos") or []:
        best = _portrait(video.get("video_files") or [])
        if best and (video.get("duration") or 0) >= MIN_SECONDS and best.get("link"):
            out.append(Found(best["link"], ".mp4", f"Video by {video['user']['name']} on Pexels ({video['url']})"))
    return out


def pexels_photo(http: Http, key: str, query: str) -> list[Found]:
    found = http.request("GET", "https://api.pexels.com/v1/search", headers={"Authorization": key},
                         params={"query": query, "orientation": "portrait", "per_page": 15}).json()
    return [Found(photo["src"]["portrait"], ".jpg", f"Photo by {photo['photographer']} on Pexels ({photo['url']})")
            for photo in found.get("photos") or []
            if (photo.get("height") or 0) >= MIN_HEIGHT and (photo.get("src") or {}).get("portrait")]


def pixabay_video(http: Http, key: str, query: str) -> list[Found]:
    found = http.request("GET", "https://pixabay.com/api/videos/", params={
        "key": key, "q": query, "safesearch": "true", "per_page": 20}).json()
    out = []
    for hit in found.get("hits") or []:
        best = _portrait(list((hit.get("videos") or {}).values()))
        if best and (hit.get("duration") or 0) >= MIN_SECONDS and best.get("url"):
            out.append(Found(best["url"], ".mp4", f"Video by {hit.get('user', '?')} on Pixabay ({hit.get('pageURL', '')})"))
    return out


def pixabay_photo(http: Http, key: str, query: str) -> list[Found]:
    found = http.request("GET", "https://pixabay.com/api/", params={
        "key": key, "q": query, "orientation": "vertical", "image_type": "photo", "safesearch": "true",
        "per_page": 20}).json()
    return [Found(hit["largeImageURL"], ".jpg", f"Photo by {hit.get('user', '?')} on Pixabay ({hit.get('pageURL', '')})")
            for hit in found.get("hits") or [] if (hit.get("imageHeight") or 0) >= MIN_HEIGHT and hit.get("largeImageURL")]


MATCH = 0.6  # an Openverse photo must carry this share of the search's words
MIN_SIDE = 1080  # and be at least this tall (a landscape photo is cropped to the middle of the frame)
MIN_TALL = 1000  # a portrait one may be a little shorter: Openverse serves Flickr photos at 1024 px at most


def _big_enough(result: dict) -> bool:
    height, width = result.get("height") or 0, result.get("width") or 0
    return height >= MIN_SIDE or (height > width and height >= MIN_TALL)


def openverse_photo(http: Http, _key: str, query: str) -> list[Found]:
    """CC0/public-domain photos that carry the words: best match first, then tall ones, then the biggest."""
    found = [r for r in openverse.search(http, "images", query)
             if _big_enough(r) and openverse.relevance(r, query) >= MATCH]
    found.sort(key=lambda r: (openverse.relevance(r, query), (r.get("height") or 0) > (r.get("width") or 0),
                              r.get("height") or 0), reverse=True)
    return [Found(r["url"], ".png" if str(r.get("filetype", "")).lower() == "png" else ".jpg",
                  openverse.credit(r, "Photo")) for r in found]


# Tried in order: moving footage first, Pexels before Pixabay, then Openverse. Each entry: (which key — "" =
# none needed, search returning its fitting results, best first).
SOURCES: tuple[tuple[str, Callable[[Http, str, str], list[Found]]], ...] = (
    ("pexels", pexels_video), ("pixabay", pixabay_video), ("pexels", pexels_photo), ("pixabay", pixabay_photo),
    ("", openverse_photo))
TRIES = 4  # downloads tried before the scene becomes a title card (a host may refuse one: rate limits)


def candidates(http: Http, keys: Keys, query: str) -> Iterator[Found]:
    """Every fitting result, source by source, best first."""
    for which, find in SOURCES:
        key = getattr(keys, which) if which else "-"
        if not key:
            continue
        try:
            yield from find(http, key, query)
        except (HttpError, ValueError, KeyError, TypeError):  # one source down or odd: try the next
            continue


def _download(http: Http, keys: Keys, query: str) -> tuple[Found, bytes] | None:
    for found in islice(candidates(http, keys, query), TRIES):
        try:
            return found, http.request("GET", found.url).body
        except HttpError:  # this host refused (Wikimedia rate-limits busy addresses): try the next result
            continue
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
    got = _download(http, keys, query)
    if not got:
        return None
    found, body = got
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stem}{found.ext}"
    path.write_bytes(body)
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
        why = "b-roll is off for this page" if use == "off" else ""
        got = None if why else fetch(http, keys, home, query)
        if got:
            scenes[n] = replace(scene, fields=MappingProxyType({**scene.fields, "src": str(got[0])}))
            notes.append(f"scene {n + 1} b-roll: {got[1]}")
        else:
            scenes[n] = _title(scene, query)
            why = why or openverse.blocked() or "nothing fitting found, or its host refused the download"
            notes.append(f"scene {n + 1}: no b-roll for {query!r} ({why}); drawn as a title card")
    return replace(board, scenes=tuple(scenes)), tuple(notes)
