"""``/hr`` in Telegram: HR jobs, each under its own word: ``payslip``, ``interview``, ``inbox``.

/hr payslip <sheet> <from> <to> <pay date> — make the slips (what Hermes' agent runs with your sheet)
/hr payslip check · show · test · yes · no · skip — check a sheet, review, sample to you, send, cancel,
  or leave out the rows with problems. No model ever sees pay; ``show`` is a command, not a chat turn.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http, HttpError, UrllibHttp
from orchestrator.brief.sources import outlook
from orchestrator.brief.store import default_state_dir
from orchestrator.outreach import graph
from orchestrator.outreach.build import fill
from orchestrator.outreach.errors import OutreachError
from orchestrator.outreach.plan import picks

from . import inbox, interview, payslips, request, settings
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
/hr payslip — monthly payslips from the salary sheet (/hr payslip help for every step)
/hr interview — one Teams link, each candidate invited to their own slot (/hr interview help)
/hr inbox — mail to the HR mailbox sorted: urgent, people, campus, applications (/hr inbox help)
/menu — all your commands"""

INBOX_HELP = """**/hr inbox** — mail to the HR mailbox, sorted by fixed rules (no AI model reads HR mail)
/hr inbox show — new HR mail by kind, and every urgent or people mail still waiting for a reply
/hr inbox list applications — the last 14 days of one kind (urgent · people · campus · applications · other)
/hr inbox done 2 — mark a waiting mail handled (one answered in its thread clears on its own)
Swept at 10:00 and 17:00 (cron); it messages you only when there is new HR mail, and the first sweep
of the day also reminds you of urgent mail still unanswered. /menu — all your commands"""

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
            self.paths.pending.unlink()
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
    return "Nothing was waiting."


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
        path.unlink()
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
        path.unlink()
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
    return "Nothing was waiting."


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
TOPICS = {"payslip": (PAYSLIP, _make, PAYSLIP_HELP),
          "interview": (INTERVIEW, _interview_make, INTERVIEW_HELP),
          "inbox": (INBOX, lambda _ctx, _rest: INBOX_HELP, INBOX_HELP)}  # next: "letter" (offer, termination)
HELP_WORDS = {"help", "-help", "--help", "-h", "?"}


def _split(text: str) -> tuple[str, str]:
    """First word and the rest; a new line counts as a space (interview rows come one per line)."""
    parts = (text or "").strip().split(maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else ((parts[0], "") if parts else ("", ""))


def handle(raw: str, state_dir: Path | None = None, http: Http | None = None, now: float | None = None) -> str:
    """``payslip show`` → that step; ``payslip <sheet> <dates>`` → make; anything else → help."""
    topic, rest = _split(raw)
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
