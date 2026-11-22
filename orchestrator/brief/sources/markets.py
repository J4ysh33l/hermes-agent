"""Index levels, yields, FX and gold from Yahoo Finance's public chart endpoint. No model, no key.

Yahoo's endpoint is unofficial and may throttle server IPs; one run a day is far below any limit
seen in practice, and a failure only removes this block from the brief.
"""

from __future__ import annotations

import time
import urllib.parse

import html
import json
import re

from ..items import IndiaGold, Markets, Quote
from ..net import Http, HttpError
from ..settings import Settings, Symbol

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
GRAMS_PER_TROY_OUNCE = 31.1034768
IBJA = "https://ibjarates.com/"
IBJA_HISTORY = re.compile(r'id="HdnGold"\s+value="([^"]*)"')
IBJA_TODAY = re.compile(r'id="GoldRatesCompare999"[^>]*>\s*([0-9.,]+)')


def india_gold(http: Http) -> IndiaGold:
    """Latest IBJA 999 rate. The page carries a daily history (₹/10 g) in a hidden field; the
    headline 1-gram figure is the fallback. IBJA publishes no rates on weekends and holidays,
    so the date shown is the last trading day."""
    page = http.request("GET", IBJA).text()
    match = IBJA_HISTORY.search(page)
    if match:
        history = json.loads(html.unescape(match.group(1)))
        dates, prices = history.get("labels") or [], history.get("purity999") or []
        if dates and prices:
            prev = prices[-2] if len(prices) >= 2 else None
            change = (prices[-1] - prev) / prev * 100 if prev else None
            return IndiaGold(float(prices[-1]), str(dates[-1]), change)
    today = IBJA_TODAY.search(page)
    if not today:
        raise ValueError("IBJA page changed: no 999 rate found")
    return IndiaGold(float(today.group(1).replace(",", "")) * 10, "today")


def quote(http: Http, sym: Symbol) -> Quote:
    url = CHART.format(symbol=urllib.parse.quote(sym.symbol, safe=""))
    data = http.request("GET", url, params={"range": "5d", "interval": "1d"}).json()
    result = (data.get("chart") or {}).get("result") or []
    if not result:
        err = ((data.get("chart") or {}).get("error") or {}).get("description", "no data")
        raise ValueError(f"{sym.symbol}: {err}")
    meta = result[0].get("meta") or {}
    closes = [c for c in ((result[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or [] if c]
    price = meta.get("regularMarketPrice") or (closes[-1] if closes else None)
    if price is None:
        raise ValueError(f"{sym.symbol}: no price")
    prev = closes[-2] if len(closes) >= 2 else meta.get("chartPreviousClose")
    change = (price - prev) / prev * 100 if prev else None
    as_of = float(meta.get("regularMarketTime") or 0)
    day = time.strftime("%a", time.gmtime(as_of + float(meta.get("gmtoffset") or 0))) if as_of else ""
    return Quote(symbol=sym.symbol, label=sym.label, price=float(price), change_pct=change,
                 as_of=as_of, unit=sym.unit, group=sym.group, day=day)


def fetch(http: Http, settings: Settings) -> Markets:
    quotes: list[Quote] = []
    errors: list[str] = []
    wanted = list(settings.all_symbols())
    extra = [Symbol(settings.gold_symbol, "Gold", "$/oz", group="Gold")]
    if settings.fx_symbol not in {s.symbol for s in wanted}:
        extra.append(Symbol(settings.fx_symbol, "USD/INR"))
    by_symbol: dict[str, Quote] = {}
    for sym in wanted + extra:
        try:
            by_symbol[sym.symbol] = quote(http, sym)
        except (HttpError, ValueError, KeyError, IndexError) as exc:
            errors.append(str(exc) if isinstance(exc, ValueError) else f"{sym.symbol}: {exc}")
    quotes = [by_symbol[s.symbol] for s in wanted if s.symbol in by_symbol]
    gold, fx = by_symbol.get(settings.gold_symbol), by_symbol.get(settings.fx_symbol)
    gold_inr = gold.price * fx.price / GRAMS_PER_TROY_OUNCE * 10 if gold and fx else None
    if gold and settings.show_gold_usd:
        quotes.append(gold)
    india = None
    if settings.india_gold:
        try:
            india = india_gold(http)
        except (HttpError, ValueError, KeyError) as exc:
            errors.append(f"IBJA gold: {exc}")
    return Markets(quotes=tuple(quotes), gold_inr_10g=gold_inr, india_gold=india, errors=tuple(errors))
