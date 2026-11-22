"""Record types shared by every source, filter and renderer."""

from __future__ import annotations

from dataclasses import dataclass, field


class SourceError(Exception):
    """A source could not be read. ``kind`` is 'auth' (log in again) or 'fetch' (try later)."""

    def __init__(self, message: str, kind: str = "fetch") -> None:
        super().__init__(message)
        self.kind = kind


class AuthError(SourceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, kind="auth")


@dataclass(frozen=True)
class Item:
    """One message, email or article. ``uid`` is stable across runs (used for 'seen')."""

    uid: str
    source: str  # slack | gmail | outlook | news
    title: str
    ts: float  # unix seconds
    sender: str = ""
    where: str = ""  # channel, folder or publication
    snippet: str = ""
    url: str = ""
    topic: str = ""
    newsletter: bool = False

    def with_topic(self, topic: str) -> Item:
        return Item(**{**self.__dict__, "topic": topic})


@dataclass(frozen=True)
class Quote:
    symbol: str
    label: str
    price: float
    change_pct: float | None
    as_of: float  # unix seconds of the last trade
    unit: str = ""
    group: str = ""
    day: str = ""  # weekday of the last trade in the exchange's own time zone, e.g. 'Fri'


@dataclass(frozen=True)
class SourceResult:
    name: str
    items: tuple[Item, ...] = ()
    error: str = ""
    error_kind: str = ""  # '' | 'auth' | 'fetch' | 'skipped'

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass(frozen=True)
class IndiaGold:
    """IBJA (India Bullion and Jewellers Association) 24K 999 rate, ₹ per 10 g, excluding GST."""

    price_10g: float
    date: str  # as published, e.g. '20/11/2026'
    change_pct: float | None = None


@dataclass(frozen=True)
class Markets:
    quotes: tuple[Quote, ...] = ()
    gold_inr_10g: float | None = None
    india_gold: IndiaGold | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)
