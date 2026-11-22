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


def _report(batch: Batch) -> list[str]:
    out = []
    if batch.problems:
        out += ["❌ Fix these rows in the sheet and send it again (nothing was made):"]
        out += [f"• {p}" for p in batch.problems]
    if batch.skipped:
        out += ["Skipped:"] + [f"• {s}" for s in batch.skipped]
    if batch.warnings:
        out += ["⚠️ Check:"] + [f"• {w}" for w in batch.warnings]
    return out


def prepare(sheet_path: Path, period: Period, settings: Settings, paths: Paths, now: float | None = None) -> str:
    rows, missing = sheet.read(sheet_path)
    if missing:
        return "The sheet is missing these columns: " + ", ".join(missing) + ". Nothing was made."
    batch = build(rows, period, settings)
    if batch.problems or not batch.slips:
        return "\n".join(_report(batch) or ["No rows with pay in the sheet."])
    if len(batch.slips) > settings.max_per_run:
        return f"{len(batch.slips)} slips is over hr.max_per_run ({settings.max_per_run}). Nothing was made."
    template = paths.templates / settings.payslip_template
    if not template.is_file():
        return f"No payslip template at {template}. Copy your Word template there first."
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
    plan = {"created": time.time() if now is None else now, "month": period.month, "items": items,
            "notes": list(_report(batch))}
    paths.pending.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(paths.pending, 0o600)
    return "\n".join([f"✅ {len(items)} payslips for {period.month} are ready. Nothing is sent yet.", *_report(batch),
                      "", "Next: /hr show (list with net pay) · /hr test (2 samples to you) · /hr yes · /hr no"])
