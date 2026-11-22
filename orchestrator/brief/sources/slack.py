"""Slack, with either kind of token in SLACK_BOT_TOKEN / SLACK_USER_TOKEN (bot wins if both set).

bot (xoxb-): reads the channels the bot is a member of: conversations.list → history per channel.
    Scopes: channels:read, groups:read, channels:history, groups:history, users:read.
    Never sees DMs between people, or any channel it was not invited to (/invite @bot).
user (xoxp-): one search.messages sweep over everything you can see, DMs included.
    Scope: search:read.

An app installed only in your own workspace is an "internal app" and keeps the normal API
limits (Slack's May 2025 throttling applies to commercially distributed apps outside the
Marketplace).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from ..items import AuthError, Item, SourceError
from ..net import Http
from ..settings import Settings

API = "https://slack.com/api/"
AUTH_ERRORS = {"invalid_auth", "not_authed", "token_expired", "token_revoked", "account_inactive", "missing_scope"}
PAGE = 100
HISTORY_PAUSE = 1.3  # seconds between history calls: stays under 50 calls a minute


def _check(data: dict) -> dict:
    if data.get("ok"):
        return data
    error = str(data.get("error", "unknown error"))
    if error in AUTH_ERRORS:
        needed = f" (needs {data['needed']})" if data.get("needed") else ""
        raise AuthError(f"Slack token problem: {error}{needed}")
    raise SourceError(f"Slack: {error}")


def _call(http: Http, token: str, method: str, **params) -> dict:
    return _check(http.request("GET", API + method, params=params, headers={"Authorization": f"Bearer {token}"}).json())


def _item(channel_id: str, where: str, msg: dict, sender: str, url: str) -> Item:
    text = " ".join((msg.get("text") or "").split())
    return Item(uid=f"slack:{channel_id}:{msg.get('ts', '')}", source="slack", title=text[:140], snippet=text[:400],
                sender=sender, where=where, ts=float(msg.get("ts") or 0), url=url)


# ------------------------------------------------------------------ user token: search
def _search(http: Http, token: str, settings: Settings, since: float) -> list[Item]:
    day = time.strftime("%Y-%m-%d", time.gmtime(since - 86400))  # 'after:' is day-granular; ts filters below
    items: list[Item] = []
    page = 1
    while len(items) < settings.slack_max:
        data = _call(http, token, "search.messages", query=f"after:{day}", sort="timestamp", sort_dir="desc",
                     count=PAGE, page=page)
        matches = (data.get("messages") or {}).get("matches") or []
        fresh = [m for m in matches if float(m.get("ts") or 0) > since]
        for m in fresh:
            channel = m.get("channel") or {}
            where = "DM" if channel.get("is_im") or channel.get("is_mpim") else f"#{channel.get('name', '')}"
            if where.lstrip("#") not in settings.slack_skip_channels:
                items.append(_item(channel.get("id", ""), where, m, m.get("username") or m.get("user") or "",
                                   m.get("permalink") or ""))
        pages = ((data.get("messages") or {}).get("paging") or {}).get("pages", 1)
        if len(fresh) < len(matches) or page >= pages:
            break
        page += 1
    return items


# ------------------------------------------------------------------ bot token: channel history
def _paged(http: Http, token: str, method: str, key: str, **params) -> list[dict]:
    rows: list[dict] = []
    cursor = ""
    while True:
        data = _call(http, token, method, limit=200, **params, **({"cursor": cursor} if cursor else {}))
        rows += data.get(key) or []
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            return rows


def _bot(http: Http, token: str, settings: Settings, since: float, sleep: Callable[[float], None]) -> list[Item]:
    team_url = _call(http, token, "auth.test").get("url", "").rstrip("/")
    names = {u["id"]: (u.get("profile") or {}).get("display_name") or u.get("real_name") or u.get("name", "")
             for u in _paged(http, token, "users.list", "members")}
    channels = [c for c in _paged(http, token, "conversations.list", "channels",
                                  types="public_channel,private_channel", exclude_archived="true")
                if c.get("is_member") and c.get("name") not in settings.slack_skip_channels]
    items: list[Item] = []
    for n, channel in enumerate(channels):
        if n:
            sleep(HISTORY_PAUSE)
        data = _call(http, token, "conversations.history", channel=channel["id"], oldest=f"{since:.6f}", limit=200)
        for msg in data.get("messages") or []:
            if msg.get("subtype") in ("channel_join", "channel_leave", "bot_add", "channel_topic"):
                continue
            link = f"{team_url}/archives/{channel['id']}/p{msg.get('ts', '').replace('.', '')}" if team_url else ""
            items.append(_item(channel["id"], f"#{channel.get('name', '')}", msg,
                               names.get(msg.get("user", ""), msg.get("username", "")), link))
    return sorted(items, key=lambda i: i.ts, reverse=True)


def fetch(http: Http, bot_token: str, user_token: str, settings: Settings, since: float,
          sleep: Callable[[float], None] = time.sleep) -> list[Item]:
    if bot_token:
        return _bot(http, bot_token, settings, since, sleep)[: settings.slack_max]
    if user_token:
        return _search(http, user_token, settings, since)[: settings.slack_max]
    raise SourceError("not set up (SLACK_BOT_TOKEN or SLACK_USER_TOKEN missing)", kind="skipped")
