"""Index levels, yields, FX and gold from Yahoo Finance's public chart endpoint. No model, no key.

Yahoo's endpoint is unofficial and may throttle server IPs; one run a day is far below any limit
seen in practice, and a failure only removes this block from the brief.
"""

from __future__ import annotations

import time
import urllib.parse

from ..items import Markets, Quote
from ..net import Http, HttpError
from ..settings import Settings, Symbol

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
GRAMS_PER_TROY_OUNCE = 31.1034768


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
    return Markets(quotes=tuple(quotes), gold_inr_10g=gold_inr, errors=tuple(errors))
