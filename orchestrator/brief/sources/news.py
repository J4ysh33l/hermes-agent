"""News: Google News RSS searches, publisher RSS/Atom feeds and Hacker News, per topic. No keys."""

from __future__ import annotations

import hashlib
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime

from ..items import Item, SourceError
from ..net import Http, HttpError
from ..settings import Topic

GOOGLE_NEWS = "https://news.google.com/rss/search"
HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
HN_SCAN = 60
HN_MIN_SCORE = 80
TAG = re.compile(r"<[^>]+>")
ATOM = "{http://www.w3.org/2005/Atom}"


def _clean(text: str, limit: int = 240) -> str:
    return " ".join(html.unescape(TAG.sub(" ", text or "")).split())[:limit]


def _uid(link: str, title: str) -> str:
    return "news:" + hashlib.sha1((link or title).encode()).hexdigest()[:16]


def _ts(value: str) -> float:
    if not value:
        return 0.0
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def parse_feed(xml_text: str, publication: str = "") -> list[Item]:
    """RSS 2.0 or Atom → items (topic not set). Broken XML raises SourceError."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceError(f"bad feed XML: {exc}") from None
    channel_title = _clean(root.findtext("channel/title") or root.findtext(f"{ATOM}title") or "", 60)
    where = publication or channel_title
    items = [_rss_item(node, where) for node in root.iter("item")]
    items += [_atom_item(node, where) for node in root.iter(f"{ATOM}entry")]
    return [i for i in items if i.title]


def _rss_item(node: ET.Element, where: str) -> Item:
    title = _clean(node.findtext("title") or "", 200)
    link = (node.findtext("link") or "").strip()
    source = node.find("source")  # Google News names the publisher here
    pub = _clean(source.text or "", 60) if source is not None and source.text else where
    if source is not None and title.endswith(f" - {pub}"):
        title = title[: -len(pub) - 3]
    return Item(uid=_uid(link, title), source="news", title=title, url=link, where=pub,
                ts=_ts(node.findtext("pubDate") or ""), snippet=_clean(node.findtext("description") or ""))


def _atom_item(node: ET.Element, where: str) -> Item:
    title = _clean(node.findtext(f"{ATOM}title") or "", 200)
    link_node = node.find(f"{ATOM}link")
    link = link_node.get("href", "") if link_node is not None else ""
    stamp = node.findtext(f"{ATOM}updated") or node.findtext(f"{ATOM}published") or ""
    summary = node.findtext(f"{ATOM}summary") or node.findtext(f"{ATOM}content") or ""
    return Item(uid=_uid(link, title), source="news", title=title, url=link, where=where,
                ts=_ts(stamp), snippet=_clean(summary))


def _site(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc.removeprefix("www.").removeprefix("feeds.")


def google_news_url(query: str) -> str:
    params = {"q": f"{query} when:1d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
    return GOOGLE_NEWS + "?" + urllib.parse.urlencode(params)


def _hacker_news(http: Http, topic: Topic, since: float) -> list[Item]:
    ids = http.request("GET", HN_TOP).json()[:HN_SCAN]
    found = []
    for story_id in ids:
        story = http.request("GET", HN_ITEM.format(id=story_id)).json() or {}
        title = story.get("title", "")
        words = set(re.findall(r"[a-z0-9]+", title.lower()))
        if story.get("score", 0) < HN_MIN_SCORE or story.get("time", 0) < since:
            continue
        if topic.keywords and not words & set(topic.keywords):
            continue
        url = story.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
        found.append(Item(uid=f"hn:{story_id}", source="news", title=title, url=url, where="Hacker News",
                          ts=float(story.get("time", 0)), snippet=f"{story.get('score', 0)} points"))
    return found


def fetch_topic(http: Http, topic: Topic, since: float) -> tuple[list[Item], list[str]]:
    """All items for one topic newer than ``since``, newest first, plus per-feed errors."""
    items: list[Item] = []
    errors: list[str] = []
    urls = [(google_news_url(q), "") for q in topic.queries] + [(f, _site(f)) for f in topic.feeds]
    for url, pub in urls:
        try:
            items += parse_feed(http.request("GET", url).text(), pub)
        except (HttpError, SourceError) as exc:
            errors.append(f"{topic.name}: {urllib.parse.urlsplit(url).netloc} ({exc})")
    if topic.hacker_news:
        try:
            items += _hacker_news(http, topic, since)
        except (HttpError, ValueError) as exc:
            errors.append(f"{topic.name}: Hacker News ({exc})")
    fresh = {i.uid: i.with_topic(topic.name) for i in items if i.ts == 0 or i.ts >= since}
    newest = sorted(fresh.values(), key=lambda i: i.ts, reverse=True)
    return _dedupe_titles(newest), errors


def _dedupe_titles(items: list[Item]) -> list[Item]:
    """The same story arrives from several feeds and queries; keep its first (newest) copy."""
    seen: set[str] = set()
    out = []
    for item in items:
        key = " ".join(re.findall(r"[a-z0-9]+", item.title.lower())[:8])
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out
