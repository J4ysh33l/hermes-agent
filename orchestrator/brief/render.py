"""Telegram text in standard markdown (Hermes converts it to Telegram's format on delivery)."""

from __future__ import annotations

import re
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

from .items import Item, Markets, Quote, SourceResult

ICONS = {"slack": "💬", "gmail": "✉️", "outlook": "✉️", "news": "📰"}
SOURCE_LABELS = {"slack": "Slack", "gmail": "Gmail", "outlook": "Outlook", "news": "News", "markets": "Markets"}
PRIVATE_SHOWN = 8


def source_label(name: str) -> str:
    """'gmail:work' → 'Gmail (work)'."""
    base, _, account = name.partition(":")
    label = SOURCE_LABELS.get(base, base)
    return f"{label} ({account})" if account else label
MARKDOWN_SPECIALS = re.compile(r"[*_`\[\]]")
MORE_LIMIT = 80
LONG_URL = 200


def plain(text: str) -> str:
    """Titles come from outside; strip characters that would break the markdown."""
    return MARKDOWN_SPECIALS.sub("", text or "").strip()


def indian_grouping(value: float) -> str:
    """1047381.2 -> '10,47,381' (lakh/crore grouping)."""
    whole = str(round(value))
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    pairs = [head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1]
    return ",".join(pairs) + "," + tail


def _arrow(pct: float | None) -> str:
    if pct is None:
        return ""
    return f" {'▲' if pct >= 0 else '▼'}{abs(pct):.2f}%"


def _price(q: Quote) -> str:
    if q.unit == "%":
        return f"{q.price:.2f}%"
    if q.unit == "$/oz":
        return f"${q.price:,.0f}/oz"
    return f"{q.price:,.2f}" if q.price < 1000 else f"{q.price:,.0f}"


def markets_block(m: Markets, tz: ZoneInfo) -> list[str]:
    groups: dict[str, list[Quote]] = {}
    for q in m.quotes:
        groups.setdefault(q.group or "Other", []).append(q)
    lines = ["**Markets** (last close)"]
    for group, quotes in groups.items():
        day = quotes[0].day or datetime.fromtimestamp(quotes[0].as_of, tz).strftime("%a")
        cells = " · ".join(
            f"{'' if q.label == group else plain(q.label) + ' '}{_price(q)}{_arrow(q.change_pct)}" for q in quotes)
        if group == "Gold" and m.gold_inr_10g:
            cells += f" · ₹{indian_grouping(m.gold_inr_10g)}/10g"
        lines.append(f"{group} ({day}): {cells}" if group not in ("Gold", "Rates and FX") else f"{group}: {cells}")
    if m.gold_inr_10g and "Gold" not in groups:
        lines.append(f"Gold: ₹{indian_grouping(m.gold_inr_10g)}/10g")
    if m.india_gold:
        g = m.india_gold
        lines.append(f"Gold India*: ₹{indian_grouping(g.price_10g)}/10g{_arrow(g.change_pct)} ({_short_date(g.date)})")
    notes = []
    if m.india_gold:
        notes.append("*India rate: IBJA 24K (999), excl. GST.")
    if m.gold_inr_10g:
        notes.append("₹ beside $ is the world price converted, before duty and GST.")
    if notes:
        lines.append("_" + " ".join(notes) + "_")
    return lines


def _short_date(published: str) -> str:
    """IBJA writes dd/mm/yyyy; show '20 Nov'."""
    try:
        return datetime.strptime(published, "%d/%m/%Y").strftime("%d %b")
    except ValueError:
        return published


def short_url(item_url: str, title: str) -> str:
    """Google News article links run to 600+ characters; a headline search is ~150 and opens
    the same story. Telegram counts link length against its 4096-character message limit."""
    if len(item_url) <= LONG_URL or "news.google.com" not in item_url:
        return item_url
    return "https://news.google.com/search?" + urllib.parse.urlencode({"q": title[:90], "hl": "en-IN"})


def _item_line(n: int, item: Item, line: str) -> str:
    where = item.where if item.source != "news" else f"{item.topic} · {item.where}"
    who = f" — {plain(item.sender.split('<')[0])}" if item.sender and item.source != "news" else ""
    body = plain(line or item.title)
    link = f" [open]({short_url(item.url, item.title)})" if item.url else ""
    return f"{n}. {ICONS.get(item.source, '•')} {plain(where)}{who}: {body}{link}"


def brief_text(
    *, day: datetime, ranked: list[Item], lines: dict[str, str], total_new: int, markets: Markets | None,
    results: list[SourceResult], model: str, tz: ZoneInfo, private: list[Item] | None = None,
) -> str:
    out = [f"**Morning brief · {day.strftime('%a %d %b')}**", ""]
    if markets and (markets.quotes or markets.india_gold):
        out += markets_block(markets, tz) + [""]
    if ranked:
        out.append(f"**Top {len(ranked)}**")
        out += [_item_line(n, item, lines.get(item.uid, "")) for n, item in enumerate(ranked, start=1)]
    else:
        out.append("Nothing new since the last brief.")
    out += _private_block(private or [])
    rest = total_new - len(ranked)
    if rest > 0:
        out += ["", f"{rest} more new items. Full list: /brief more"]
    out += _problems(results, markets, model, bool(ranked))
    return "\n".join(out).strip()


def _private_block(items: list[Item]) -> list[str]:
    """Money and HR mail, listed by the script: sender and subject only, never sent to the model."""
    if not items:
        return []
    out = ["", f"**💳 Money & HR · {len(items)}** (not sent to AI)"]
    for item in items[:PRIVATE_SHOWN]:
        who = plain(item.sender.split("<")[0].strip().strip('"') or item.sender)
        link = f" [open]({short_url(item.url, item.title)})" if item.url else ""
        out.append(f"• {who}: {plain(item.title)}{link}")
    if len(items) > PRIVATE_SHOWN:
        out.append(f"…and {len(items) - PRIVATE_SHOWN} more")
    return out


def _problems(results: list[SourceResult], markets: Markets | None, model: str, had_items: bool) -> list[str]:
    notes = []
    for r in results:
        if r.error_kind == "auth":
            notes.append(f"🔑 {source_label(r.name)} needs a new login: {r.error}")
        elif r.error:
            notes.append(f"⚠️ {source_label(r.name)} not included: {r.error}")
    if markets and markets.errors:
        notes.append("⚠️ Markets missing: " + "; ".join(markets.errors[:4]))
    if had_items and not model:
        notes.append("⚠️ No model answered, so items are in time order, not ranked.")
    return ["", *notes] if notes else []


def more_text(edition: dict) -> str:
    top = edition.get("top") or []
    rest = edition.get("rest") or []
    if not top and not rest:
        return "Nothing saved for the latest brief."
    out = [f"**All items · {edition.get('day', '')}** ({len(top) + len(rest)})"]
    groups: dict[str, list[dict]] = {}
    for item in top + rest:
        key = item.get("topic") or SOURCE_LABELS.get(item.get("source", ""), item.get("source", ""))
        groups.setdefault(key, []).append(item)
    shown = 0
    for key, entries in groups.items():
        out += ["", f"**{plain(key)}**"]
        for item in entries:
            if shown >= MORE_LIMIT:
                out.append(f"… and {len(top) + len(rest) - shown} more in the saved edition file.")
                return "\n".join(out)
            link = f" [open]({short_url(item['url'], item.get('title', ''))})" if item.get("url") else ""
            where = f"{plain(item.get('where', ''))}: " if item.get("where") else ""
            out.append(f"• {where}{plain(item.get('title', ''))}{link}")
            shown += 1
    return "\n".join(out)
