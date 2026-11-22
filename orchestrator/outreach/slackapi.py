"""Slack Web API calls for sending as you, with SLACK_USER_TOKEN (xoxp-).

Scopes (already in the app manifest, LOGINS.md §1.4): users:read, users:read.email,
channels:read, groups:read, im:write, mpim:write, chat:write.
Reads are GET with query parameters; writes are POST with a JSON body.
"""

from __future__ import annotations

from typing import Any

from orchestrator.brief.net import Http

from .errors import OutreachError

API = "https://slack.com/api/"


def _check(method: str, data: dict) -> dict:
    if data.get("ok"):
        return data
    needed = f" (needs scope {data['needed']})" if data.get("needed") else ""
    raise OutreachError(f"Slack {method}: {data.get('error', 'unknown error')}{needed}")


def get(http: Http, token: str, method: str, **params: Any) -> dict:
    resp = http.request("GET", API + method, params=params, headers={"Authorization": f"Bearer {token}"})
    return _check(method, resp.json())


def post(http: Http, token: str, method: str, body: dict[str, Any]) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    return _check(method, http.request("POST", API + method, headers=headers, json_body=body).json())


def paged(http: Http, token: str, method: str, key: str, **params: Any) -> list[dict]:
    rows: list[dict] = []
    cursor = ""
    while True:
        data = get(http, token, method, limit=200, **params, **({"cursor": cursor} if cursor else {}))
        rows += data.get(key) or []
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            return rows


def me(http: Http, token: str) -> str:
    return get(http, token, "auth.test")["user_id"]


def users(http: Http, token: str) -> list[dict]:
    return paged(http, token, "users.list", "members")


def by_email(http: Http, token: str, email: str) -> dict | None:
    try:
        return get(http, token, "users.lookupByEmail", email=email)["user"]
    except OutreachError as exc:
        if "users_not_found" in str(exc):
            return None
        raise


def channel(http: Http, token: str, name: str) -> dict:
    """A channel you are in, by name (without '#')."""
    want = name.lstrip("#").lower()
    for conv in paged(http, token, "users.conversations", "channels", types="public_channel,private_channel",
                      exclude_archived="true"):
        if conv.get("name", "").lower() == want:
            return conv
    raise OutreachError(f"You are not in a Slack channel called #{want}.")


def channel_members(http: Http, token: str, channel_id: str) -> list[str]:
    return paged(http, token, "conversations.members", "members", channel=channel_id)


def open_dm(http: Http, token: str, user_ids: list[str]) -> str:
    """One id → 1:1 DM; 2-8 ids → group DM. Returns the conversation id."""
    return post(http, token, "conversations.open", {"users": ",".join(user_ids)})["channel"]["id"]


def send(http: Http, token: str, channel_id: str, text: str) -> str:
    return post(http, token, "chat.postMessage", {"channel": channel_id, "text": text})["ts"]


def schedule(http: Http, token: str, channel_id: str, text: str, post_at: int) -> str:
    data = post(http, token, "chat.scheduleMessage", {"channel": channel_id, "text": text, "post_at": post_at})
    return data["scheduled_message_id"]
