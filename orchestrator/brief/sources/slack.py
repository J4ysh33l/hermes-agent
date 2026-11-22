"""Slack: one ``search.messages`` sweep (everything the user can see, DMs included) since the last run.

Needs a user token (xoxp-) with the ``search:read`` scope in SLACK_USER_TOKEN.
"""

from __future__ import annotations

import time

from ..items import AuthError, Item, SourceError
from ..net import Http
from ..settings import Settings

SEARCH = "https://slack.com/api/search.messages"
AUTH_ERRORS = {"invalid_auth", "not_authed", "token_expired", "token_revoked", "account_inactive", "missing_scope"}
PAGE = 100


def _check(data: dict) -> dict:
    if data.get("ok"):
        return data
    error = str(data.get("error", "unknown error"))
    if error in AUTH_ERRORS:
        raise AuthError(f"Slack login problem: {error}")
    raise SourceError(f"Slack: {error}")


def _item(match: dict) -> Item:
    channel = match.get("channel") or {}
    name = channel.get("name") or ""
    where = "DM" if channel.get("is_im") or channel.get("is_mpim") else f"#{name}"
    text = " ".join((match.get("text") or "").split())
    return Item(uid=f"slack:{channel.get('id', '')}:{match.get('ts', '')}", source="slack",
                title=text[:140], snippet=text[:400], sender=match.get("username") or match.get("user") or "",
                where=where, ts=float(match.get("ts") or 0), url=match.get("permalink") or "")


def fetch(http: Http, token: str, settings: Settings, since: float) -> list[Item]:
    if not token:
        raise SourceError("not set up (SLACK_USER_TOKEN missing)", kind="skipped")
    day = time.strftime("%Y-%m-%d", time.gmtime(since - 86400))  # 'after:' is day-granular; ts filters below
    headers = {"Authorization": f"Bearer {token}"}
    items: list[Item] = []
    page = 1
    while len(items) < settings.slack_max:
        params = {"query": f"after:{day}", "sort": "timestamp", "sort_dir": "desc", "count": PAGE, "page": page}
        data = _check(http.request("GET", SEARCH, params=params, headers=headers).json())
        matches = (data.get("messages") or {}).get("matches") or []
        fresh = [_item(m) for m in matches if float(m.get("ts") or 0) > since]
        items += [i for i in fresh if i.where.lstrip("#") not in settings.slack_skip_channels]
        pages = ((data.get("messages") or {}).get("paging") or {}).get("pages", 1)
        if len(fresh) < len(matches) or page >= pages:
            break
        page += 1
    return items[: settings.slack_max]
