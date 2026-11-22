"""Outlook via Microsoft Graph, delegated Mail.Read (your mailbox only, not the tenant's).

Public-client app (no client secret). The refresh token rotates on every use, so it lives in
tokens/microsoft.json, rewritten after each run. Log in once with
``python -m orchestrator.brief auth microsoft`` (device code: open a URL, type a code).
"""

from __future__ import annotations

import calendar
import time

from ..items import AuthError, Item, SourceError
from ..net import Http, HttpError
from ..settings import Settings

LOGIN = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
SCOPES = "offline_access Mail.Read"
MESSAGES = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
SELECT = "id,subject,from,bodyPreview,receivedDateTime,webLink,inferenceClassification,internetMessageHeaders"


def refresh(http: Http, client_id: str, tenant: str, token: dict) -> dict:
    """Swap the stored refresh token for a new access + refresh token pair."""
    if not (client_id and token.get("refresh_token")):
        raise SourceError("not set up (run: python -m orchestrator.brief auth microsoft)", kind="skipped")
    form = {"client_id": client_id, "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"], "scope": SCOPES}
    try:
        fresh = http.request("POST", LOGIN.format(tenant=tenant or "organizations") + "/token", form=form).json()
    except HttpError as exc:
        if exc.status in (400, 401) and "invalid_grant" in exc.detail:
            raise AuthError("Outlook login expired: run `python -m orchestrator.brief auth microsoft`") from None
        raise
    return {"refresh_token": fresh.get("refresh_token", token["refresh_token"]),
            "access_token": fresh["access_token"], "saved_at": time.time()}


def _item(msg: dict) -> Item:
    sender = ((msg.get("from") or {}).get("emailAddress") or {})
    headers = {h.get("name", "").lower() for h in msg.get("internetMessageHeaders") or []}
    received = msg.get("receivedDateTime", "1970-01-01T00:00:00Z")
    ts = calendar.timegm(time.strptime(received[:19], "%Y-%m-%dT%H:%M:%S"))
    return Item(uid=f"outlook:{msg['id'][-40:]}", source="outlook", title=(msg.get("subject") or "(no subject)")[:200],
                sender=f"{sender.get('name', '')} <{sender.get('address', '')}>".strip(), where="Outlook",
                snippet=" ".join((msg.get("bodyPreview") or "").split())[:400], ts=ts, url=msg.get("webLink", ""),
                newsletter=bool({"list-unsubscribe", "list-id"} & headers)
                or msg.get("inferenceClassification") == "other")


def fetch(http: Http, access_token: str, settings: Settings, since: float) -> list[Item]:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since))
    params = {"$filter": f"receivedDateTime gt {stamp}", "$select": SELECT,
              "$orderby": "receivedDateTime desc", "$top": settings.mail_max}
    try:
        data = http.request("GET", MESSAGES, params=params, headers={"Authorization": f"Bearer {access_token}"}).json()
    except HttpError as exc:
        if exc.status == 401:
            raise AuthError("Outlook login rejected: run `python -m orchestrator.brief auth microsoft`") from None
        raise
    return [_item(m) for m in data.get("value") or []]
