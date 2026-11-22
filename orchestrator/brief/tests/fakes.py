"""Fake HTTP for the brief: every outside service the brief talks to, answered from memory."""

from __future__ import annotations

import json
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from orchestrator.brief.net import HttpError, Response, build_url

NOW = time.time()


def rss(items: list[tuple[str, str, float]], source: str = "") -> str:
    """(title, link, unix time) → an RSS 2.0 document; ``source`` mimics Google News."""
    rows = []
    for title, link, ts in items:
        pub = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(ts))
        src = f"<source url='https://x'>{source}</source>" if source else ""
        shown = f"{title} - {source}" if source else title
        rows.append(f"<item><title>{shown}</title><link>{link}</link><pubDate>{pub}</pubDate>"
                    f"<description>About {title}</description>{src}</item>")
    return f"<?xml version='1.0'?><rss><channel><title>Feed</title>{''.join(rows)}</channel></rss>"


def chart(price: float, prev: float, tz_offset: int = -18000, as_of: float = NOW - 20000) -> dict:
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price, "regularMarketTime": as_of,
                                           "gmtoffset": tz_offset},
                                  "indicators": {"quote": [{"close": [prev - 1, prev, price]}]}}], "error": None}}


def gemini_answer(ids: list[str]) -> dict:
    top = [{"id": i, "line": f"Summary of {i}"} for i in ids]
    return {"candidates": [{"content": {"parts": [{"text": json.dumps({"top": top})}]}}],
            "usageMetadata": {"promptTokenCount": 1500, "candidatesTokenCount": 120, "totalTokenCount": 1620}}


@dataclass
class Call:
    method: str
    url: str
    headers: dict[str, str]
    form: dict[str, str] | None
    json_body: Any


Handler = Callable[[Call], Any]


@dataclass
class FakeHttp:
    """Routes match on 'METHOD url-prefix'. A handler returns a dict/list (JSON), a str (text),
    or raises HttpError. Unmatched requests fail loudly."""

    routes: dict[str, Handler] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list)

    def on(self, method: str, prefix: str, handler: Handler | Any) -> FakeHttp:
        self.routes[f"{method} {prefix}"] = handler if callable(handler) else (lambda _c, v=handler: v)
        return self

    def request(self, method, url, *, params=None, headers=None, form=None, json_body=None) -> Response:
        full = build_url(url, params)
        call = Call(method, full, headers or {}, form, json_body)
        self.calls.append(call)
        matches = [k for k in self.routes if f"{method} {full}".startswith(k)]
        if not matches:
            raise AssertionError(f"unexpected request: {method} {full}")
        value = self.routes[max(matches, key=len)](call)
        body = value.encode() if isinstance(value, str) else json.dumps(value).encode()
        return Response(200, body)

    def count(self, prefix: str) -> int:
        return sum(1 for c in self.calls if c.url.startswith(prefix))


def http_error(status: int, detail: str = "") -> Callable[[Call], Any]:
    def fail(call: Call) -> Any:
        raise HttpError(status, call.url, detail)
    return fail


def query(call: Call) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(urllib.parse.urlsplit(call.url).query)
