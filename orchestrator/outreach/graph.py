"""Microsoft Graph for meetings, with the brief's Outlook login (delegated, your account only).

Scopes (``orchestrator.brief.sources.outlook.MEETING_SCOPES``): Calendars.ReadWrite (your busy times and
creating events) and User.ReadBasic.All (finding a colleague's email by name). A refresh token
can be swapped for any scope the account already consented to; if the permissions were granted
after your last sign-in, sign in once more (``python -m orchestrator.brief auth microsoft``).

Creating an event with attendees makes Outlook send each of them the invite email at that moment,
from your mailbox, with Accept/Decline buttons and (for a Teams event) the Teams join link in the
body. ``transactionId`` makes a retried create return the same event instead of a second invite.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone, UTC

from orchestrator.brief.creds import Secrets
from orchestrator.brief.items import SourceError
from orchestrator.brief.net import Http, HttpError
from orchestrator.brief.sources import outlook

from .errors import OutreachError

GRAPH = "https://graph.microsoft.com/v1.0"
FREE = {"free", "workingElsewhere"}


def access(http: Http, secrets: Secrets, scopes: str = outlook.MEETING_SCOPES) -> str:
    """A fresh access token for ``scopes``; the rotated refresh token is saved, as the brief does."""
    try:
        fresh = outlook.refresh(http, secrets.get("MS_CLIENT_ID"), secrets.get("MS_TENANT_ID"),
                                secrets.token("microsoft"), scopes)
    except (SourceError, HttpError) as exc:
        raise OutreachError(f"Outlook: {exc}") from None
    secrets.save_token("microsoft", {"refresh_token": fresh["refresh_token"], "saved_at": fresh["saved_at"]})
    return fresh["access_token"]


def _call(http: Http, token: str, method: str, path: str, **kw) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Prefer": 'outlook.timezone="UTC"'}
    try:
        return http.request(method, GRAPH + path, headers=headers, **kw).json()
    except HttpError as exc:
        hint = " (permission missing in Entra, or the login predates it)" if exc.status == 403 else ""
        raise OutreachError(f"Outlook {method} {path.split('?')[0]}: HTTP {exc.status}{hint}") from None


def _utc(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp[:19]).replace(tzinfo=UTC)


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def busy(http: Http, token: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Your events between start and end that block time (tentative counts as busy)."""
    params = {"startDateTime": _iso(start) + "Z", "endDateTime": _iso(end) + "Z",
              "$select": "start,end,showAs,isCancelled", "$top": 200}
    rows = _call(http, token, "GET", "/me/calendarView", params=params).get("value") or []
    return sorted((_utc(e["start"]["dateTime"]), _utc(e["end"]["dateTime"])) for e in rows
                  if not e.get("isCancelled") and e.get("showAs") not in FREE)


def find_people(http: Http, token: str, word: str) -> list[dict[str, str]]:
    """Colleagues whose display name, first name or email starts with ``word``."""
    safe = word.replace("'", "''")
    flt = f"startswith(displayName,'{safe}') or startswith(givenName,'{safe}') or startswith(mail,'{safe}')"
    params = {"$filter": flt, "$select": "displayName,givenName,mail,userPrincipalName", "$top": 10}
    rows = _call(http, token, "GET", "/users", params=params).get("value") or []
    return [{"name": r.get("displayName") or "", "first": r.get("givenName") or "",
             "email": r.get("mail") or r.get("userPrincipalName") or ""} for r in rows if r.get("mail")
            or r.get("userPrincipalName")]


def create_event(http: Http, token: str, *, subject: str, body_html: str, start: datetime, end: datetime,
                 attendees: list[dict[str, str]], teams: bool, transaction_id: str = "") -> tuple[str, str]:
    """Returns (event id, Teams join link or ''). Outlook emails the invite immediately."""
    body = {"subject": subject, "body": {"contentType": "HTML", "content": body_html},
            "start": {"dateTime": _iso(start), "timeZone": "UTC"},
            "end": {"dateTime": _iso(end), "timeZone": "UTC"},
            "attendees": [{"emailAddress": {"address": a["email"], "name": a.get("name", "")}, "type": "required"}
                          for a in attendees],
            "allowNewTimeProposals": True, "responseRequested": True}
    if transaction_id:
        body["transactionId"] = transaction_id
    if teams:
        body |= {"isOnlineMeeting": True, "onlineMeetingProvider": "teamsForBusiness"}
    data = _call(http, token, "POST", "/me/events", json_body=body)
    join = (data.get("onlineMeeting") or {}).get("joinUrl") or ""
    if teams and not join and data.get("id"):  # the Teams link can lag the create by a moment
        again = _call(http, token, "GET", f"/me/events/{data['id']}", params={"$select": "onlineMeeting"})
        join = (again.get("onlineMeeting") or {}).get("joinUrl") or ""
    return data.get("id", ""), join


def me(http: Http, token: str) -> str:
    """Your own email address (needs User.Read, which every sign-in carries)."""
    data = _call(http, token, "GET", "/me", params={"$select": "mail,userPrincipalName"})
    return data.get("mail") or data.get("userPrincipalName") or ""


def send_mail(http: Http, token: str, *, to: tuple[str, str], subject: str, body_html: str,
              attachments: tuple[tuple[str, bytes], ...] = ()) -> None:
    """One email from your mailbox (kept in Sent Items). ``to``: (name, address). Attachments:
    (file name, PDF bytes); Graph takes up to 3 MB per message this way, far above a payslip."""
    message = {"subject": subject, "body": {"contentType": "HTML", "content": body_html},
               "toRecipients": [{"emailAddress": {"name": to[0], "address": to[1]}}],
               "attachments": [{"@odata.type": "#microsoft.graph.fileAttachment", "name": name,
                                "contentType": "application/pdf", "contentBytes": base64.b64encode(data).decode()}
                               for name, data in attachments]}
    headers = {"Authorization": f"Bearer {token}"}
    try:  # 202 Accepted with an empty body
        http.request("POST", GRAPH + "/me/sendMail", headers=headers,
                     json_body={"message": message, "saveToSentItems": True})
    except HttpError as exc:
        hint = " (Mail.Send not granted, or the login predates it)" if exc.status == 403 else ""
        raise OutreachError(f"Outlook sendMail to {to[1]}: HTTP {exc.status}{hint}") from None
