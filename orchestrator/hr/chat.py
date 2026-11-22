"""``/hr`` in Telegram: HR jobs, each under its own word. Today: ``/hr payslip``.

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

from . import payslips, settings
from .payroll import Period
from .payslips import Paths, rupees

PAYSLIP_HELP = """**/hr payslip** — payslips from your salary sheet, emailed from your Outlook (no AI model touches pay)
Send Hermes the month's sheet (.xlsx/.csv) and say the period, e.g. "payslips for 1–30 Nov, paid 2 Dec".
Columns: Employee Name, Position, DOJ, Email, Compensation, Basic, HRA, LOP Days
(optional: Reimbursement, Other Deductions). Any bad row stops the run; every employee with a
problem is listed, and /hr payslip skip makes everyone else's slips, leaving those rows out.
/hr payslip <sheet path> <from> <to> <pay date> — make the slips (dates dd/mm/yyyy); nothing is sent
/hr payslip check <sheet path> <from> <to> — only checks the sheet and lists every problem
/hr payslip show — slips waiting: name, email, net pay
/hr payslip test — 2 sample slips emailed to you · test all — every slip, to you only
/hr payslip yes — email everyone their own slip · yes 1-10 — only those
/hr payslip no — cancel
/hr payslip skip — make the good rows' slips, leave the listed employees out
/menu — all your commands"""

HR_HELP = """**/hr** — HR jobs from your files, sent from your Outlook only after you approve
/hr payslip — monthly payslips from the salary sheet (/hr payslip help for every step)
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
            self.paths.pending.unlink()
            return None
        return plan

    def log(self, to: str, file: str, ok: bool, note: str = "", test: bool = False) -> None:
        row = {"ts": datetime.fromtimestamp(self.now, TZ).isoformat(timespec="seconds"), "to": to,
               "file": Path(file).name, "test": test, "ok": ok, "note": note[:200]}
        fd = os.open(self.paths.sent, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")


def _date(text: str) -> date:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"'{text}' is not a date (use dd/mm/yyyy)")


def run_payslips(ctx: Context, sheet: str, start: str, end: str, pay_date: str) -> str:
    try:
        period = Period(_date(start), _date(end), _date(pay_date))
    except ValueError as exc:
        return str(exc)
    if period.end < period.start:
        return "The period ends before it starts."
    return payslips.prepare(Path(sheet).expanduser(), period, ctx.settings, ctx.paths, ctx.now)


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
                        attachments=((Path(item["file"]).name, Path(item["file"]).read_bytes()),))
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
    return "\n".join([f"Sent {len(items) - len(failed)} test slip(s) to {me} only. Check them, then /hr payslip yes.",
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
    parts = arg.split()
    if len(parts) != 3:
        return "Usage: /hr payslip check <sheet path> <from> <to>, dates dd/mm/yyyy"
    try:
        period = Period(_date(parts[1]), _date(parts[2]), _date(parts[2]))
    except ValueError as exc:
        return str(exc)
    checked = payslips.check(Path(parts[0]).expanduser(), period, ctx.settings, ctx.paths)
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
    parts = arg.split()
    if len(parts) != 4:
        return PAYSLIP_HELP
    return run_payslips(ctx, *parts)


def agent_make(args: list[str], state_dir: Path | None = None) -> str:
    """The only entry Hermes' agent has: make slips from a sheet. It can't reach show, test, yes or skip."""
    if len(args) != 4:
        return "Usage: hr_payslips.py <sheet path> <from> <to> <pay date>, dates dd/mm/yyyy"
    return run_payslips(Context(state_dir or default_state_dir()), *args)


PAYSLIP = {"check": _check, "show": _show, "test": _test, "yes": _yes, "no": _no, "cancel": _no, "skip": _skip}
TOPICS = {"payslip": (PAYSLIP, _make, PAYSLIP_HELP)}  # next: "letter" (offer, termination)
HELP_WORDS = {"help", "-help", "--help", "-h", "?"}


def handle(raw: str, state_dir: Path | None = None, http: Http | None = None, now: float | None = None) -> str:
    """``payslip show`` → that step; ``payslip <sheet> <dates>`` → make; anything else → help."""
    topic, _, rest = (raw or "").strip().partition(" ")
    if topic.lower() not in TOPICS:
        return HR_HELP
    steps, make, help_text = TOPICS[topic.lower()]
    word, _, arg = rest.strip().partition(" ")
    if not word or word.lower() in HELP_WORDS:
        return help_text
    step = steps.get(word.lower())
    try:
        ctx = Context(state_dir or default_state_dir(), http, now)
        return step(ctx, arg) if step else make(ctx, rest)
    except OutreachError as exc:
        return str(exc)
