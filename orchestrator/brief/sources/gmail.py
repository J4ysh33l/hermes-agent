"""Gmail via the Gmail API (read-only scope), one or more accounts.

Each account has its own refresh token in ``tokens/google-<label>.json`` (``tokens/google.json``
is the account labelled ``main``), written by ``python -m orchestrator.brief auth google
[--account <label>]``. Client id/secret in .env are shared by every account.

A run costs three HTTP requests per account, however many mails there are: a token refresh,
one ``messages.list`` (ids only) and one batch request per 25 mails.
"""

from __future__ import annotations

import json
import re
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from ..items import AuthError, Item, SourceError
from ..net import Http, HttpError
from ..settings import Settings

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
PROFILE = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
BATCH = "https://www.googleapis.com/batch/gmail/v1"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
HEADERS = ("From", "Subject", "List-Unsubscribe", "List-Id", "Precedence")
BATCH_SIZE = 25  # Google allows 100 and recommends ≤50; 50 tripped its per-user concurrency limit live
RETRIES = 3
MAIN = "main"


@dataclass(frozen=True)
class Account:
    label: str
    token_name: str  # file stem under tokens/


def accounts(token_dir: Path) -> list[Account]:
    """Every Gmail account that has logged in, ``main`` first."""
    found = [Account(MAIN, "google")] if (token_dir / "google.json").is_file() else []
    found += [Account(p.stem.removeprefix("google-"), p.stem) for p in sorted(token_dir.glob("google-*.json"))]
    return found


def token_name(label: str) -> str:
    return "google" if label == MAIN else f"google-{label}"


def access_token(http: Http, client_id: str, client_secret: str, refresh_token: str, label: str = MAIN) -> str:
    login = "python -m orchestrator.brief auth google" + ("" if label == MAIN else f" --account {label}")
    if not (client_id and client_secret and refresh_token):
        raise SourceError(f"not set up (run: {login})", kind="skipped")
    form = {"client_id": client_id, "client_secret": client_secret,
            "refresh_token": refresh_token, "grant_type": "refresh_token"}
    try:
        return http.request("POST", TOKEN_URL, form=form).json()["access_token"]
    except HttpError as exc:
        if exc.status in (400, 401) and ("invalid_grant" in exc.detail or "unauthorized" in exc.detail.lower()):
            raise AuthError(f"Gmail ({label}) login expired: run `{login}`") from None
        raise


def address(http: Http, token: str) -> str:
    return http.request("GET", PROFILE, headers={"Authorization": f"Bearer {token}"}).json().get("emailAddress", "")


def _item(msg: dict, label: str, email: str) -> Item:
    headers = {h["name"].lower(): h["value"] for h in (msg.get("payload") or {}).get("headers") or []}
    newsletter = bool(headers.get("list-unsubscribe") or headers.get("list-id")
                      or headers.get("precedence", "").lower() in ("bulk", "list"))
    account = f"?authuser={urllib.parse.quote(email)}" if email else ""
    return Item(uid=f"gmail:{msg['id']}", source="gmail", title=headers.get("subject", "(no subject)")[:200],
                sender=headers.get("from", ""), where=email or ("Gmail" if label == MAIN else f"Gmail ({label})"),
                snippet=(msg.get("snippet") or "")[:400], ts=int(msg.get("internalDate", 0)) / 1000,
                newsletter=newsletter, url=f"https://mail.google.com/mail/u/{account}#all/{msg['id']}")


def _batch_body(ids: list[str], boundary: str) -> bytes:
    query = urllib.parse.urlencode({"format": "metadata", "metadataHeaders": list(HEADERS)}, doseq=True)
    parts = [f"--{boundary}\r\nContent-Type: application/http\r\nContent-ID: <{i}>\r\n\r\n"
             f"GET /gmail/v1/users/me/messages/{i}?{query}\r\n\r\n" for i in ids]
    return ("".join(parts) + f"--{boundary}--\r\n").encode()


def parse_batch(body: str) -> tuple[list[dict], list[str], str]:
    """multipart/mixed answer → (messages, ids that failed, first error). The boundary is the
    body's first line; each part's Content-ID is ``response-<message id>``."""
    boundary = body.lstrip().split("\n", 1)[0].strip()
    messages, failed, first_error = [], [], ""
    for part in body.split(boundary)[1:]:
        status = re.search(r"HTTP/[\d.]+ (\d{3})", part)
        start = part.find("{")
        if not status or start < 0:
            continue
        payload = json.loads(part[start:part.rfind("}") + 1])
        if status.group(1) == "200":
            messages.append(payload)
            continue
        cid = re.search(r"Content-ID: <response-([^>]+)>", part)
        failed.append(cid.group(1) if cid else "")
        first_error = first_error or f"{status.group(1)} {(payload.get('error') or {}).get('message', '')}".strip()
    return messages, failed, first_error


def _get_all(http: Http, auth: dict[str, str], ids: list[str], label: str) -> list[dict]:
    """Batches of BATCH_SIZE. Gmail answers single parts with 429 ("too many concurrent requests
    for user") when a burst is too fast: those ids are retried, then the account fails whole so
    its watermark stays put and nothing is skipped."""
    found: list[dict] = []
    pending, error = ids, ""
    for attempt in range(RETRIES + 1):
        if attempt:
            time.sleep(2 ** attempt)
        retry: list[str] = []
        for start in range(0, len(pending), BATCH_SIZE):
            boundary = "batch_" + secrets.token_hex(8)
            reply = http.request("POST", BATCH, data=_batch_body(pending[start:start + BATCH_SIZE], boundary),
                                 headers={**auth, "Content-Type": f"multipart/mixed; boundary={boundary}"})
            messages, failed, first_error = parse_batch(reply.text())
            found += messages
            retry += failed
            error = first_error or error
        if not retry:
            return found
        pending = retry
    raise SourceError(f"Gmail ({label}): {len(pending)} of {len(ids)} mails could not be read ({error})")


def fetch(http: Http, token: str, settings: Settings, since: float, label: str = MAIN, email: str = "") -> list[Item]:
    auth = {"Authorization": f"Bearer {token}"}
    query = f"after:{int(since)} -category:promotions -category:social -category:forums"
    listing = http.request("GET", API, params={"q": query, "maxResults": settings.mail_max}, headers=auth).json()
    ids = [ref["id"] for ref in listing.get("messages") or []]
    return [i for i in (_item(m, label, email) for m in _get_all(http, auth, ids, label)) if i.ts > since]
