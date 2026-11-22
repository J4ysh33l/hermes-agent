"""One payslip run: read the sheet, check every row, fill one Word slip per person, convert them to
PDF, and save the batch for approval. Nothing is emailed here.

The text this returns for Hermes' agent carries counts and problems only, never amounts, so
salary figures don't pass through the agent's model. ``/hr show`` (a command, no model) lists
names, addresses and net pay for you.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from orchestrator.brief.render import indian_grouping

from . import docfill, pdf, sheet
from .payroll import Batch, Period, Slip, build
from .settings import Settings


@dataclass(frozen=True)
class Paths:
    home: Path  # $HERMES_HOME/hr

    @property
    def templates(self) -> Path:
        return self.home / "templates"

    @property
    def pending(self) -> Path:
        return self.home / "pending.json"

    @property
    def blocked(self) -> Path:
        """The last run stopped only by bad rows: what ``/hr skip`` re-runs without them."""
        return self.home / "blocked.json"

    @property
    def sent(self) -> Path:
        return self.home / "sent.jsonl"

    def run_dir(self, period: Period) -> Path:
        return self.home / "payslips" / period.key


def rupees(amount: Decimal) -> str:
    return "₹" + indian_grouping(float(amount))


def period_text(period: Period) -> str:
    """'1–30 Nov 2026'; '16 Nov – 15 Dec 2026' across months; years shown when they differ."""
    a, b = period.start, period.end
    if (a.month, a.year) == (b.month, b.year):
        return f"{a.day}–{b.day} {b:%b %Y}"
    return f"{a.day} {a:%b}{a:' %Y' if a.year != b.year else ''} – {b.day} {b:%b %Y}"


def values(slip: Slip, period: Period) -> dict[str, str]:
    days = slip.lop_days.normalize()
    return {"month": period.month, "name": slip.name, "designation": slip.designation,
            "doj": f"{slip.doj:%d/%m/%Y}", "pay_period": period_text(period),
            "paid_days": f"{slip.paid_days.normalize():f}", "lop_days": f"{days:f}",
            "pay_date": f"{period.pay_date:%d/%m/%Y}", "basic": rupees(slip.basic), "hra": rupees(slip.hra),
            "gross": rupees(slip.gross), "lop_amount": rupees(slip.lop_amount),
            "other_deductions": rupees(slip.other_deductions), "total_deductions": rupees(slip.total_deductions),
            "reimbursement": rupees(slip.reimbursement), "net_pay": rupees(slip.net)}


def file_name(slip: Slip, period: Period) -> str:
    safe = "".join(c if c.isalnum() else "_" for c in slip.name).strip("_")
    return f"Payslip_{period.end:%b-%Y}_{safe}"


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for part in (path, *path.parents):
        if part.name == "hr":
            os.chmod(part, 0o700)
            break
    return path


def _by_row(problems: tuple[str, ...]) -> list[str]:
    """One line per employee: 'Row 7 (Ayush Singh): designation is missing; email is missing'."""
    rows: dict[str, list[str]] = {}
    for problem in problems:
        who, sep, what = problem.partition("): ")
        key, text = (who + ")", what) if sep and who.startswith("Row ") else (problem, "")
        rows.setdefault(key, []).append(text)
    return [f"• {who}: {'; '.join(t for t in texts if t)}" if any(texts) else f"• {who}" for who, texts in rows.items()]


def _report(batch: Batch, leave_out: bool = False) -> list[str]:
    out = []
    if batch.problems and leave_out:
        out += [f"Left out, no slip until fixed ({len(batch.left_out)}):", *_by_row(batch.problems)]
    elif batch.problems:
        out += [f"❌ {len(batch.left_out)} employee(s) with problems:", *_by_row(batch.problems)]
    if batch.skipped:
        out += ["Skipped:"] + [f"• {s}" for s in batch.skipped]
    if batch.warnings:
        out += ["⚠️ Check:"] + [f"• {w}" for w in batch.warnings]
    return out


@dataclass(frozen=True)
class Checked:
    batch: Batch | None  # None: the sheet could not be read
    sheet_errors: tuple[str, ...]  # template, columns, size: no slip can be made until these are fixed

    def ready(self, leave_out: bool = False) -> bool:
        b = self.batch
        return b is not None and not self.sheet_errors and bool(b.slips) and (leave_out or not b.problems)

    def can_leave_out(self) -> bool:
        """Only rows are wrong, and at least one other row is fine: /hr skip can go ahead."""
        return not self.ready() and self.ready(leave_out=True)

    def report(self, leave_out: bool = False) -> list[str]:
        return [*self.sheet_errors, *(_report(self.batch, leave_out) if self.batch else [])]


def check(sheet_path: Path, period: Period, settings: Settings, paths: Paths) -> Checked:
    """Everything that could stop a run, found before anything is made: the template, missing
    columns, and every problem in every row, all in one list so the sheet is fixed in one pass."""
    errors: list[str] = []
    template = paths.templates / settings.payslip_template
    if not template.is_file():
        errors.append(f"❌ No payslip template at {template}. Copy your Word template there.")
    try:
        rows, missing = sheet.read(sheet_path)
    except (OSError, ValueError) as exc:
        return Checked(None, (*errors, f"❌ Can't read the sheet: {exc}"))
    if missing:
        errors.append("❌ Add these columns: " + ", ".join(sheet.LABELS[m] for m in missing))
    batch = build(rows, period, settings, frozenset(missing))
    if not missing and not batch.slips and not batch.problems:
        errors.append("❌ No rows with pay in the sheet.")
    if len(batch.slips) > settings.max_per_run:
        errors.append(f"❌ {len(batch.slips)} slips is over hr.max_per_run ({settings.max_per_run}).")
    return Checked(batch, tuple(errors))


def _offer(checked: Checked) -> list[str]:
    b = checked.batch
    names = ", ".join(w.split("(", 1)[1].rstrip(")") for w in b.left_out)
    return ["", f"Leave out {len(b.left_out)} ({names}) and make the other {len(b.slips)} slips? /hr skip"]


def prepare(sheet_path: Path, period: Period, settings: Settings, paths: Paths, now: float | None = None,
            leave_out: tuple[str, ...] | None = None) -> str:
    """``leave_out``: the rows you agreed to leave out (from ``/hr skip``). If the sheet now has a
    different set of bad rows, nothing is made and the new list is offered instead."""
    now = time.time() if now is None else now
    checked = check(sheet_path, period, settings, paths)
    agreed = leave_out is not None and checked.batch is not None and checked.batch.left_out == leave_out
    if not checked.ready(leave_out=agreed):
        paths.blocked.unlink(missing_ok=True)
        head = ("The sheet changed since you said skip. Nothing was made:" if leave_out is not None
                else "Nothing was made. Fix all of this, then send the sheet again:")
        lines = [head, *checked.report()]
        if checked.can_leave_out():
            _save(paths.blocked, {"created": now, "sheet": str(sheet_path), "start": period.start.isoformat(),
                                  "end": period.end.isoformat(), "pay_date": period.pay_date.isoformat(),
                                  "left_out": list(checked.batch.left_out)})
            lines += _offer(checked)
        return "\n".join(lines)
    paths.blocked.unlink(missing_ok=True)
    batch, report = checked.batch, checked.report(leave_out=agreed)
    template = paths.templates / settings.payslip_template
    out = _private_dir(paths.run_dir(period))
    docs = []
    for slip in batch.slips:
        doc = out / (file_name(slip, period) + ".docx")
        docfill.fill(template, values(slip, period), doc)
        docs.append(doc)
    pdfs = pdf.convert(docs, out)
    for doc in docs:
        doc.unlink()
    items = [{"name": s.name, "first": s.first, "email": s.email, "file": str(p), "net": str(s.net)}
             for s, p in zip(batch.slips, pdfs)]
    _save(paths.pending, {"created": now, "month": period.month, "items": items, "notes": report})
    return "\n".join([f"✅ {len(items)} payslips for {period.month} are ready. Nothing is sent yet.", *report,
                      "", "Next: /hr show (list with net pay) · /hr test (2 samples to you) · /hr yes · /hr no"])


def _save(path: Path, data: dict) -> None:
    _private_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(path, 0o600)
