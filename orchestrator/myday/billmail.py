"""Bills found in your personal Gmail: card statements and bill mails, read by script (no model).

Once a day, with the morning card, every Gmail account the brief has logged in is searched for
recent mail with "statement" or "bill" in the subject. Each new mail is read once: when its text
names a total amount due above zero and a due date still ahead, it becomes a To Do task in your
Bills list ("💳 Pay …", due that day, phone reminder ``bill_remind_days[0]`` days before). From
there it is an ordinary bill: Telegram reminders, ``/bills paid``, points on time or late
(``bills.statements``).

Added once: a mail is marked read (by Gmail message id) only after its task exists in To Do, so a
To Do failure retries it the next day; and a bill is keyed by due date + amount, so the bank's mail
and CRED's about the same bill make one task.

The mail text never leaves the host: nothing is sent to a model, only the task title to To Do.
"""

from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass
from datetime import date, timedelta

from orchestrator.brief.items import SourceError
from orchestrator.brief.net import HttpError
from orchestrator.brief.sources import gmail

from . import bills
from .session import Session

LOOKBACK_DAYS = 40  # a monthly statement is due 15-25 days after it is mailed
QUERY = f"newer_than:{LOOKBACK_DAYS}d subject:(statement OR bill)"
MAX_AHEAD = timedelta(days=60)  # a due date further out is a misread

MONTHS = {m: n for n, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
DATES = (  # (pattern, groups → (day, month, year)); numeric dates are Indian: day first
    (re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b"), lambda g: (g[0], g[1], g[2])),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), lambda g: (g[2], g[1], g[0])),
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s-]+{_MON}[\s,-]+(\d{{4}})\b", re.IGNORECASE), lambda g: (g[0], g[1], g[2])),
    (re.compile(rf"\b{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.IGNORECASE), lambda g: (g[1], g[0], g[2])),
)
AMOUNT_LABELS = ("total amount due", "total due", "amount due", "amount payable", "total outstanding",
                 "bill amount")
DUE_LABEL = re.compile(r"due\s+(?:date|on|by)|pay(?:ment)?\s+by", re.IGNORECASE)
AMOUNT = re.compile(r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d{1,2})?)", re.IGNORECASE)
NEAR = 120  # characters after a label to look for its value
NAMES = (  # subject → the bill's name
    re.compile(r"your\s+(.+?)\s+credit\s+card\s+statement", re.IGNORECASE),
    re.compile(r"bill\s+for\s+your\s+(.+?)\s+is\s+here", re.IGNORECASE),
    re.compile(r"your\s+(.+?)\s+(?:statement|bill)\b", re.IGNORECASE),
)
GENERIC = {"credit card", "card"}  # CRED's "Your credit card bill is due …": the sender names it
BILLER = re.compile(r"biller\s+name\s*:\s*([A-Za-z][\w&.-]*)", re.IGNORECASE)


@dataclass(frozen=True)
class Found:
    name: str
    amount: float
    due: date


def _date(day: str, month: str, year: str) -> date | None:
    number = int(month) if month.isdigit() else MONTHS[month[:3].lower()]
    try:
        return date(int(year), number, int(day))
    except ValueError:
        return None


def due_date(text: str) -> date | None:
    """The first date shortly after a "due date" / "due on" / "pay by" label."""
    for label in DUE_LABEL.finditer(text):
        window = text[label.end():label.end() + NEAR]
        hits = [(m.start(), parts(m.groups())) for pattern, parts in DATES if (m := pattern.search(window))]
        for _, groups in sorted(hits):
            if found := _date(*groups):
                return found
    return None


def amount_due(text: str) -> float | None:
    """The number after the first amount label found (``total amount due`` before ``amount due``,
    so "minimum amount due" is never taken for the total)."""
    lower = text.lower()
    for label in AMOUNT_LABELS:
        start = lower.find(label)
        while start >= 0:
            if m := AMOUNT.search(text, start + len(label), start + len(label) + NEAR):
                return float(m.group(1).replace(",", ""))
            start = lower.find(label, start + 1)
    return None


def bill_name(subject: str, sender: str, text: str = "") -> str:
    if m := BILLER.search(text):  # utility bills: "Biller Name: CITYPOWER City Power …"
        return f"{m.group(1)} bill"
    for pattern in NAMES:
        if (m := pattern.search(subject)) and m.group(1).strip(" :-").lower() not in GENERIC:
            name = m.group(1).strip(" :-")
            card = "credit card" in subject.lower() and not re.search(r"\bcard\b", name, re.IGNORECASE)
            return f"{name} card" if card else name
    display = sender.split("<")[0].strip().strip('"\'')
    return display or sender.split("@")[-1].strip("> ")


def parse(subject: str, sender: str, text: str, today: date) -> Found | None:
    """A bill to pay, or None (nothing due, already past, or not a bill)."""
    text = re.sub(r"\s+", " ", text)
    amount, due = amount_due(text), due_date(text) or due_date(subject)
    if not amount or due is None or not today <= due <= today + MAX_AHEAD:
        return None
    return Found(bill_name(subject, sender, text), amount, due)


def message_text(payload: dict) -> str:
    """Every text part of a Gmail message, HTML reduced to its words."""
    out = []
    body = (payload.get("body") or {}).get("data")
    if body:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8", "replace")
        if "html" in (payload.get("mimeType") or ""):
            raw = re.sub(r"(?is)<(style|script)\b.*?</\1>", " ", raw)
            raw = html.unescape(re.sub(r"<[^>]+>", " ", raw))
        out.append(raw)
    out += [message_text(part) for part in payload.get("parts") or []]
    return "\n".join(t for t in out if t)


# ---- the daily scan -------------------------------------------------------------------------------


def _seen(session: Session) -> dict[str, str]:
    """Gmail message ids already read → the day they were read (pruned after LOOKBACK_DAYS)."""
    seen = session.state.data.setdefault("billmail_seen", {})
    oldest = (session.today - timedelta(days=LOOKBACK_DAYS + 1)).isoformat()
    for key in [k for k, day in seen.items() if day < oldest]:
        del seen[key]
    return seen


def _account(session: Session, account: gmail.Account, seen: dict[str, str]) -> list[tuple[str, Found, str]]:
    """New bills in one account as (message id, bill, subject). Mails that are not bills are marked
    read here; bills only once their task is in To Do (``scan``)."""
    secrets, http = session.secrets, session.http
    token = gmail.access_token(http, secrets.get("GOOGLE_CLIENT_ID"), secrets.get("GOOGLE_CLIENT_SECRET"),
                               secrets.token(account.token_name).get("refresh_token", ""), account.label)
    auth = {"Authorization": f"Bearer {token}"}
    listing = http.request("GET", gmail.API, params={"q": QUERY, "maxResults": 50}, headers=auth).json()
    found = []
    for ref in listing.get("messages") or []:
        if ref["id"] in seen:
            continue
        msg = http.request("GET", f"{gmail.API}/{ref['id']}", params={"format": "full"}, headers=auth).json()
        headers = {h["name"].lower(): h["value"] for h in (msg.get("payload") or {}).get("headers") or []}
        subject = headers.get("subject", "")
        bill = parse(subject, headers.get("from", ""), message_text(msg.get("payload") or {}), session.today)
        if bill:
            found.append((ref["id"], bill, subject))
        else:
            seen[ref["id"]] = session.today.isoformat()
    return found


def scan(session: Session) -> list[str]:
    """Telegram lines for bills newly found in Gmail (each also added to To Do). Once a day."""
    accounts = gmail.accounts(session.secrets.token_dir)
    if not accounts or not session.state.once(f"billmail:{session.today.isoformat()}"):
        return []
    seen, lines = _seen(session), []
    for account in accounts:
        try:
            found = _account(session, account, seen)
        except (SourceError, HttpError) as exc:
            lines.append(f"⚠️ Bills from Gmail ({account.label}): {exc}")
            continue
        for msg_id, bill, subject in found:
            if line := bills.add_statement(session, bill, subject):  # raises if To Do fails: mail stays unread
                lines.append(line)
            seen[msg_id] = session.today.isoformat()
    return lines
