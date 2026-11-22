"""Gmail via the Gmail API (read-only scope). Refresh token in tokens/google.json
(written by ``python -m orchestrator.brief auth google``); client id/secret in .env."""

from __future__ import annotations

from ..items import AuthError, Item, SourceError
from ..net import Http, HttpError
from ..settings import Settings

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
HEADERS = ("From", "Subject", "List-Unsubscribe", "List-Id", "Precedence")


def access_token(http: Http, client_id: str, client_secret: str, refresh_token: str) -> str:
    if not (client_id and client_secret and refresh_token):
        raise SourceError("not set up (run: python -m orchestrator.brief auth google)", kind="skipped")
    form = {"client_id": client_id, "client_secret": client_secret,
            "refresh_token": refresh_token, "grant_type": "refresh_token"}
    try:
        return http.request("POST", TOKEN_URL, form=form).json()["access_token"]
    except HttpError as exc:
        if exc.status in (400, 401) and ("invalid_grant" in exc.detail or "unauthorized" in exc.detail.lower()):
            raise AuthError("Gmail login expired: run `python -m orchestrator.brief auth google`") from None
        raise


def _item(msg: dict) -> Item:
    headers = {h["name"].lower(): h["value"] for h in (msg.get("payload") or {}).get("headers") or []}
    newsletter = bool(headers.get("list-unsubscribe") or headers.get("list-id")
                      or headers.get("precedence", "").lower() in ("bulk", "list"))
    return Item(uid=f"gmail:{msg['id']}", source="gmail", title=headers.get("subject", "(no subject)")[:200],
                sender=headers.get("from", ""), where="Gmail", snippet=(msg.get("snippet") or "")[:400],
                ts=int(msg.get("internalDate", 0)) / 1000, newsletter=newsletter,
                url=f"https://mail.google.com/mail/u/0/#all/{msg['id']}")


def fetch(http: Http, token: str, settings: Settings, since: float) -> list[Item]:
    auth = {"Authorization": f"Bearer {token}"}
    query = f"after:{int(since)} -category:promotions -category:social -category:forums -in:chats"
    listing = http.request("GET", API, params={"q": query, "maxResults": settings.mail_max}, headers=auth).json()
    items = []
    for ref in listing.get("messages") or []:
        params = {"format": "metadata", "metadataHeaders": list(HEADERS)}
        items.append(_item(http.request("GET", f"{API}/{ref['id']}", params=params, headers=auth).json()))
    return [i for i in items if i.ts > since]
