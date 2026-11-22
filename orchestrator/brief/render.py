"""Telegram text in standard markdown (Hermes converts it to Telegram's format on delivery)."""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .items import Item, Markets, Quote, SourceResult

ICONS = {"slack": "💬", "gmail": "✉️", "outlook": "📧", "news": "📰"}
WORK_SOURCES = ("gmail", "outlook", "slack")
SOURCE_LABELS = {"slack": "Slack", "gmail": "Gmail", "outlook": "Outlook", "news": "News", "markets": "Markets"}
PRIVATE_SHOWN = 8
TELEGRAM_BUDGET = 4000  # one message is 4096 characters of visible text
MARKUP = re.compile(r"\*\*|(?<!\w)_|_(?!\w)")


def source_label(name: str) -> str:
    """'gmail:work' → 'Gmail (work)'."""
    base, _, account = name.partition(":")
    label = SOURCE_LABELS.get(base, base)
    return f"{label} ({account})" if account else label
MARKDOWN_SPECIALS = re.compile(r"[*_`\[\]]")
MORE_LIMIT = 80


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
    lines = ["**📈 Markets** (last close)"]
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


def _who(item: Item) -> str:
    """'Asha Rao <asha@x.com>' → 'Asha Rao'; a bare address stays as it is."""
    return plain(item.sender.split("<")[0].strip().strip('"') or item.sender.strip("<> "))


def _work_line(item: Item, line: str) -> str:
    """Slack and mail: who and what. A one-to-one DM is named once, by its sender, and
    the sender is not repeated when the model's line already opens with their name."""
    place = item.where.removesuffix(" (thread)")
    prefix = f"{plain(place)} — " if item.source == "slack" and place != item.sender else ""
    who, body = _who(item), plain(line or item.title)
    names = [n.strip() for n in who.split(",") if n.strip()]
    if line and any(body.startswith(n) for n in names):
        return f"• {prefix}{body}"
    return f"• {prefix}{who}: {body}"


def _news_line(n: int, item: Item, line: str) -> str:
    return f"{n}. {plain(item.topic)} · {plain(item.where)}: {plain(line or item.title)}"


def _group_key(item: Item) -> str:
    """Subsection inside a source: the Gmail account, the Slack group; Outlook has one."""
    return {"gmail": item.where, "slack": item.topic}.get(item.source, "")


def _work_section(source: str, picked: list[Item], lines: dict[str, str], private: list[Item],
                  rest: list[Item], order: tuple[str, ...]) -> list[str]:
    groups: dict[str, tuple[list[Item], list[Item], list[Item]]] = {}
    for bucket, items in enumerate((picked, private, rest)):
        for item in items:
            if item.source == source:
                groups.setdefault(_group_key(item), ([], [], []))[bucket].append(item)
    if not groups:
        return []
    out = ["", f"**{ICONS[source]} {SOURCE_LABELS[source]}**"]
    for key in sorted(groups, key=lambda k: order.index(k) if k in order else len(order)):
        chosen, money, others = groups[key]
        if key:
            out.append(f"_{plain(key)}_")
        out += [_work_line(item, lines.get(item.uid, "")) for item in chosen]
        if money:
            out.append(f"💳 Money & HR · {len(money)} (not sent to AI)")
            out += [f"• {plain(item.title)}" for item in money[:PRIVATE_SHOWN]]
            if len(money) > PRIVATE_SHOWN:
                out.append(f"…and {len(money) - PRIVATE_SHOWN} more")
        if others:
            out.append(f"+{len(others)} more" if chosen or money else f"{len(others)} new, nothing that needs you")
    return out


def _news_section(picked: list[Item], lines: dict[str, str], rest: list[Item]) -> list[str]:
    news = [i for i in picked if i.source == "news"]
    more = sum(1 for i in rest if i.source == "news")
    if not news and not more:
        return []
    out = ["", f"**{ICONS['news']} News · Top {len(news)}**" if news else f"**{ICONS['news']} News**"]
    out += [_news_line(n, item, lines.get(item.uid, "")) for n, item in enumerate(news, start=1)]
    if more:
        out.append(f"+{more} more headlines")
    return out


def brief_text(
    *, day: datetime, ranked: list[Item], lines: dict[str, str], rest: list[Item], markets: Markets | None,
    results: list[SourceResult], model: str, tz: ZoneInfo, private: list[Item] | None = None,
    slack_order: tuple[str, ...] = (),
) -> str:
    """Sections in a fixed order: Markets, Gmail (by account), Outlook, Slack (by group), News.
    No links: they cost space; the saved edition keeps every URL for when one is asked for. The brief
    is one Telegram message: past TELEGRAM_BUDGET the lowest-ranked work items, then headlines,
    move into the '+N more' counts."""
    picked, overflow = list(ranked), list(rest)
    while True:
        text = _compose(day, picked, lines, overflow, markets, results, model, tz, private or [], slack_order)
        if visible_length(text) <= TELEGRAM_BUDGET or not picked:
            return text
        cut = next((i for i in reversed(picked) if i.source != "news"), picked[-1])
        picked.remove(cut)
        overflow.append(cut)


def visible_length(text: str) -> int:
    """What Telegram counts against its limit: bold/italic markers are entities, not text."""
    return len(MARKUP.sub("", text))


def _compose(day: datetime, picked: list[Item], lines: dict[str, str], rest: list[Item], markets: Markets | None,
             results: list[SourceResult], model: str, tz: ZoneInfo, private: list[Item],
             slack_order: tuple[str, ...]) -> str:
    out = [f"**Morning brief · {day.strftime('%a %d %b')}**"]
    if markets and (markets.quotes or markets.india_gold):
        out += [""] + markets_block(markets, tz)
    body: list[str] = []
    for source in WORK_SOURCES:
        body += _work_section(source, picked, lines, private, rest, slack_order)
    body += _news_section(picked, lines, rest)
    out += body or ["", "Nothing new since the last brief."]
    if rest:
        out += ["", f"{len(rest)} more new items. Full list: /brief more"]
    out += _problems(results, markets, model, bool(picked))
    return "\n".join(out).strip()


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
            where = f"{plain(item.get('where', ''))}: " if item.get("where") else ""
            out.append(f"• {where}{plain(item.get('title', ''))}")
            shown += 1
    return "\n".join(out)
