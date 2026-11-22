"""Settings: ``brief.yaml`` (hand-edited) merged with ``prefs.json`` (written by /brief commands)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

EXAMPLE = Path(__file__).resolve().parent / "brief.example.yaml"
SOURCE_NAMES = ("slack", "gmail", "outlook", "news", "markets")


@dataclass(frozen=True)
class Topic:
    name: str
    queries: tuple[str, ...] = ()
    feeds: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    hacker_news: bool = False
    weight: float = 1.0
    per_run: int = 6


@dataclass(frozen=True)
class Symbol:
    symbol: str
    label: str
    unit: str = ""
    group: str = ""


@dataclass(frozen=True)
class ModelChoice:
    id: str
    json_mode: bool = True


@dataclass(frozen=True)
class Prefs:
    """What Telegram commands change. Stored as JSON next to brief.yaml."""

    watchlist: tuple[str, ...] = ()
    muted_words: tuple[str, ...] = ()
    muted_senders: tuple[str, ...] = ()
    followed: tuple[str, ...] = ()  # extra free-text topics, searched on Google News

    @classmethod
    def load(cls, path: Path) -> Prefs:
        if not path.is_file():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{k: tuple(raw.get(k, ())) for k in cls.__dataclass_fields__})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: list(getattr(self, k)) for k in self.__dataclass_fields__}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)


@dataclass(frozen=True)
class Settings:
    timezone: str = "Asia/Kolkata"
    lookback_hours: float = 26
    top_items: int = 8
    sources: frozenset[str] = frozenset(SOURCE_NAMES)
    topics: tuple[Topic, ...] = ()
    markets: tuple[Symbol, ...] = ()
    gold_symbol: str = "GC=F"
    fx_symbol: str = "INR=X"
    show_gold_usd: bool = True
    slack_max: int = 200
    slack_skip_channels: frozenset[str] = frozenset()
    mail_max: int = 50
    keep_newsletters_from: tuple[str, ...] = ()
    exclude_senders: tuple[str, ...] = ()
    exclude_subject_words: tuple[str, ...] = ()
    muted_words: tuple[str, ...] = ()
    muted_senders: tuple[str, ...] = ()
    max_input_tokens: int = 12000
    models: tuple[ModelChoice, ...] = ()
    prefs: Prefs = field(default_factory=Prefs)

    def all_topics(self) -> tuple[Topic, ...]:
        extra = tuple(Topic(name=f, queries=(f,), weight=1.5, per_run=5) for f in self.prefs.followed)
        return self.topics + extra

    def all_symbols(self) -> tuple[Symbol, ...]:
        known = {s.symbol for s in self.markets}
        watch = tuple(Symbol(s, s, group="Watchlist") for s in self.prefs.watchlist if s not in known)
        return self.markets + watch

    def all_muted_words(self) -> tuple[str, ...]:
        return self.muted_words + self.prefs.muted_words

    def all_muted_senders(self) -> tuple[str, ...]:
        return self.muted_senders + self.prefs.muted_senders


def _tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in (value or ()))


def _topic(raw: dict[str, Any]) -> Topic:
    return Topic(
        name=str(raw["name"]),
        queries=_tuple(raw.get("queries")),
        feeds=_tuple(raw.get("feeds")),
        keywords=tuple(k.lower() for k in _tuple(raw.get("keywords"))),
        hacker_news=bool(raw.get("hacker_news", False)),
        weight=float(raw.get("weight", 1.0)),
        per_run=int(raw.get("per_run", 6)),
    )


def parse(raw: dict[str, Any], prefs: Prefs) -> Settings:
    gold = raw.get("gold") or {}
    slack = raw.get("slack") or {}
    mail = raw.get("mail") or {}
    ranking = raw.get("ranking") or {}
    enabled = raw.get("sources") or {}
    return Settings(
        timezone=str(raw.get("timezone", "Asia/Kolkata")),
        lookback_hours=float(raw.get("lookback_hours", 26)),
        top_items=int(raw.get("top_items", 8)),
        sources=frozenset(n for n in SOURCE_NAMES if enabled.get(n, True)),
        topics=tuple(_topic(t) for t in raw.get("topics") or ()),
        markets=tuple(Symbol(str(m["symbol"]), str(m.get("label", m["symbol"])), str(m.get("unit", "")),
                            str(m.get("group", "")))
                      for m in raw.get("markets") or ()),
        gold_symbol=str(gold.get("symbol", "GC=F")),
        fx_symbol=str(gold.get("fx_symbol", "INR=X")),
        show_gold_usd=bool(gold.get("show_usd_per_oz", True)),
        slack_max=int(slack.get("max_messages", 200)),
        slack_skip_channels=frozenset(_tuple(slack.get("skip_channels"))),
        mail_max=int(mail.get("max_messages", 50)),
        keep_newsletters_from=tuple(s.lower() for s in _tuple(mail.get("keep_newsletters_from"))),
        exclude_senders=tuple(s.lower() for s in _tuple(mail.get("exclude_senders"))),
        exclude_subject_words=tuple(s.lower() for s in _tuple(mail.get("exclude_subject_words"))),
        muted_words=tuple(s.lower() for s in _tuple(raw.get("muted_words"))),
        muted_senders=tuple(s.lower() for s in _tuple(raw.get("muted_senders"))),
        max_input_tokens=int(ranking.get("max_input_tokens", 12000)),
        models=tuple(ModelChoice(str(m["id"]), bool(m.get("json_mode", True))) for m in ranking.get("models") or ()),
        prefs=prefs,
    )


def load(state_dir: Path) -> Settings:
    """brief.yaml from the state folder, or the shipped example when none was copied yet."""
    path = state_dir / "brief.yaml"
    raw = yaml.safe_load((path if path.is_file() else EXAMPLE).read_text(encoding="utf-8")) or {}
    return parse(raw, Prefs.load(state_dir / "prefs.json"))
