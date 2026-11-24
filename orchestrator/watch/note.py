"""Gemini's note on a change: which new items matter to you and why. One call per change, in the
same message as the script's list (no waiting). Up to ``PAGES`` of the new items' pages are read by
the script first, so the note can say what the page says (location, seniority, deadline), never a
guess. Everything sent is public page text plus your ``watch.about`` line and the watch's "what".
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from orchestrator import llm
from orchestrator.brief.net import Http, HttpError
from orchestrator.brief.settings import ModelChoice

from .sources import Item

MODELS = (ModelChoice("gemini-3.1-flash-lite"), ModelChoice("gemini-3.5-flash-lite"), ModelChoice("gemma-4-31b-it"))
PAGES = 5  # new items whose pages are opened for the note
PAGE_CHARS = 1500  # of each page's text
PROMPT = """New items appeared on a page I watch. Write a note for Telegram, read on a phone.
Rules: plain text, no Markdown tables, at most 10 lines. First the items that match what I care about,
one line each: the title, why it matters to me, then facts from its page text below that help me decide
(location or remote, seniority, team, deadline, pay if stated). Then one line for the rest, e.g.
"Not relevant: 6 others (sales, US-only)". If none matter, say so in one line and why. Use only the text
below; write "page not read" when an item has no page text. Never invent a fact.

What I care about on this page: {what}
About me: {about}
Page: {url}

New items:
{items}"""


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, _attrs):
        self.skip += tag in self.SKIP

    def handle_endtag(self, tag):
        self.skip -= tag in self.SKIP and self.skip > 0

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def page_text(http: Http, url: str) -> str:
    try:
        html = http.request("GET", url).text()
    except (HttpError, OSError):
        return ""
    parser = _Text()
    parser.feed(html)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()[:PAGE_CHARS]


def write(http: Http, key: str, w: dict, new: list[Item], about: str) -> str:
    """The note, or a line saying why there is none (the change itself is already in the message)."""
    if not key:
        return "(No Gemini note: GEMINI_API_KEY is not set.)"
    rows = []
    for n, item in enumerate(new[:30]):
        text = page_text(http, item.link) if n < PAGES and item.link.startswith("http") else ""
        rows.append(f"- {item.title} — {item.link}\n  Page text: {text or 'page not read'}")
    prompt = PROMPT.format(what=w["what"] or "anything new", about=about or "(not given)", url=w["url"],
                           items="\n".join(rows))
    errors = []
    for model in MODELS:
        try:
            text = llm.gemini(http, key, model.id, prompt, workflow="watch", step="note", max_output_tokens=600,
                              temperature=0.2).strip()
        except (HttpError, ValueError) as exc:
            errors.append(f"{model.id}: {str(exc)[:80]}")
            continue
        if text:
            return text
        errors.append(f"{model.id}: empty answer")
    return "(No Gemini note: " + "; ".join(errors) + ")"
