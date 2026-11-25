"""Reading a watched page into items (title + link). No model.

A watch's ``spec`` says how to read it:

- ``{"kind": "json", "url", "items", "title", "link" | "link_template"}``: a JSON feed. ``items`` is
  the dot path to the list ("" = the whole answer is the list), ``title`` and ``link`` are field
  names, ``link_template`` builds the link from fields (``https://x/{id}``).
- ``{"kind": "feed", "url"}``: RSS or Atom.
- ``{"kind": "html", "url"}``: every link on the page (text + address). A page that answers with
  RSS/Atom is read as a feed.

Any spec may add ``match`` (a regular expression; only items whose title or link match are kept).

``detect`` turns a careers-page address into its job board's public JSON feed when it knows the board
(Greenhouse, Lever, Ashby, SmartRecruiters, Workable), which is cleaner and steadier than the page.
Anything else starts as ``html``; Claude can later replace the spec with a better one.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

from orchestrator.brief.net import Http, HttpError

KINDS = ("json", "feed", "html")
MAX_ITEMS = 2000  # a big company board has hundreds of roles
BOARDS = (  # (host pattern, feed url, items path, title field, link field or template)
    (r"(?:job-)?boards\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)",
     "https://boards-api.greenhouse.io/v1/boards/{co}/jobs", "jobs", "title", "absolute_url"),
    (r"jobs\.lever\.co/([\w-]+)", "https://api.lever.co/v0/postings/{co}?mode=json", "", "text", "hostedUrl"),
    (r"jobs\.ashbyhq\.com/([\w.-]+)", "https://api.ashbyhq.com/posting-api/job-board/{co}", "jobs", "title",
     "jobUrl"),
    (r"(?:careers|jobs)\.smartrecruiters\.com/([\w-]+)", "https://api.smartrecruiters.com/v1/companies/{co}/postings",
     "content", "name", "https://jobs.smartrecruiters.com/{co}/{id}"),
    (r"apply\.workable\.com/([\w-]+)", "https://apply.workable.com/api/v1/widget/accounts/{co}", "jobs", "title",
     "url"),
)


class SourceError(Exception):
    """The page could not be read this time; the watch keeps its last items."""


@dataclass(frozen=True)
class Item:
    key: str  # the link (or the title when there is none): what makes an item new
    title: str
    link: str


def detect(url: str) -> dict:
    for pattern, feed, items, title, link in BOARDS:
        if m := re.search(pattern, url):
            co = m.group(1)
            spec = {"kind": "json", "url": feed.format(co=co), "items": items, "title": title, "page": url}
            spec["link_template" if "{" in link else "link"] = link.replace("{co}", co)
            return spec
    if re.search(r"(\.xml|\.rss|/rss|/feed|/atom)(/|\?|$)", url, re.IGNORECASE):
        return {"kind": "feed", "url": url}
    return {"kind": "html", "url": url}


def check_spec(spec: object) -> list[str]:
    """Problems with a spec (from Claude or brief.yaml); [] when it can be used."""
    if not isinstance(spec, dict):
        return ["the spec is not a JSON object"]
    problems = []
    if spec.get("kind") not in KINDS:
        problems.append(f"kind must be one of {', '.join(KINDS)}")
    if not re.match(r"https?://", str(spec.get("url", ""))):
        problems.append("url must start with http:// or https://")
    if spec.get("kind") == "json" and not spec.get("title"):
        problems.append("a json spec needs title (and link or link_template)")
    if spec.get("match"):
        try:
            re.compile(spec["match"])
        except re.error as exc:
            problems.append(f"match is not a valid pattern: {exc}")
    return problems


# ---- readers --------------------------------------------------------------------------------------


def _path(data, dotted: str):
    for part in [p for p in dotted.split(".") if p]:
        data = data.get(part) if isinstance(data, dict) else None
    return data


def _json_items(text: str, spec: dict) -> list[Item]:
    rows = _path(json.loads(text), spec.get("items", ""))
    if not isinstance(rows, list):
        raise SourceError(f"no list at {spec.get('items') or 'the top'} of the answer")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = " ".join(str(_path(row, spec["title"]) or "").split())
        flat = {k: v for k, v in row.items() if isinstance(v, (str, int, float))}
        link = spec["link_template"].format_map(_Blank(flat)) if spec.get("link_template") \
            else str(_path(row, spec.get("link", "")) or "")
        if title:
            out.append(Item(link or title, title, link))
    return out


class _Blank(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _feed_items(text: str) -> list[Item]:
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:
        raise SourceError(f"not a valid feed: {exc}") from None
    out = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        title = link = ""
        for child in node:
            name = child.tag.rsplit("}", 1)[-1]
            if name == "title":
                title = " ".join((child.text or "").split())
            elif name == "link":
                link = (child.text or "").strip() or child.get("href", "")
        if title or link:
            out.append(Item(link or title, title or link, link))
    return out


class _Links(HTMLParser):
    SKIP = ("script", "style", "noscript")

    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base, self.links, self.href, self.text, self.skip = base, [], None, [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "a":
            self.href, self.text = dict(attrs).get("href"), []
        elif tag == "img" and self.href is not None:
            self.text.append(dict(attrs).get("alt") or "")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "a" and self.href is not None:
            self.links.append((self.href, " ".join(" ".join(self.text).split())))
            self.href = None

    def handle_data(self, data):
        if self.href is not None and not self.skip:
            self.text.append(data)


def _html_items(text: str, url: str) -> list[Item]:
    parser = _Links(url)
    parser.feed(text)
    page = urldefrag(url)[0]
    out = []
    for href, title in parser.links:
        href = (href or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        link = urldefrag(urljoin(url, href))[0]
        if link == page or urlsplit(link).scheme not in ("http", "https"):
            continue
        out.append(Item(link, title or link.rsplit("/", 1)[-1] or link, link))
    return out


def _looks_like_feed(text: str) -> bool:
    head = text.lstrip()[:400].lower()
    return (head.startswith("<?xml") and ("<rss" in head or "<feed" in head)) or head.startswith(("<rss", "<feed"))


def read(http: Http, spec: dict) -> list[Item]:
    """The items now, de-duplicated by key, filtered by ``match``. Raises SourceError."""
    try:
        text = http.request("GET", spec["url"], headers={"Accept": "*/*"}).text()
    except HttpError as exc:
        raise SourceError(f"HTTP {exc.status}" if exc.status else f"network error ({exc.detail[:100]})") from None
    except OSError as exc:
        raise SourceError(str(exc)[:120]) from None
    try:
        if spec["kind"] == "json":
            items = _json_items(text, spec)
        elif spec["kind"] == "feed" or _looks_like_feed(text):
            items = _feed_items(text)
        else:
            items = _html_items(text, spec["url"])
    except ValueError as exc:  # bad JSON
        raise SourceError(f"could not read the answer: {str(exc)[:120]}") from None
    if spec.get("match"):
        keep = re.compile(spec["match"], re.IGNORECASE)
        items = [i for i in items if keep.search(i.title) or keep.search(i.link)]
    unique = {}
    for item in items:
        unique.setdefault(item.key, item)
    return list(unique.values())[:MAX_ITEMS]
