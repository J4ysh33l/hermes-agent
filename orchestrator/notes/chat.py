"""``/notes`` in Telegram. Read by script, no model: the meeting is named by words from its subject.

/notes list                                  meetings of the last 7 days and what was made
/notes product sync summary tasks prd        queue them (Gemini); add ``claude`` for Claude
/notes onboarding doc client follow-up email the document you describe (everything after ``doc``)
/notes last transcript                       the transcript file of the latest meeting
/notes product sync skip                     nothing needed (stops the question showing in the recap)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from orchestrator.brief.store import default_state_dir

from .store import KINDS, Store, label, status_line
from .work import IST, ref

HELP = """**/notes** — Smriti: summaries and documents from your Teams meetings (recorded + transcribed)
/notes list — your meetings of the last 7 days and what was made for each
/notes product sync summary tasks prd — what to make; name the meeting by words from its subject, or last
/notes onboarding doc client follow-up email — any document: everything after doc says what
/notes last transcript — the transcript file · /notes product sync skip — nothing needed
Add claude to have Claude write it (through your handoff repo); Gemini is the default. Hindi is written
in Latin script. After each check (10, 12, 14, 16, 18 and the 20:00 recap) you are asked about meetings
that ended. Work starts within 15 minutes and arrives here; nothing you ask for is dropped. /menu — all your commands"""

MODELS = ("gemini", "claude")
WORDS = {*KINDS, "skip", *MODELS}


@dataclass(frozen=True)
class Ask:
    meeting: str  # words naming the meeting
    kinds: tuple[str, ...]
    what: str  # the document asked for after ``doc``
    model: str
    skip: bool


def parse(raw: str) -> Ask | None:
    words = raw.split()
    first = next((i for i, w in enumerate(words) if w.lower() in WORDS), None)
    if first is None or first == 0:
        return None
    rest = words[first:]
    model = next((w.lower() for w in rest if w.lower() in MODELS), "gemini")
    kinds, what = [], ""
    for i, word in enumerate(rest):
        low = word.lower()
        if low == "doc":
            what = " ".join(w for w in rest[i + 1:] if w.lower() not in MODELS)
            kinds.append("doc")
            break
        if low in KINDS:
            kinds.append(low)
    return Ask(" ".join(words[:first]), tuple(dict.fromkeys(kinds)), what, model,
               any(w.lower() == "skip" for w in rest))


def listing(store: Store, now: datetime) -> str:
    rows = store.recent(now)
    if not rows:
        return "No Teams meetings of yours in the last 7 days yet (checked at 10, 12, 14, 16, 18 and 20:00)."
    lines = ["📋 **Meetings, last 7 days**"]
    lines += [f"· {label(m)} — {status_line(m)}" for _, m in rows]
    lines.append(f"/notes {ref(rows[0][1]['subject'])} summary tasks prd · /notes last transcript")
    return "\n".join(lines)


def handle(raw: str, home: Path | None = None, now: datetime | None = None) -> str:
    text = (raw or "").strip()
    if not text or text.lower() in {"help", "-help", "--help", "-h", "?"}:
        return HELP
    home = home or default_state_dir().parent
    now = now or datetime.now(IST)
    store = Store(home)
    if text.lower() == "list":
        return listing(store, now)
    ask = parse(text)
    if ask is None or not (ask.kinds or ask.skip):
        return "Say what to make, e.g. /notes product sync summary tasks prd (or /notes list)"
    if "doc" in ask.kinds and not ask.what:
        return "Say which document after doc, e.g. /notes onboarding doc client follow-up email"
    keys = store.find(ask.meeting, now)
    if not keys:
        return f"No meeting matches “{ask.meeting}”. /notes list shows the last 7 days."
    if len(keys) > 1:
        options = "\n".join(f"· {label(store.meetings[k])}" for k in keys[:6])
        return f"“{ask.meeting}” matches {len(keys)} meetings. Add a word from the one you mean:\n{options}"
    key = keys[0]
    m = store.meetings[key]
    if ask.skip:
        m["skipped"] = True
        store.save()
        return f"Noted: nothing needed for {label(m)}."
    m["skipped"] = False
    for kind in ask.kinds:
        store.request(key, kind, ask.model, ask.what if kind == "doc" else "")
    store.save()
    made = ", ".join(ask.what if k == "doc" else k for k in ask.kinds)
    who = "Claude (through your handoff repo)" if ask.model == "claude" else "Gemini"
    return (f"📝 {label(m)}: {made} by {who}. Work starts within 15 minutes; it arrives here when ready, "
            "and the 20:00 recap lists anything still waiting.")
