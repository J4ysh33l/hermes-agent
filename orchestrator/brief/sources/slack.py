"""Slack, with a user token (SLACK_USER_TOKEN, preferred) or a bot token (SLACK_BOT_TOKEN).

user (xoxp-): everything you are a member of (channels, private channels, DMs, group DMs, and
    thread replies, including replies to threads started before the last run).
    1. users.conversations: every conversation you are in, with names (1 call)
    2. search.messages since the last run, kept only where you are a member (1 call per 100
       messages). Measured on a 61-conversation workspace over 48 h: 5 calls in 1 s, against 73
       calls in 10 s for history + replies per conversation, and search also caught replies to
       older threads that history cannot see.
    3. users.list: every name in one call (166 people: 1 call, 0.3 s); users.info only for
       someone it missed, such as a person from another workspace
    Scopes: channels:read, groups:read, im:read, mpim:read, search:read, users:read.
    search.messages is marked "legacy" by Slack; if it is ever switched off, the user token falls
    back to the history path below.
bot (xoxb-): only channels the bot was invited to (/invite @bot), never DMs: conversations.list →
    conversations.history per channel. Scopes: channels:read, groups:read, channels:history,
    groups:history, users:read.

Messages are grouped into one item per conversation (per thread for thread replies), so the
model reads "#ops: 7 new (Asha, Ravi): …" instead of seven separate rows.

Internal apps keep the normal API limits; Slack's 2025 throttle (1 call a minute) applies only
to commercially distributed apps outside the Marketplace.
"""

from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass

from ..items import AuthError, Item, SourceError
from ..net import Http
from ..settings import Settings

API = "https://slack.com/api/"
AUTH_ERRORS = {"invalid_auth", "not_authed", "token_expired", "token_revoked", "account_inactive", "missing_scope"}
SEARCH_GONE = {"method_deprecated", "unknown_method"}
SKIP_SUBTYPES = {"channel_join", "channel_leave", "bot_add", "channel_topic", "channel_purpose", "huddle_thread"}
CONVERSATION_TYPES = "public_channel,private_channel,mpim,im"
PAGE = 100
MAX_PAGES = 20


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


def _paged(http: Http, token: str, method: str, key: str, **params) -> list[dict]:
    rows: list[dict] = []
    cursor = ""
    while True:
        data = _call(http, token, method, limit=200, **params, **({"cursor": cursor} if cursor else {}))
        rows += data.get(key) or []
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            return rows


@dataclass(frozen=True)
class Message:
    channel: str
    ts: str
    user: str
    text: str
    link: str
    thread_ts: str = ""  # set for a reply inside a thread


class People:
    """User id → display name, looked up once per id per run."""

    def __init__(self, http: Http, token: str) -> None:
        self._http, self._token, self._names = http, token, {}

    def add(self, members: list[dict]) -> None:
        self._names.update({m["id"]: _display(m) for m in members})

    def name(self, user_id: str) -> str:
        if user_id and user_id not in self._names:
            try:
                self._names[user_id] = _display(_call(self._http, self._token, "users.info", user=user_id)["user"])
            except SourceError:
                self._names[user_id] = user_id
        return self._names.get(user_id, user_id)


def _display(member: dict) -> str:
    profile = member.get("profile") or {}
    return profile.get("display_name") or profile.get("real_name") or member.get("real_name") or member.get("name", "")


def _label(conv: dict, people: People) -> str:
    if conv.get("is_im"):
        return f"DM: {people.name(conv.get('user', ''))}"
    if conv.get("is_mpim"):  # name looks like mpdm-asha--ravi--you-1
        handles = conv.get("name", "").removeprefix("mpdm-").rsplit("-", 1)[0].split("--")
        return "Group DM: " + ", ".join(h for h in handles if h)
    return f"#{conv.get('name', '')}"


def _group(conv: dict, label: str, settings: Settings) -> str:
    if conv.get("is_im") or conv.get("is_mpim"):
        return settings.slack_dm_group
    name = label.lstrip("#")
    return next((g for g, names in settings.slack_groups if name in names), settings.slack_other_group)


def _thread_of(permalink: str) -> str:
    return (urllib.parse.parse_qs(urllib.parse.urlsplit(permalink).query).get("thread_ts") or [""])[0]


# ------------------------------------------------------------------ collecting messages
def _searched(http: Http, token: str, member: set[str], since: float) -> list[Message]:
    day = time.strftime("%Y-%m-%d", time.gmtime(since - 86400))  # 'after:' is day-granular; ts filters below
    found: list[Message] = []
    for page in range(1, MAX_PAGES + 1):
        data = _call(http, token, "search.messages", query=f"after:{day}", sort="timestamp", sort_dir="desc",
                     count=PAGE, page=page)
        matches = (data.get("messages") or {}).get("matches") or []
        for m in matches:
            channel = (m.get("channel") or {}).get("id", "")
            if float(m.get("ts") or 0) > since and channel in member:
                link = m.get("permalink") or ""
                thread = _thread_of(link)
                found.append(Message(channel, m["ts"], m.get("user") or "", m.get("text") or "", link,
                                     thread if thread and thread != m["ts"] else ""))
        pages = ((data.get("messages") or {}).get("paging") or {}).get("pages", 1)
        if page >= pages or any(float(m.get("ts") or 0) <= since for m in matches):
            break
    return found


def _history(http: Http, token: str, convs: list[dict], since: float, team_url: str) -> list[Message]:
    found: list[Message] = []
    oldest = f"{since:.6f}"
    for conv in convs:
        cid = conv["id"]
        for msg in _call(http, token, "conversations.history", channel=cid, oldest=oldest, limit=200).get("messages") or []:
            if msg.get("subtype") in SKIP_SUBTYPES:
                continue
            found.append(Message(cid, msg["ts"], msg.get("user", ""), msg.get("text") or "", _link(team_url, cid, msg["ts"])))
            if msg.get("reply_count") and float(msg.get("latest_reply") or 0) > since:
                replies = _call(http, token, "conversations.replies", channel=cid, ts=msg["ts"], oldest=oldest)
                found += [Message(cid, r["ts"], r.get("user", ""), r.get("text") or "",
                                  _link(team_url, cid, r["ts"], msg["ts"]), msg["ts"])
                          for r in replies.get("messages") or [] if r["ts"] != msg["ts"] and float(r["ts"]) > since]
    return found


def _link(team_url: str, channel: str, ts: str, thread_ts: str = "") -> str:
    if not team_url:
        return ""
    link = f"{team_url}/archives/{channel}/p{ts.replace('.', '')}"
    return link + (f"?thread_ts={thread_ts}&cid={channel}" if thread_ts else "")


# ------------------------------------------------------------------ grouping into items
def _items(messages: list[Message], convs: dict[str, dict], people: People, settings: Settings) -> list[Item]:
    buckets: dict[tuple[str, str], list[Message]] = {}
    for msg in sorted(messages, key=lambda m: float(m.ts)):
        buckets.setdefault((msg.channel, msg.thread_ts), []).append(msg)
    items = []
    for (cid, thread), msgs in buckets.items():
        conv = convs[cid]
        label = _label(conv, people)
        where = f"{_group(conv, label, settings)} · {label}" + (" (thread)" if thread else "")
        senders = list(dict.fromkeys(people.name(m.user) for m in msgs if m.user))
        lines = " / ".join(f"{people.name(m.user)}: {' '.join(m.text.split())}" for m in msgs[-6:])
        latest = msgs[-1]
        count = f"{len(msgs)} new: " if len(msgs) > 1 else ""
        items.append(Item(uid=f"slack:{cid}:{thread}:{latest.ts}", source="slack",
                          title=(count + " ".join(latest.text.split()))[:140], snippet=lines[:600],
                          sender=", ".join(senders)[:80], where=where, ts=float(latest.ts), url=latest.link))
    return sorted(items, key=lambda i: i.ts, reverse=True)


def _user(http: Http, token: str, settings: Settings, since: float) -> list[Item]:
    convs = {c["id"]: c for c in _paged(http, token, "users.conversations", "channels",
                                         types=CONVERSATION_TYPES, exclude_archived="true")}
    people = People(http, token)
    people.add(_paged(http, token, "users.list", "members"))
    wanted = {cid for cid, c in convs.items()
              if c.get("is_im") or c.get("is_mpim") or c.get("name") not in settings.slack_skip_channels}
    try:
        messages = _searched(http, token, wanted, since)
    except SourceError as exc:
        if not any(gone in str(exc) for gone in SEARCH_GONE):
            raise
        team_url = _call(http, token, "auth.test").get("url", "").rstrip("/")
        messages = _history(http, token, [convs[c] for c in wanted], since, team_url)
    return _items(messages[: settings.slack_max], convs, people, settings)


def _bot(http: Http, token: str, settings: Settings, since: float) -> list[Item]:
    team_url = _call(http, token, "auth.test").get("url", "").rstrip("/")
    people = People(http, token)
    people.add(_paged(http, token, "users.list", "members"))
    convs = {c["id"]: c for c in _paged(http, token, "conversations.list", "channels",
                                         types="public_channel,private_channel", exclude_archived="true")
             if c.get("is_member") and c.get("name") not in settings.slack_skip_channels}
    messages = _history(http, token, list(convs.values()), since, team_url)
    return _items(messages[: settings.slack_max], convs, people, settings)


def fetch(http: Http, bot_token: str, user_token: str, settings: Settings, since: float) -> list[Item]:
    if user_token:
        return _user(http, user_token, settings, since)
    if bot_token:
        return _bot(http, bot_token, settings, since)
    raise SourceError("not set up (SLACK_USER_TOKEN or SLACK_BOT_TOKEN missing)", kind="skipped")
