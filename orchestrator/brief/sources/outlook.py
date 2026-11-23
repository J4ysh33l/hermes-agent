"""Outlook via Microsoft Graph, delegated Mail.Read (your mailbox only, not the tenant's).

Sign-in asks for every scope (``LOGIN_SCOPES``) so one consent covers outreach meetings too, but
each refresh asks only for what its caller needs: the brief keeps working on Mail.Read even
while the calendar permissions are not granted yet.

Public-client app (no client secret). The refresh token rotates on every use, so it lives in
tokens/microsoft.json, rewritten after each run. Log in once with
``python -m orchestrator.brief auth microsoft`` (paste-back: open the link, sign in, paste
the address the browser lands on).
"""

from __future__ import annotations

import calendar
import time

from ..items import AuthError, Item, SourceError
from ..net import Http, HttpError
from ..settings import Settings

LOGIN = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
SCOPES = "offline_access Mail.Read"
MEETING_SCOPES = "offline_access Calendars.ReadWrite User.ReadBasic.All"  # orchestrator/outreach
SEND_SCOPES = "offline_access Mail.Send User.Read"  # orchestrator/hr: mail from your mailbox; /me for tests
TODO_SCOPES = "offline_access Tasks.ReadWrite"  # orchestrator/myday: Microsoft To Do
LOGIN_SCOPES = "offline_access User.Read Mail.Read Mail.Send Calendars.ReadWrite User.ReadBasic.All Tasks.ReadWrite"
NOT_CONSENTED = "AADSTS65001"
MESSAGES = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
SELECT = "id,subject,from,bodyPreview,receivedDateTime,webLink,inferenceClassification,internetMessageHeaders"


def refresh(http: Http, client_id: str, tenant: str, token: dict, scopes: str = SCOPES) -> dict:
    """Swap the stored refresh token for a new access + refresh token pair for ``scopes``."""
    if not (client_id and token.get("refresh_token")):
        raise SourceError("not set up (run: python -m orchestrator.brief auth microsoft)", kind="skipped")
    form = {"client_id": client_id, "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"], "scope": scopes}
    try:
        fresh = http.request("POST", LOGIN.format(tenant=tenant or "organizations") + "/token", form=form).json()
    except HttpError as exc:
        if NOT_CONSENTED in exc.detail:
            raise AuthError(f"Outlook permission not granted for: {scopes.removeprefix('offline_access ')}. "
                            "Entra → API permissions → add it → Grant admin consent, then "
                            "`python -m orchestrator.brief auth microsoft`") from None
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
