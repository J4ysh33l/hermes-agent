"""The HR inbox sweep: mail sent to the HR mailbox (``hr.mailbox``, e.g. hr@medochealth.in), sorted
by script into urgent, people, campus, applications and other. The sort reads no body and uses no model.

The HR mailbox is a Microsoft 365 group, so its mail lands in your own Outlook; your Outlook
login (Mail.Read) finds it with one search per sweep (``recipients:<mailbox>``, To or Cc).

Mails you sent yourself (Sent Items) are left out. Urgent and people mails are open items until
someone else at your domain answers in the same thread (a colleague's "Re:"/"Fw:" is itself an answer)
(found in Outlook, one lookup per open thread) or you mark them ``/hr inbox done``. The sweep
(10:00 and 17:00 by cron) sends nothing when there is no new HR mail, except the day's first
sweep, which reminds you of urgent mails still unanswered.

State: ``$HERMES_HOME/hr/inbox.json`` (0600): the mails seen (subject, sender, category; no body).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orchestrator.brief.net import Http, HttpError
from orchestrator.brief.sources import outlook
from orchestrator.outreach import graph
from orchestrator.outreach.errors import OutreachError

GRAPH = "https://graph.microsoft.com/v1.0"
FIRST_LOOKBACK = timedelta(days=14)
KEEP = timedelta(days=30)  # handled and counts-only mails are forgotten after this; open ones never
PAGES = 5  # 100 mails each
LIST_DAYS = 14


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    action: bool  # needs an answer: tracked until replied to or marked done


CATEGORIES = (
    Category("urgent", "🚨 Urgent", True),
    Category("people", "👥 People", True),
    Category("campus", "🎓 Campus", False),
    Category("applications", "📄 Applications", False),
    Category("other", "📢 Other", False),
)
BY_KEY = {c.key: c for c in CATEGORIES}

_W = re.IGNORECASE
URGENT = re.compile(r"\b(legal|statutory|court|summons|advocate|lawyer|police|labou?r (commissioner|court|office)|"
                    r"harass\w*|posh|complaint|grievance|final notice|pending (salary|dues|payment)|"
                    r"outstanding dues|unpaid|urgent)\b", _W)
URGENT_SENDERS = re.compile(r"\.(nic|gov)\.in$", _W)  # courts, labour department, EPFO
PEOPLE = re.compile(r"\b(resign\w*|relieving|experience (certificate|letter)|full (and|&) final|f&f|salary|"
                    r"payslips?|leaves?|notice period|appraisal|reimburse\w*|offer letter|joining|"
                    r"internship completion|certificate|attendance|pf|esic?|form 16|bonus|increment)\b", _W)
CAMPUS = re.compile(r"\b(campus|placements?|recruitment drive|graduating batch|training (and|&) placement|t&p)\b", _W)
APPLICATIONS = re.compile(r"\b(appl(y|ied|ying|ication)\w*|resume|cv|opportunit\w*|roles?|positions?|jobs?|"
                          r"internships?|developer|engineer\w*|analyst|designer|immediate joiner|fresher|"
                          r"candidate|hiring|portfolio|exploring|vacanc\w*|openings?)\b", _W)

REPLY = re.compile(r"\s*(re|fw|fwd)\s*:", _W)


def classify(subject: str, sender: str, own_domain: str) -> str:
    """The category key, by fixed rules in this order (a resignation about pending salary is urgent)."""
    domain = sender.rsplit("@", 1)[-1].lower()
    if URGENT.search(subject) or URGENT_SENDERS.search(domain):
        return "urgent"
    if PEOPLE.search(subject) or domain == own_domain:
        return "people"
    if CAMPUS.search(subject):
        return "campus"
    if APPLICATIONS.search(subject):
        return "applications"
    return "other"


# ---- state ----------------------------------------------------------------------------------------


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        self.items: dict[str, dict] = self.data.setdefault("items", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=1)
        tmp.replace(self.path)

    def prune(self, now: datetime) -> None:
        oldest = (now - KEEP).isoformat()
        for key in [k for k, it in self.items.items()
                    if it["received"] < oldest and not (BY_KEY[it["cat"]].action and not it.get("done"))]:
            del self.items[key]

    def open_items(self) -> list[tuple[str, dict]]:
        rows = [(k, it) for k, it in self.items.items() if BY_KEY[it["cat"]].action and not it.get("done")]
        return sorted(rows, key=lambda kv: (kv[1]["cat"] != "urgent", kv[1]["received"]))


# ---- Outlook --------------------------------------------------------------------------------------


def _get(http: Http, token: str, url: str, params: dict | None = None) -> dict:
    try:
        return http.request("GET", url, params=params, headers={"Authorization": f"Bearer {token}"}).json()
    except HttpError as exc:
        raise OutreachError(f"Outlook (HR inbox): HTTP {exc.status}") from None


def fetch(http: Http, token: str, mailbox: str, since: datetime) -> list[dict]:
    """Mails to or cc the HR mailbox received on or after ``since``'s day (Outlook search is by day)."""
    params: dict | None = {"$search": f'"recipients:{mailbox} AND received>={since:%Y-%m-%d}"', "$top": 100,
                           "$select": "id,subject,from,receivedDateTime,conversationId,webLink,parentFolderId"}
    url, rows = GRAPH + "/me/messages", []
    for _ in range(PAGES):
        page = _get(http, token, url, params)
        rows += page.get("value") or []
        url, params = page.get("@odata.nextLink"), None
        if not url:
            break
    return rows


def sent_folder(http: Http, token: str, store: Store) -> str:
    """Your Sent Items folder id (asked once, then kept)."""
    if not store.data.get("sent_folder"):
        store.data["sent_folder"] = _get(http, token, GRAPH + "/me/mailFolders/sentitems", {"$select": "id"})["id"]
    return store.data["sent_folder"]


def answered(http: Http, token: str, item: dict, own_domain: str) -> bool:
    """True when someone else at ``own_domain`` (you, HR) wrote in the thread after this mail arrived;
    the sender's own follow-up does not count."""
    found = _get(http, token, GRAPH + "/me/messages",
                 {"$filter": f"conversationId eq '{item['conv']}'", "$select": "from,receivedDateTime", "$top": 50})
    for msg in found.get("value") or []:
        sender = ((msg.get("from") or {}).get("emailAddress") or {}).get("address", "").lower()
        if sender.endswith("@" + own_domain) and sender != item["from"].lower() \
                and msg.get("receivedDateTime", "")[:19] > item["received"]:
            return True
    return False


# ---- the sweep ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Sweep:
    new: list[tuple[str, dict]]
    open: list[tuple[str, dict]]
    replied: int


def sweep(http: Http, secrets, store: Store, mailbox: str, now: datetime) -> Sweep:
    token = graph.access(http, secrets, outlook.SCOPES)
    own_domain = mailbox.rsplit("@", 1)[-1].lower()
    last = store.data.get("last_sweep")
    since = datetime.fromisoformat(last) - timedelta(days=1) if last else now - FIRST_LOOKBACK
    new, mine = [], sent_folder(http, token, store)
    for msg in fetch(http, token, mailbox, since):
        if msg["id"] in store.items or msg.get("parentFolderId") == mine:
            continue
        sender = (msg.get("from") or {}).get("emailAddress") or {}
        address = sender.get("address", "")
        if address.lower() == mailbox.lower():  # the HR mailbox's own sends
            continue
        item = {"cat": classify(msg.get("subject") or "", address, own_domain),
                "subject": (msg.get("subject") or "(no subject)")[:150], "name": sender.get("name") or address,
                "from": address, "received": msg["receivedDateTime"][:19], "conv": msg.get("conversationId", ""),
                "link": msg.get("webLink", "")}
        if address.lower().endswith("@" + own_domain) and REPLY.match(item["subject"]):
            item["done"] = "internal"  # a colleague answering or forwarding in an HR thread
        store.items[msg["id"]] = item
        new.append((msg["id"], item))
    replied = 0
    for key, item in store.open_items():
        if item["conv"] and answered(http, token, item, own_domain):
            store.items[key]["done"] = "replied"
            replied += 1
    store.data["last_sweep"] = now.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    store.prune(now.astimezone(UTC).replace(tzinfo=None))
    return Sweep(sorted(new, key=lambda kv: kv[1]["received"]), store.open_items(), replied)


# ---- text -----------------------------------------------------------------------------------------


def age(received: str, now: datetime) -> str:
    days = (now.astimezone(UTC).replace(tzinfo=None) - datetime.fromisoformat(received)).days
    return "today" if days < 1 else f"{days}d"


def open_lines(store: Store, now: datetime) -> list[str]:
    rows = store.open_items()
    store.data["listing"] = [k for k, _ in rows]
    return [f"{n}. {BY_KEY[it['cat']].label[0]} {it['name']} — {it['subject']} ({age(it['received'], now)}, no reply)"
            for n, (_, it) in enumerate(rows, 1)]


def counts(items: list[dict]) -> str:
    parts = [f"{c.label} {n}" for c in CATEGORIES if (n := sum(it["cat"] == c.key for it in items))]
    return " · ".join(parts) or "nothing"


def digest(result: Sweep, store: Store, now: datetime, *, always: bool, remind: bool) -> str:
    """The Telegram text: new mail by category, then open urgent/people mails. "" = nothing to say."""
    urgent_open = [it for _, it in result.open if it["cat"] == "urgent"]
    if not (always or result.new or (remind and urgent_open)):
        return ""
    lines = [f"📥 **HR inbox** — {len(result.new)} new" + (f" · {result.replied} answered" if result.replied else "")]
    if result.new:
        lines.append(counts([it for _, it in result.new]))
    if result.open:
        lines += ["", f"**Waiting for a reply ({len(result.open)})**", *open_lines(store, now)]
        lines.append("/hr inbox done 1 — handled outside the thread")
    elif always:
        lines.append("Nothing waiting for a reply.")
    lines.append("/hr inbox list applications · campus · people · urgent · other")
    return "\n".join(lines)


def listing(store: Store, key: str, now: datetime) -> str:
    oldest = (now.astimezone(UTC).replace(tzinfo=None) - timedelta(days=LIST_DAYS)).isoformat()
    rows = sorted((it for it in store.items.values() if it["cat"] == key and it["received"] >= oldest),
                  key=lambda it: it["received"], reverse=True)
    head = f"**{BY_KEY[key].label}** — last {LIST_DAYS} days: {len(rows)}"
    body = [f"· {it['received'][5:10]} {it['name']} — {it['subject']}" + (" ✓" if it.get("done") else "")
            for it in rows[:30]]
    return "\n".join([head, *body, *(["…and more in Outlook"] if len(rows) > 30 else [])])
