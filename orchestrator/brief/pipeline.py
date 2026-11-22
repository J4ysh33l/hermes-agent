"""One brief run: collect → filter → (one model call) → render → save. Never raises for a
source failure: the brief goes out with what worked and names what did not."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from . import filters, rank, render
from .creds import Secrets
from .items import Item, Markets, SourceError, SourceResult
from .net import Http, HttpError
from .settings import Settings
from .sources import gmail, markets, news, outlook, slack
from .store import Store

PROMPT_OVERHEAD_TOKENS = 800  # instructions + answer room inside max_input_tokens


@dataclass(frozen=True)
class RunResult:
    text: str
    model: str
    new_items: int
    ranked: int


def _slack(http: Http, settings: Settings, secrets: Secrets, since: float) -> list[Item]:
    return slack.fetch(http, secrets.get("SLACK_BOT_TOKEN"), secrets.get("SLACK_USER_TOKEN"), settings, since)


def _gmail_account(account: gmail.Account) -> Callable[[Http, Settings, Secrets, float], list[Item]]:
    def fetch(http: Http, settings: Settings, secrets: Secrets, since: float) -> list[Item]:
        stored = secrets.token(account.token_name)
        token = gmail.access_token(http, secrets.get("GOOGLE_CLIENT_ID"), secrets.get("GOOGLE_CLIENT_SECRET"),
                                   stored.get("refresh_token", ""), account.label)
        return gmail.fetch(http, token, settings, since, account.label, stored.get("email", ""))
    return fetch


def _gmail_missing(http: Http, settings: Settings, secrets: Secrets, since: float) -> list[Item]:
    raise SourceError("not set up (run: python -m orchestrator.brief auth google)", kind="skipped")


def _outlook(http: Http, settings: Settings, secrets: Secrets, since: float) -> list[Item]:
    fresh = outlook.refresh(http, secrets.get("MS_CLIENT_ID"), secrets.get("MS_TENANT_ID"), secrets.token("microsoft"))
    secrets.save_token("microsoft", {"refresh_token": fresh["refresh_token"], "saved_at": fresh["saved_at"]})
    return outlook.fetch(http, fresh["access_token"], settings, since)


def _news(http: Http, settings: Settings, secrets: Secrets, since: float) -> list[Item]:
    items: list[Item] = []
    errors: list[str] = []
    topics = settings.all_topics()
    for topic in topics:
        found, problems = news.fetch_topic(http, topic, since)
        items += found
        errors += problems
    feeds = sum(len(t.queries) + len(t.feeds) for t in topics)
    if errors and len(errors) >= feeds:
        raise SourceError("every news feed failed: " + errors[0])
    return items


Fetcher = Callable[[Http, Settings, Secrets, float], list[Item]]
FETCHERS: dict[str, Fetcher] = {"slack": _slack, "gmail": _gmail_missing, "outlook": _outlook, "news": _news}


def _fetchers(settings: Settings, secrets: Secrets) -> list[tuple[str, Fetcher]]:
    """Enabled sources in order. Gmail becomes one entry per logged-in account ('gmail',
    'gmail:work', ...), each with its own watermark and its own login alert."""
    out: list[tuple[str, Fetcher]] = []
    for name, fetch in FETCHERS.items():
        if name not in settings.sources:
            continue
        if name == "gmail" and (found := gmail.accounts(secrets.token_dir)):
            out += [("gmail" if a.label == gmail.MAIN else f"gmail:{a.label}", _gmail_account(a)) for a in found]
        else:
            out.append((name, fetch))
    return out


def collect(http: Http, settings: Settings, secrets: Secrets, store: Store, now: float) -> list[SourceResult]:
    results = []
    for name, fetch in _fetchers(settings, secrets):
        try:
            items = fetch(http, settings, secrets, store.since(name, now, settings.lookback_hours))
            results.append(SourceResult(name, tuple(items)))
        except SourceError as exc:
            results.append(SourceResult(name, error=str(exc), error_kind=exc.kind))
        except (HttpError, ValueError, KeyError) as exc:
            results.append(SourceResult(name, error=str(exc)[:200], error_kind="fetch"))
    return results


def run(http: Http, settings: Settings, secrets: Secrets, store: Store, now: float, *, dry_run: bool = False) -> RunResult:
    tz = ZoneInfo(settings.timezone)
    results = collect(http, settings, secrets, store, now)
    market = markets.fetch(http, settings) if "markets" in settings.sources else Markets()

    work = [i for r in results if r.name != "news" for i in r.items]
    fresh_news = [i for r in results if r.name == "news" for i in r.items]
    kept_work, private, _ = filters.keep(work, settings, store.is_seen)
    kept_news, _, _ = filters.keep(fresh_news, settings, store.is_seen)
    candidates = kept_work + filters.cap_news(kept_news, settings)
    fits, over = filters.fit_budget(candidates, settings.max_input_tokens - PROMPT_OVERHEAD_TOKENS)

    ranked = rank.rank(http, secrets.get("GEMINI_API_KEY", "GOOGLE_API_KEY"), fits, settings)
    chosen = {i.uid for i in ranked.items}
    # Only the capped candidates are listed in /brief more; older headlines past a topic's
    # per_run are still marked seen below so they never resurface as stale "new" items.
    rest = [i for i in candidates if i.uid not in chosen]
    day = datetime.fromtimestamp(now, tz)
    text = render.brief_text(day=day, ranked=list(ranked.items), lines=ranked.lines,
                             total_new=len(ranked.items) + len(rest), markets=market, results=results,
                             model=ranked.model, tz=tz, private=private)
    if not dry_run:
        meta = {"model": ranked.model, "model_errors": list(ranked.errors), "over_budget": len(over),
                "failed": {r.name: r.error for r in results if r.error}}
        store.save_edition(day.strftime("%Y-%m-%d"), text, list(ranked.items), rest, meta)
        store.mark_seen([i.uid for i in kept_work + kept_news + private], now)
        store.mark_run([r.name for r in results if r.ok], now)
    return RunResult(text=text, model=ranked.model, new_items=len(ranked.items) + len(rest), ranked=len(ranked.items))
