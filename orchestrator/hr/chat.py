"""``/hr`` in Telegram: HR jobs, each under its own word: ``payslip``, ``interview``, ``inbox``.

/hr payslip <sheet> <from> <to> <pay date> — make the slips (what Hermes' agent runs with your sheet)
/hr payslip check · show · test · yes · no · skip — check a sheet, review, sample to you, send, cancel,
  or leave out the rows with problems. No model ever sees pay; ``show`` is a command, not a chat turn.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator import expiry
from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http, HttpError, UrllibHttp
from orchestrator.brief.sources import outlook
from orchestrator.brief.store import default_state_dir
from orchestrator.outreach import graph
from orchestrator.outreach.build import fill
from orchestrator.outreach.errors import OutreachError
from orchestrator.outreach.plan import picks

from orchestrator.notes.errors import NotesError
from orchestrator.notes.telegram import Telegram
from orchestrator.recap.parts import pending_files

from . import duties, inbox, intake, interview, offer, payslips, reply, request, settings, store
from .docfill import TemplateError
from .pdf import PdfError, convert
from .payroll import Period
from .payslips import Paths, rupees

PAYSLIP_HELP = """**/hr payslip** — payslips from your salary sheet, emailed from your Outlook (no AI model touches pay)
/hr payslip November 02/12/2026 — then paste the table (copied from Sheets/Excel) on the next lines
/hr payslip <sheet file> November 02/12/2026 — or send the sheet file (.xlsx/.csv)
Month: November · Nov 2026 · 11/2026, or two dates 01/11/2026 30/11/2026. Then the pay date.
Columns: Employee Name, Position, Email, DOJ, Compensation, Basic (optional: HRA, LOP Days,
Reimbursement, Other Deductions; HRA defaults to Compensation − Basic). Nothing is sent yet.
/hr payslip check November — then the table: only checks, makes nothing
/hr payslip show — slips waiting: name, email, net pay
/hr payslip test — 2 sample slips emailed to you · test all — every slip, to you only
/hr payslip yes — email everyone their own slip · yes 1-10 — only those
/hr payslip no — cancel
/hr payslip skip — make the good rows' slips, leave the employees with problems out
Paste a table only after /hr payslip: as a plain chat message it would reach the AI model.
/menu — all your commands"""

INTERVIEW_HELP = """**/hr interview** — one Teams link for a block of interviews; each candidate is invited to their slot
/hr interview, then one line each (or ; between lines):
Date: 25/11/2026
Panel: rishabh@medochealth.in, nidhi@medochealth.in   (optional: the interviewers)
Asha Verma, Backend Engineer, 11:00, 11:30, asha@gmail.com
Rohan Das, Data Analyst, 11:45, 12:15, rohan@gmail.com
End is optional (Start + 30 min). Or paste a table with columns Name, Position, Email, Date, Start, End.
→ a preview; nothing is sent. One day per batch; slots can't overlap (one link). No AI model is used.
/hr interview yes — create the Teams link, invite each candidate to their own slot and the panel to all
/hr interview show · /hr interview no
/menu — all your commands"""

HR_HELP = """**/hr** — HR jobs from your files, sent from your Outlook only after you approve
/hr list — everything pending in HR: mail waiting for a reply, applications not answered, approvals
/hr payslip — monthly payslips from the salary sheet (/hr payslip help for every step)
/hr interview — one Teams link, each candidate invited to their own slot (/hr interview help)
/hr inbox — mail to the HR mailbox sorted: urgent, people, campus, applications (/hr inbox help)
/hr reply — answer HR mail in its thread: Gemini drafts, or a template with no model (/hr reply help)
/hr offer — offer letters (internship, full-time, consultant) from your Word templates (/hr offer help)
/hr duties — the duties kept per position for offer letters (/hr duties help)
/hr sync — templates and duties kept in your private repo (/hr sync help)
/menu — all your commands"""

REPLY_HELP = """**/hr reply** — answer HR mail in its own thread, From the HR mailbox, only after your yes
/hr reply 2 — Gemini drafts a reply to mail 2 of the waiting list (/hr list or /hr inbox show)
/hr reply 2 say we'll send the relieving letter by Friday — with your instruction
/hr reply 2 ack Backend Engineer — a template, no model: ack · reject · docs · letter · leave · salary
  (the words after it fill the role or the date: "letter 30 Nov" → "…by 30 Nov")
/hr reply applications ack — acknowledge every unanswered application of the last 14 days (preview first)
/hr reply show · yes · no — see the draft, send it, drop it
/hr reply again shorter, mention the portal — Gemini redrafts with your change
/hr reply edit <your text> — use your own words instead (blank lines split paragraphs)
Before Gemini sees a mail, names, emails, phone numbers, links, amounts and ID numbers are swapped
for placeholders; the draft is refused if any comes back changed or invented. "Hi <name>," and the
sign-off are added by the script. /menu — all your commands"""

INBOX_HELP = """**/hr inbox** — mail to the HR mailbox, sorted by fixed rules (no AI model; /hr reply drafts answers)
/hr inbox show — new HR mail by kind, and every urgent or people mail still waiting for a reply
/hr inbox list applications — the last 14 days of one kind (urgent · people · campus · applications · other)
/hr inbox done 2 — mark a waiting mail handled (one answered in its thread clears on its own)
Swept at 10:00 and 17:00 (cron); it messages you only when there is new HR mail, and the first sweep
of the day also reminds you of urgent mail still unanswered. /menu — all your commands"""

OFFER_HELP = """**/hr offer** — offer letters from your template; emailed only after your yes
/hr offer internship · /hr offer fte · /hr offer consultant, then the details:
Name: Asha Verma
Position: Marketing Intern
Month: June - July     (or Start: 01/12/2026 and Tenure: 3 months; no year = the next June)
Stipend: 15000         (or Unpaid; Salary: / Fee: a month; or CTC: 12 LPA a year)
Email: asha@gmail.com  (optional; needed to send it)
Several people: one Name: line starts each; a line written once (e.g. Stipend: Unpaid at the
end) is for everyone. Any other line fills the bracket of the same name, e.g. Location: Mohali.
Or one line: /hr offer internship Asha Verma, Marketing Intern, 01/12/2026, 3, 15000, asha@gmail.com
A message in another shape is read by Gemma (then Gemini) and checked the same way; that sends
your message as it is to Google. Missing values are asked for, never guessed.
→ the letters (PDF + Word) come to you here to check; nothing is sent.
Duties: a position seen before uses its saved duties (no model); a new one gets one Gemma call
(only the position and the kind of offer are sent), saved for next time. /hr duties to see or set them.
/hr offer show · test · yes · no — see them again, the PDFs to you only, the PDF to each person
From the HR mailbox, drop them
Unpaid: the pay table goes and hr.unpaid_line says so. A Word signature line with your signature
over it is redrawn so the PDF shows the whole signature.
Templates in $HERMES_HOME/hr/templates/: offer_internship.docx, offer_fte.docx, offer_consultant.docx,
with [Name] [Position] [Date] [Start date] [End date] [duration spelled] [duration number] [Monthly]
[Annual] and a [duties and responsibilities] bullet. /hr sync pull fetches them from your private repo.
/menu — all your commands"""

SYNC_HELP = """**/hr sync** — your templates and saved duties, kept in your private GitHub repo
/hr sync pull — fetch hr/templates/*.docx and hr/duties.json into $HERMES_HOME/hr/ (new machine)
/hr sync push — send yours up (after you change a template here)
The repo: hr.store_repo, else notes.handoff_repo (private!); token GITHUB_HANDOFF_TOKEN.
New duties go up by themselves after each offer."""

DUTIES_HELP = """**/hr duties** — duties and responsibilities kept per position, used by /hr offer
/hr duties list — every saved position
/hr duties Marketing Intern — its duties
/hr duties Marketing Intern = Assist with…; Prepare…; Research… — set them yourself (no model)
/hr duties forget Marketing Intern — the next offer for it asks the model again
/menu — all your commands"""

TZ = ZoneInfo("Asia/Kolkata")
TEST_SAMPLES = 2


class Context:
    def __init__(self, state_dir: Path, http: Http | None = None, now: float | None = None) -> None:
        self.state_dir = state_dir
        self.http = http or UrllibHttp()
        self.now = time.time() if now is None else now
        self.settings = settings.load(state_dir)
        self.paths = Paths(state_dir.parent / "hr")
        self.secrets = Secrets(state_dir.parent / ".env", state_dir / "tokens")

    def plan(self) -> dict | None:
        if not self.paths.pending.is_file():
            return None
        plan = json.loads(self.paths.pending.read_text(encoding="utf-8"))
        if self.now - plan["created"] > self.settings.preview_minutes * 60:
            expiry.expire(self.paths.pending)  # the evening recap reminds you until you redo it or say no
            return None
        return plan

    def log(self, to: str, file: str, ok: bool, note: str = "", test: bool = False) -> None:
        row = {"ts": datetime.fromtimestamp(self.now, TZ).isoformat(timespec="seconds"), "to": to,
               "file": Path(file).name, "test": test, "ok": ok, "note": note[:200]}
        fd = os.open(self.paths.sent, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")


def _sheet(ctx: Context, req: request.PayslipRequest) -> Path:
    """The file you sent, or the pasted table saved privately (0600, $HERMES_HOME/hr/inbox/)."""
    if req.sheet is not None:
        return req.sheet
    inbox = payslips.private_dir(ctx.paths.home / "inbox")
    for old in inbox.glob("pasted-*.tsv"):  # salary data: only the latest paste is kept
        old.unlink()
    path = inbox / f"pasted-{int(ctx.now)}.tsv"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(req.table + "\n")
    return path


def run_payslips(ctx: Context, text: str) -> str:
    try:
        req = request.parse(text, datetime.fromtimestamp(ctx.now, TZ).date(), need_pay=True)
    except ValueError as exc:
        return f"{exc}\n\n/hr payslip help for the formats"
    period = Period(req.start, req.end, req.pay_date)
    return payslips.prepare(_sheet(ctx, req), period, ctx.settings, ctx.paths, ctx.now)


def _show(ctx: Context, _arg: str) -> str:
    plan = ctx.plan()
    if plan is None:
        return "No payslips are waiting."
    total = sum(Decimal(i["net"]) for i in plan["items"])
    lines = [f"**Payslips, {plan['month']}** — {len(plan['items'])} people, total net {rupees(total)}", ""]
    lines += [f"{n}. {i['name']} — {i['email']} — {rupees(Decimal(i['net']))}" for n, i in enumerate(plan["items"], 1)]
    lines += [""] + plan.get("notes", []) + ["", "/hr payslip test · yes · yes 1-10 · no"]
    return "\n".join(lines)


def _mail(ctx: Context, token: str, plan: dict, item: dict, to: tuple[str, str], test: bool) -> str:
    s = ctx.settings
    sender = s.sender_name or "HR"
    subject = ("[TEST for " + item["email"] + "] " if test else "") + fill(s.mail_subject, month=plan["month"])
    body = fill(s.mail_body, first=item["first"], name=item["name"], month=plan["month"], sender=sender)
    try:
        graph.send_mail(ctx.http, token, to=to, subject=subject, body_html=body,
                        attachments=((Path(item["file"]).name, Path(item["file"]).read_bytes()),),
                        sender=s.mailbox)
    except (OutreachError, HttpError, OSError) as exc:
        ctx.log(to[1], item["file"], False, str(exc), test)
        return f"{item['name']}: {exc}"
    ctx.log(to[1], item["file"], True, test=test)
    return ""


def _token(ctx: Context) -> str:
    return graph.access(ctx.http, ctx.secrets, outlook.SEND_SCOPES)


def _test(ctx: Context, arg: str) -> str:
    plan = ctx.plan()
    if plan is None:
        return "No payslips are waiting."
    token = _token(ctx)
    me = graph.me(ctx.http, token)
    items = plan["items"] if arg.strip().lower() == "all" else plan["items"][:TEST_SAMPLES]
    failed = [f for i in items if (f := _mail(ctx, token, plan, i, ("", me), test=True))]
    sender = f" from {ctx.settings.mailbox}" if ctx.settings.mailbox else ""
    return "\n".join([f"Sent {len(items) - len(failed)} test slip(s){sender} to {me} only. Check them, then /hr payslip yes.",
                      *failed])


def _yes(ctx: Context, arg: str) -> str:
    plan = ctx.plan()
    if plan is None:
        return f"No payslips are waiting (a batch expires after {ctx.settings.preview_minutes} min)."
    chosen = picks(arg, len(plan["items"]))
    if chosen is None:
        return f"Pick numbers between 1 and {len(plan['items'])}, e.g. /hr payslip yes 1-10"
    token = _token(ctx)
    ctx.paths.pending.unlink()
    failed = [f for n in chosen
              if (f := _mail(ctx, token, plan, (i := plan["items"][n]), (i["name"], i["email"]), test=False))]
    out = [f"✅ Emailed {len(chosen) - len(failed)} of {len(chosen)} payslips for {plan['month']}."]
    return "\n".join(out + (["❌ Not sent:"] + failed if failed else []))


def _no(ctx: Context, _arg: str) -> str:
    if ctx.paths.pending.is_file():
        ctx.paths.pending.unlink()
        return "Cancelled. Nothing was emailed."
    dropped = expiry.clear(ctx.paths.pending) | expiry.clear(ctx.paths.blocked)
    return "Dropped the expired payslip run from the recap." if dropped else "Nothing was waiting."


def _check(ctx: Context, arg: str) -> str:
    try:
        req = request.parse(arg, datetime.fromtimestamp(ctx.now, TZ).date(), need_pay=False)
    except ValueError as exc:
        return f"{exc}\n\n/hr payslip help for the formats"
    period = Period(req.start, req.end, req.end)
    checked = payslips.check(_sheet(ctx, req), period, ctx.settings, ctx.paths)
    if checked.ready():
        return "\n".join([f"✅ The sheet is ready: {len(checked.batch.slips)} payslips for {period.month}.",
                          *checked.report()])
    tail = (["", f"{len(checked.batch.slips)} rows are fine. When you send it with the pay date, you can "
             f"leave the {len(checked.batch.left_out)} above out with /hr payslip skip."] if checked.can_leave_out() else [])
    return "\n".join(["The sheet is not ready yet. Fix all of this:", *checked.report(), *tail])


def _skip(ctx: Context, _arg: str) -> str:
    path = ctx.paths.blocked
    if not path.is_file():
        return "Nothing to skip. /hr payslip skip works right after a run that stopped only because of bad rows."
    held = json.loads(path.read_text(encoding="utf-8"))
    if ctx.now - held["created"] > ctx.settings.preview_minutes * 60:
        expiry.expire(path)
        return "That run is too old. Send the sheet again."
    period = Period(date.fromisoformat(held["start"]), date.fromisoformat(held["end"]),
                    date.fromisoformat(held["pay_date"]))
    return payslips.prepare(Path(held["sheet"]), period, ctx.settings, ctx.paths, ctx.now,
                            leave_out=tuple(held["left_out"]))


def _make(ctx: Context, arg: str) -> str:
    return run_payslips(ctx, arg) if arg.strip() else PAYSLIP_HELP


def agent_make(args: list[str], state_dir: Path | None = None) -> str:
    """The only entry Hermes' agent has: make slips from a sheet FILE (it never handles a pasted
    table, so pay never passes through its model). It can't reach show, test, yes or skip."""
    ctx = Context(state_dir or default_state_dir())
    if not args or not request.is_sheet(args[0]):
        return "Usage: hr_payslips.py <sheet path> <month> <pay date>, e.g. ~/nov.xlsx November 02/12/2026"
    return run_payslips(ctx, " ".join(args))


def _interview_path(ctx: Context) -> Path:
    return ctx.paths.home / "interview.json"


def _interview_saved(ctx: Context) -> dict | None:
    path = _interview_path(ctx)
    if not path.is_file():
        return None
    saved = json.loads(path.read_text(encoding="utf-8"))
    if ctx.now - saved["created"] > ctx.settings.preview_minutes * 60:
        expiry.expire(path)
        return None
    return saved


def _interview_make(ctx: Context, text: str) -> str:
    parsed = interview.parse(text, datetime.fromtimestamp(ctx.now, TZ), ctx.settings.max_interviews,
                             ctx.settings.interview_minutes)
    if parsed.problems:
        return "\n".join(["Nothing was saved. Fix all of this and send it again:",
                          *(f"• {p}" for p in parsed.problems), "", "/hr interview help for the format"])
    warnings = interview.busy_warnings(ctx.http, ctx.secrets, parsed)
    saved = interview.plan(parsed, warnings, ctx.now)
    payslips.save_private(_interview_path(ctx), saved)
    expiry.clear(_interview_path(ctx))
    return interview.preview(saved, ctx.settings.preview_minutes)


def _interview_show(ctx: Context, _arg: str) -> str:
    saved = _interview_saved(ctx)
    return interview.preview(saved, ctx.settings.preview_minutes) if saved else "No interviews are waiting."


def _interview_yes(ctx: Context, _arg: str) -> str:
    saved = _interview_saved(ctx)
    if saved is None:
        return f"No interviews are waiting (a plan expires after {ctx.settings.preview_minutes} min)."
    _interview_path(ctx).unlink()  # before sending: a second yes can never invite twice
    return interview.send(ctx.http, ctx.secrets, saved, ctx.settings,
                          lambda to, ok, note: ctx.log(to, "interview", ok, note))


def _interview_no(ctx: Context, _arg: str) -> str:
    path = _interview_path(ctx)
    if path.is_file():
        path.unlink()
        return "Cancelled. Nobody was invited."
    return "Dropped the expired interview plan from the recap." if expiry.clear(path) else "Nothing was waiting."


def _inbox_store(ctx: Context) -> inbox.Store:
    return inbox.Store(ctx.paths.home / "inbox.json")


def _inbox_sweep(ctx: Context, *, always: bool) -> str:
    if not ctx.settings.mailbox:
        return "Set hr.mailbox in brief.yaml (e.g. hr@medochealth.in) first: the sweep reads mail sent to it."
    store, now = _inbox_store(ctx), datetime.fromtimestamp(ctx.now, TZ)
    result = inbox.sweep(ctx.http, ctx.secrets, store, ctx.settings.mailbox, now)
    remind = store.data.get("reminded") != now.date().isoformat()
    text = inbox.digest(result, store, now, always=always, remind=remind)
    if text:
        store.data["reminded"] = now.date().isoformat()
    store.save()
    return text


def _inbox_list(ctx: Context, arg: str) -> str:
    key = arg.strip().lower()
    if key not in inbox.BY_KEY:
        return "Which kind? /hr inbox list " + " · ".join(inbox.BY_KEY)
    return inbox.listing(_inbox_store(ctx), key, datetime.fromtimestamp(ctx.now, TZ))


def _inbox_done(ctx: Context, arg: str) -> str:
    store = _inbox_store(ctx)
    shown = store.data.get("listing") or []
    chosen = picks(arg, len(shown)) if arg.strip() else None
    if chosen is None:
        return f"Give numbers from the last /hr inbox show (1 to {len(shown)}), e.g. /hr inbox done 2"
    keys = [shown[i] for i in chosen]
    names = []
    for key in keys:
        if key in store.items:
            store.items[key]["done"] = "marked"
            names.append(store.items[key]["subject"])
    store.save()
    return "✅ Handled: " + "; ".join(names) if names else "Nothing to mark. Show /hr inbox show again."


PAYSLIP = {"check": _check, "show": _show, "test": _test, "yes": _yes, "no": _no, "cancel": _no, "skip": _skip}
INTERVIEW = {"show": _interview_show, "yes": _interview_yes, "no": _interview_no, "cancel": _interview_no}
INBOX = {"show": lambda ctx, _a: _inbox_sweep(ctx, always=True),
         "sweep": lambda ctx, _a: _inbox_sweep(ctx, always=False),  # the cron's word: silent when nothing new
         "list": _inbox_list, "done": _inbox_done}
# ---- /hr reply ---------------------------------------------------------------------------------


def _reply_path(ctx: Context) -> Path:
    return ctx.paths.home / "reply.json"


def _reply_saved(ctx: Context) -> dict | None:
    path = _reply_path(ctx)
    if not path.is_file():
        return None
    saved = json.loads(path.read_text(encoding="utf-8"))
    if ctx.now - saved["created"] > ctx.settings.preview_minutes * 60:
        expiry.expire(path)
        return None
    return saved


def _waiting_keys(store: inbox.Store) -> list[str]:
    """The numbers you saw last (/hr list, /hr inbox show), else the waiting list as it is now."""
    return store.data.get("listing") or [k for k, _ in store.open_items()]


def _gemini_key(ctx: Context) -> str:
    return ctx.secrets.get("GEMINI_API_KEY", "GOOGLE_API_KEY")


def _item(key: str, it: dict, mail: reply.Mail | None, draft: reply.Draft, instruction: str, ctx: Context) -> dict:
    name = mail.sender_name if mail else it["name"]
    return {"key": key, "name": name, "to": it["from"], "subject": it["subject"], "how": draft.how,
            "hidden": draft.hidden, "fixes": list(draft.fixes), "instruction": instruction,
            "text": reply.as_text(draft, name, ctx.settings)}


def _reply_preview(saved: dict, minutes: int) -> str:
    items = saved["items"]
    if len(items) > 1:
        lines = [f"**Replies to {len(items)} mails** (\"{items[0]['how']}\"), waiting for your yes ({minutes} min):"]
        lines += [f"{n}. {i['name']} <{i['to']}> — Re: {i['subject']}" for n, i in enumerate(items, 1)]
        lines += ["", "Each gets:", items[0]["text"]]
    else:
        i = items[0]
        lines = [f"**Reply to {i['name']}** <{i['to']}> — Re: {i['subject']}", "", i["text"], ""]
        how = f"Drafted by {i['how']}" if i["how"].startswith(("gemini", "gemma")) else f"From {i['how']}"
        if i["hidden"]:
            how += f"; {i['hidden']} names, emails or numbers were hidden from it and put back"
        lines.append(how + ".")
        if i["fixes"]:
            lines.append("Fixed in its answer: " + "; ".join(i["fixes"]))
    lines += ["", "/hr reply yes · again <change> · edit <your text> · no"]
    return "\n".join(lines)


def _save_reply(ctx: Context, items: list[dict]) -> str:
    saved = {"created": ctx.now, "items": items}
    payslips.save_private(_reply_path(ctx), saved)
    expiry.clear(_reply_path(ctx))
    return _reply_preview(saved, ctx.settings.preview_minutes)


def _draft_for(ctx: Context, key: str, it: dict, words: str) -> dict:
    """``words``: a template name and its words, or an instruction for Gemini."""
    name, _, rest = words.strip().partition(" ")
    if ctx.settings.template(name.lower()) is not None:
        return _item(key, it, None, reply.from_template(ctx.settings, name.lower(), rest), "", ctx)
    token = graph.access(ctx.http, ctx.secrets, outlook.SCOPES)
    mail = reply.fetch(ctx.http, token, key)
    return _item(key, it, mail, reply.write(ctx.http, _gemini_key(ctx), ctx.settings, mail, words.strip()),
                 words.strip(), ctx)


def _reply_make(ctx: Context, rest: str) -> str:
    number, _, words = rest.strip().partition(" ")
    store = _inbox_store(ctx)
    keys = _waiting_keys(store)
    if not number.isdigit() or not 1 <= int(number) <= len(keys) or keys[int(number) - 1] not in store.items:
        return (f"Pick a mail 1 to {len(keys)} from /hr list, e.g. /hr reply 2" if keys
                else "No HR mail is waiting for a reply. /hr inbox show sweeps for new mail.")
    key = keys[int(number) - 1]
    try:
        return _save_reply(ctx, [_draft_for(ctx, key, store.items[key], words)])
    except reply.ReplyError as exc:
        return f"{exc}\n\nTry a template instead: /hr reply {number} ack (or reject, docs, letter, leave, salary)."


def _reply_applications(ctx: Context, arg: str) -> str:
    name, _, words = arg.strip().partition(" ")
    if ctx.settings.template(name.lower()) is None:
        return "Which template? e.g. /hr reply applications ack (no model is used for a batch)"
    store, now = _inbox_store(ctx), datetime.fromtimestamp(ctx.now, TZ)
    rows = _unanswered_applications(store, now)[: ctx.settings.reply_bulk_max]
    if not rows:
        return "Every application of the last 14 days has an answer."
    draft = reply.from_template(ctx.settings, name.lower(), words)
    return _save_reply(ctx, [_item(k, it, None, draft, "", ctx) for k, it in rows])


def _unanswered_applications(store: inbox.Store, now: datetime) -> list[tuple[str, dict]]:
    oldest = (now.astimezone(UTC).replace(tzinfo=None) - timedelta(days=inbox.LIST_DAYS)).isoformat()
    return sorted(((k, it) for k, it in store.items.items()
                   if it["cat"] == "applications" and not it.get("done") and it["received"] >= oldest),
                  key=lambda kv: kv[1]["received"])


def _reply_show(ctx: Context, _arg: str) -> str:
    saved = _reply_saved(ctx)
    return _reply_preview(saved, ctx.settings.preview_minutes) if saved else "No reply is waiting."


def _reply_again(ctx: Context, arg: str) -> str:
    saved = _reply_saved(ctx)
    if saved is None or len(saved["items"]) != 1:
        return "No single reply is waiting to redraft. Start with /hr reply <number>."
    old = saved["items"][0]
    store = _inbox_store(ctx)
    if old["key"] not in store.items:
        return "That mail is no longer in the HR inbox list. Start again with /hr list."
    try:
        return _save_reply(ctx, [_draft_for(ctx, old["key"], store.items[old["key"]],
                                            f"{old['instruction']} {arg}".strip())])
    except reply.ReplyError as exc:
        return f"{exc}\n\nThe earlier draft is gone; /hr reply edit <your text> to write it yourself."


def _reply_edit(ctx: Context, arg: str) -> str:
    saved = _reply_saved(ctx)
    if saved is None or len(saved["items"]) != 1:
        return "No single reply is waiting. Start with /hr reply <number>, then edit it."
    if not arg.strip():
        return "Write the reply after /hr reply edit (the greeting and sign-off are added)."
    item = saved["items"][0]
    item.update(how="your words", hidden=0, fixes=[],
                text=reply.as_text(reply.own_words(arg), item["name"], ctx.settings))
    return _save_reply(ctx, saved["items"])


def _reply_yes(ctx: Context, _arg: str) -> str:
    saved = _reply_saved(ctx)
    if saved is None:
        return f"No reply is waiting (a draft expires after {ctx.settings.preview_minutes} min)."
    _reply_path(ctx).unlink()  # before sending: a second yes can never send twice
    token = graph.access(ctx.http, ctx.secrets, outlook.SEND_SCOPES)
    store, failed = _inbox_store(ctx), []
    for item in saved["items"]:
        try:
            reply.send(ctx.http, token, item["key"], item["text"], ctx.settings.mailbox)
        except OutreachError as exc:
            ctx.log(item["to"], "reply", False, str(exc))
            failed.append(f"{item['name']}: {exc}")
            continue
        ctx.log(item["to"], "reply", True, item["how"])
        if item["key"] in store.items:
            store.items[item["key"]]["done"] = "replied"
    store.save()
    sent = len(saved["items"]) - len(failed)
    sender = f" from {ctx.settings.mailbox}" if ctx.settings.mailbox else ""
    return "\n".join([f"✅ Sent {sent} of {len(saved['items'])} replies{sender}, each in its own thread.",
                      *(["❌ Not sent:"] + failed if failed else [])])


def _reply_no(ctx: Context, _arg: str) -> str:
    path = _reply_path(ctx)
    if path.is_file():
        path.unlink()
        return "Dropped. Nothing was sent."
    return "Dropped the expired reply from the recap." if expiry.clear(path) else "Nothing was waiting."


# ---- /hr offer · /hr duties -----------------------------------------------------------------------


def _offer_path(ctx: Context) -> Path:
    return ctx.paths.home / "offer.json"


def _offer_saved(ctx: Context) -> dict | None:
    path = _offer_path(ctx)
    if not path.is_file():
        return None
    saved = json.loads(path.read_text(encoding="utf-8"))
    if ctx.now - saved["created"] > ctx.settings.preview_minutes * 60:
        expiry.expire(path)
        return None
    if "letters" not in saved:  # one letter, as saved before several could wait together
        saved = {"created": saved["created"], "read_by": "", "letters": [saved]}
    return saved


def _how(src: str) -> str:
    return ("saved for this position, no model call" if src == "saved" else
            f"written by {src} and saved for this position" if src != "you" else "set by you")


def _offer_text(saved: dict, minutes: int) -> str:
    letters = saved["letters"]
    lines = [f"**{len(letters)} offer letters**, not sent:"] if len(letters) > 1 else []
    if saved.get("read_by"):
        lines.append(f"(Your message was read by {saved['read_by']}: check the names and dates.)")
    shown: set[str] = set()
    for n, one in enumerate(letters, 1):
        o = one["offer"]
        pay = (f"{one.get('pay', 'stipend')}: unpaid" if one.get("unpaid") else
               f"{one.get('pay', 'stipend')} {one['monthly']} a month ({one['annual']} a year)")
        head = f"{n}. " if len(letters) > 1 else ""
        lines += [f"{head}**{one.get('kind_label', 'Offer')} offer letter: {o['name']}**, {o['position']}",
                  f"{one['dates']} · {pay}",
                  f"To: {o['email'] or '(no email: add Email: to send it)'}"]
        if o["position"].lower() not in shown:
            shown.add(o["position"].lower())
            lines += [f"Duties ({_how(one['duties_from'])}):", *(f"• {d}" for d in one["duties"])]
        lines.append(f"Files: {', '.join(Path(f).name for f in one['files'])}")
        if one.get("note"):
            lines.append(one["note"])
    mailable = sum(1 for one in letters if one["offer"]["email"])
    lines.append(f"/hr offer test — the PDFs to you · /hr offer yes — email {'each' if mailable > 1 else 'it'} to "
                 f"the person · /hr offer no — drop (waits {minutes} min)" if mailable else
                 "/hr offer test — the PDFs to you · /hr offer no — drop · add Email: lines to mail the people")
    return "\n".join(lines)


def _offer_parse(ctx: Context, kind, rest: str, today: date) -> tuple[list, list[str], str]:
    """(offers, problems, the model that read the message or ""). The plain reading first; a model only
    when that leaves a problem, and its reading is checked the same way."""
    def plain(blocks: list[str]) -> tuple[list, list[str]]:
        made, problems = [], []
        for n, block in enumerate(blocks, 1):
            one, found = offer.parse(block, kind, today)
            if one:
                made.append(one)
            who = f"Person {n}: " if len(blocks) > 1 else ""
            problems += [who + p for p in found]
        return made, problems

    made, problems = plain(offer.people(rest))
    if not problems:
        return made, [], ""
    try:
        blocks, model = intake.read(ctx.http, _gemini_key(ctx), ctx.settings.duties_models, rest, kind.role,
                                    today, kind.pay)
    except intake.IntakeError:
        return [], problems, ""
    again, still = plain(blocks)
    return (again, [], model) if not still else ([], still, model)


def _offer_make(ctx: Context, text: str) -> str:
    word, rest = _split(text)
    kind = offer.kind_of(word)
    if kind is None:
        return ("Which kind of offer? /hr offer internship · /hr offer fte · /hr offer consultant, then the "
                "details.\n\n" + OFFER_HELP)
    s, today = ctx.settings, datetime.fromtimestamp(ctx.now, TZ).date()
    made, problems, read_by = _offer_parse(ctx, kind, rest, today)
    if problems:
        note = [f"(Read by {read_by}.)"] if read_by else []
        return "\n".join(["No letter was made. Fix this and send it again:", *(f"• {p}" for p in problems),
                          *note, "", "/hr offer help for the format"])
    if len(made) > s.max_offers:
        return f"No letter was made: {len(made)} people in one message, at most {s.max_offers} (hr.max_offers)."
    template = ctx.paths.templates / dict(s.offer_templates)[kind.name]
    if not template.is_file():
        return (f"No {kind.label.lower()} offer template at {template}. Put your Word letter there (the "
                "[Name], [Position]… fields as they are); /hr offer help lists them.")
    table = duties.Table(ctx.paths.home)
    letters = []
    for one in made:
        try:
            found = duties.find_or_write(table, ctx.http, _gemini_key(ctx), s.duties_models, one.position,
                                         s.interview.company, s.company_about, today, s.duties_count, kind.role)
            folder = ctx.paths.home / "offers" / f"{today:%Y%m%d}-{kind.name}-{offer.key_part(one)}"
            doc = folder / (offer.file_stem(one) + ".docx")
            offer.make(template, one, found.items, doc, today, s.unpaid_line, s.unpaid_drop)
        except (duties.DutiesError, TemplateError) as exc:
            return f"No letter was made ({one.name}). {exc}"
        files, note = [doc], ""
        try:
            files = convert([doc], folder) + [doc]
        except PdfError as exc:
            note = f"⚠️ Word file only: {exc}"
        v = one.values(today)
        dates = (f"{v['start date']} – {v['end date']} ({one.months} months)" if one.months
                 else f"from {v['start date']}")
        letters.append({"offer": {"name": one.name, "position": one.position, "email": one.email,
                                  "start": v["start date"]},
                        "kind": kind.name, "kind_label": kind.label, "role": kind.role, "pay": kind.pay.lower(),
                        "dates": dates, "monthly": v["monthly"], "annual": v["annual"], "unpaid": one.unpaid,
                        "duties": list(found.items),
                        "duties_from": "saved" if found.saved and found.by != "you" else found.by,
                        "files": [str(f) for f in files], "items": [{"file": str(files[0])}], "note": note})
        try:  # the letter itself, to check before it goes out
            Telegram(ctx.http, ctx.secrets).file(files[0], f"{kind.label} offer letter: {one.name} (not sent)")
        except (NotesError, HttpError, OSError):
            pass  # the paths are in the reply
    store.push_duties(ctx)
    saved = {"created": ctx.now, "read_by": read_by, "letters": letters}
    path = _offer_path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(saved, fh)
    return _offer_text(saved, s.preview_minutes)


def _offer_show(ctx: Context, _arg: str) -> str:
    saved = _offer_saved(ctx)
    return _offer_text(saved, ctx.settings.preview_minutes) if saved else "No offer letter is waiting."


def _offer_mail(ctx: Context, token: str, one: dict, to: tuple[str, str]) -> str:
    """'' when sent, else why not. The PDF only (the first file; the Word file when no PDF was made)."""
    s, o = ctx.settings, one["offer"]
    letter = Path(one["files"][0])
    if not letter.is_file():
        return f"{o['name']}: {letter.name} is gone; make the letter again with /hr offer"
    values = {"first": o["name"].split()[0], "name": o["name"], "position": o["position"], "start": o["start"],
              "role": one.get("role", "role"), "company": s.interview.company, "sender": s.sender_name or "HR Team"}
    try:
        graph.send_mail(ctx.http, token, to=to, subject=fill(s.offer_subject, **values),
                        body_html=fill(s.offer_body, **values),
                        attachments=((letter.name, letter.read_bytes()),), sender=s.mailbox)
    except (OutreachError, HttpError, OSError) as exc:
        ctx.log(to[1], str(letter), False, str(exc))
        return f"{o['name']}: {exc}"
    ctx.log(to[1], str(letter), True)
    return ""


def _offer_test(ctx: Context, _arg: str) -> str:
    """Each letter, as the person would get it, to you only (the signed-in Outlook account)."""
    saved = _offer_saved(ctx)
    if saved is None:
        return f"No offer letter is waiting (one expires after {ctx.settings.preview_minutes} min)."
    token = _token(ctx)
    me = graph.me(ctx.http, token)
    failed = [f for one in saved["letters"] if (f := _offer_mail(ctx, token, one, (one["offer"]["name"], me)))]
    sent = len(saved["letters"]) - len(failed)
    return "\n".join([f"Sent {sent} letter(s) to {me} only, as each person would get them. Nobody else got "
                      "anything; /hr offer yes mails the people.", *(f"❌ {f}" for f in failed)])


def _offer_yes(ctx: Context, _arg: str) -> str:
    saved = _offer_saved(ctx)
    if saved is None:
        return f"No offer letter is waiting (one expires after {ctx.settings.preview_minutes} min)."
    letters = [one for one in saved["letters"] if one["offer"]["email"]]
    if not letters:
        return "No letter has an email address. Send /hr offer again with Email: lines."
    _offer_path(ctx).unlink()  # before sending: a second yes can never mail twice
    token = _token(ctx)
    failed = [f for one in letters if (f := _offer_mail(ctx, token, one, (one["offer"]["name"], one["offer"]["email"])))]
    s = ctx.settings
    sender = f" from {s.mailbox}" if s.mailbox else ""
    if len(saved["letters"]) == 1 and not failed:
        o = letters[0]["offer"]
        return f"✅ Offer letter sent to {o['name']} <{o['email']}>{sender}."
    skipped = [one["offer"]["name"] for one in saved["letters"] if not one["offer"]["email"]]
    out = [f"✅ Sent {len(letters) - len(failed)} of {len(letters)} offer letters{sender}."]
    out += [f"❌ {f}" for f in failed] + ([f"Not sent (no email): {', '.join(skipped)}"] if skipped else [])
    return "\n".join(out + (["Make the failed ones again with /hr offer to retry."] if failed else []))


def _offer_no(ctx: Context, _arg: str) -> str:
    path = _offer_path(ctx)
    if path.is_file():
        path.unlink()
        return "Dropped. Nothing was sent (the files stay in $HERMES_HOME/hr/offers/)."
    return "Dropped the expired offer letter from the recap." if expiry.clear(path) else "Nothing was waiting."


def _duties_list(ctx: Context) -> str:
    rows = duties.Table(ctx.paths.home).rows
    if not rows:
        return "No duties saved yet. /hr offer saves them for each new position; /hr duties help"
    return "\n".join([f"**Duties saved ({len(rows)} positions)**",
                      *(f"• {r['position']}: {len(r['duties'])} duties, {r.get('by') or '?'}, {r.get('saved', '')}"
                        for r in sorted(rows.values(), key=lambda r: r["position"].lower())),
                      "/hr duties <position> to see one"])


def _duties(ctx: Context, text: str) -> str:
    text = text.strip()
    if not text:
        return _duties_list(ctx)
    table = duties.Table(ctx.paths.home)
    position, sep, given = text.partition("=")
    position = " ".join(position.split())
    if sep:
        items = duties.clean([d for d in re.split(r"[;\n]", given) if d.strip()])
        if not items:
            return "Give the duties after =, separated by ; (or one per line)."
        table.put(position, items, "you", datetime.fromtimestamp(ctx.now, TZ).date())
        return f"Saved {len(items)} duties for {position}; the next /hr offer for it uses them."
    found = table.get(position)
    if not found:
        return f"No duties saved for {position!r}. The next /hr offer for it writes them, or set them: " \
               f"/hr duties {position} = first; second; …"
    return "\n".join([f"**{found.position}** ({found.by or '?'})", *(f"• {d}" for d in found.items),
                      f"/hr duties forget {found.position} — ask the model again next time"])


def _duties_forget(ctx: Context, arg: str) -> str:
    if not arg.strip():
        return "Which position? /hr duties forget Marketing Intern"
    gone = duties.Table(ctx.paths.home).forget(arg)
    return f"Forgot the duties for {arg.strip()}." if gone else f"No duties were saved for {arg.strip()!r}."


# ---- /hr list -----------------------------------------------------------------------------------


def _approvals(ctx: Context) -> list[str]:
    lines = []
    for item in pending_files(ctx.paths.home.parent):
        if item.path.parent != ctx.paths.home:
            continue
        if item.path.is_file():
            created = json.loads(item.path.read_text(encoding="utf-8"))["created"]
            ends = datetime.fromtimestamp(created + item.minutes * 60, TZ)
            if ends > datetime.fromtimestamp(ctx.now, TZ):
                lines.append(f"✍️ {item.name}: waiting for your yes until {ends:%H:%M} · {item.command}")
                continue
        if item.path.is_file() or expiry.marker(item.path).is_file():
            lines.append(f"⌛ {item.name}: expired without your yes · /recap now to bring it back, "
                         f"or {item.cancel} to drop it")
    return lines


def _list(ctx: Context, _arg: str) -> str:
    store, now = _inbox_store(ctx), datetime.fromtimestamp(ctx.now, TZ)
    waiting = inbox.open_lines(store, now)
    store.save()  # keeps the numbers you see for /hr reply <n> and /hr inbox done <n>
    apps = _unanswered_applications(store, now)
    approvals = _approvals(ctx)
    swept = store.data.get("last_sweep")
    lines = ["**HR — everything pending**" + (f" (mail as of the {swept[11:16]} UTC sweep)" if swept else "")]
    if waiting:
        lines += ["", f"**Mail waiting for a reply ({len(waiting)})**", *waiting,
                  "/hr reply 1 — draft an answer · /hr inbox done 1 — handled elsewhere"]
    if apps:
        lines += ["", f"📄 {len(apps)} applications of the last {inbox.LIST_DAYS} days have no answer · "
                      "/hr reply applications ack"]
    if approvals:
        lines += ["", "**Approvals**", *approvals]
    if len(lines) == 1:
        lines.append("Nothing is pending." if swept else "Nothing is pending. /hr inbox show sweeps the HR mailbox first.")
    return "\n".join(lines)


REPLY = {"show": _reply_show, "yes": _reply_yes, "no": _reply_no, "cancel": _reply_no, "again": _reply_again,
         "edit": _reply_edit, "applications": _reply_applications}
TOPICS = {"payslip": (PAYSLIP, _make, PAYSLIP_HELP),
          "interview": (INTERVIEW, _interview_make, INTERVIEW_HELP),
          "inbox": (INBOX, lambda _ctx, _rest: INBOX_HELP, INBOX_HELP),
          "reply": (REPLY, _reply_make, REPLY_HELP),
          "offer": ({"show": _offer_show, "test": _offer_test, "yes": _offer_yes, "no": _offer_no,
                     "cancel": _offer_no},
                    _offer_make, OFFER_HELP),
          "sync": ({"pull": lambda ctx, _a: store.pull(ctx), "push": lambda ctx, _a: store.push(ctx)},
                   lambda _ctx, _rest: SYNC_HELP, SYNC_HELP),
          "duties": ({"forget": _duties_forget, "list": lambda ctx, _a: _duties_list(ctx)}, _duties, DUTIES_HELP)}
HELP_WORDS = {"help", "-help", "--help", "-h", "?"}


def _split(text: str) -> tuple[str, str]:
    """First word and the rest; a new line counts as a space (interview rows come one per line)."""
    parts = (text or "").strip().split(maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else ((parts[0], "") if parts else ("", ""))


def handle(raw: str, state_dir: Path | None = None, http: Http | None = None, now: float | None = None) -> str:
    """``payslip show`` → that step; ``payslip <sheet> <dates>`` → make; anything else → help."""
    topic, rest = _split(raw)
    if topic.lower() == "list" and not rest.strip():
        return _list(Context(state_dir or default_state_dir(), http, now), "")
    if topic.lower() not in TOPICS:
        return HR_HELP
    steps, make, help_text = TOPICS[topic.lower()]
    word, arg = _split(rest)
    if not word or word.lower() in HELP_WORDS:
        return help_text
    step = steps.get(word.lower())
    try:
        ctx = Context(state_dir or default_state_dir(), http, now)
        return step(ctx, arg) if step else make(ctx, rest)
    except OutreachError as exc:
        return str(exc)
