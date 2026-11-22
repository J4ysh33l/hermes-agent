"""Sheet rows → payslip figures, by fixed rules (no model, no guessing):

- Gross = Basic + HRA, and must equal Compensation (else the row stops).
- Working days = days in the pay period minus weekly offs and holidays (``hr.weekly_off``).
- Loss of pay = Compensation ÷ working days × LOP days, rounded to the rupee.
- Net = Gross − (Loss of pay + Other deductions) + Reimbursement.
- Paid days = working days − LOP days.

A row with a problem stops the whole run (``problems``); a row with Compensation 0 is skipped and
listed; someone who joined inside the period is a warning (check their LOP covers it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .settings import Settings

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RUPEE = Decimal(1)


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    pay_date: date

    @property
    def month(self) -> str:
        return self.end.strftime("%B %Y")

    @property
    def key(self) -> str:
        return self.end.strftime("%Y-%m")


@dataclass(frozen=True)
class Slip:
    row: int
    name: str
    email: str
    designation: str
    doj: date
    basic: Decimal
    hra: Decimal
    gross: Decimal
    lop_days: Decimal
    lop_amount: Decimal
    other_deductions: Decimal
    reimbursement: Decimal
    working_days: int

    @property
    def first(self) -> str:
        return self.name.split(" ")[0]

    @property
    def total_deductions(self) -> Decimal:
        return self.lop_amount + self.other_deductions

    @property
    def net(self) -> Decimal:
        return self.gross - self.total_deductions + self.reimbursement

    @property
    def paid_days(self) -> Decimal:
        return Decimal(self.working_days) - self.lop_days


@dataclass(frozen=True)
class Batch:
    slips: tuple[Slip, ...]
    problems: tuple[str, ...]  # any → nothing is generated
    skipped: tuple[str, ...]  # Compensation 0: listed, not paid
    warnings: tuple[str, ...]


def working_days(period: Period, settings: Settings) -> int:
    days = (period.end - period.start).days + 1
    return sum(1 for n in range(days) if (d := period.start + timedelta(days=n)).weekday() not in settings.weekly_off
               and d not in settings.holidays)


def _money(text: str) -> Decimal:
    cleaned = text.replace(",", "").replace("₹", "").strip() or "0"
    return Decimal(cleaned)


def _date(text: str) -> date:
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(text)


def _row(raw: dict[str, str], period: Period, days: int) -> tuple[Slip | None, list[str]]:
    who = f"Row {raw['row']} ({raw.get('name') or 'no name'})"
    problems = [f"{who}: {field} is missing" for field in ("name", "designation", "email")
                if raw.get(field, "").strip() in ("", "0")]
    if raw.get("email") and not EMAIL.match(raw["email"].strip()):
        problems.append(f"{who}: '{raw['email']}' is not an email address")
    try:
        doj = _date(raw.get("doj", ""))
    except ValueError:
        problems.append(f"{who}: DOJ '{raw.get('doj', '')}' is not a date (use dd/mm/yyyy)")
        doj = period.start
    try:
        comp, basic, hra = (_money(raw.get(k, "")) for k in ("compensation", "basic", "hra"))
        lop = _money(raw.get("lop", ""))
        other, reimb = _money(raw.get("other_deductions", "")), _money(raw.get("reimbursement", ""))
    except InvalidOperation:
        return None, [*problems, f"{who}: a money or LOP cell is not a number"]
    if basic + hra != comp:
        problems.append(f"{who}: Basic + HRA ({basic + hra}) is not Compensation ({comp})")
    if not 0 <= lop <= days:
        problems.append(f"{who}: LOP days {lop} is outside 0–{days} working days")
    if doj > period.end:
        problems.append(f"{who}: joins {doj:%d/%m/%Y}, after this pay period")
    if problems:
        return None, problems
    lop_amount = (comp / days * lop).quantize(RUPEE, ROUND_HALF_UP)
    return Slip(int(raw["row"]), " ".join(raw["name"].split()), raw["email"].strip().lower(),
                " ".join(raw["designation"].split()), doj, basic, hra, comp, lop, lop_amount, other, reimb, days), []


def build(rows: list[dict[str, str]], period: Period, settings: Settings) -> Batch:
    days = working_days(period, settings)
    slips: list[Slip] = []
    problems: list[str] = []
    skipped: list[str] = []
    warnings: list[str] = []
    for raw in rows:
        if raw.get("compensation", "").replace(",", "").strip() in ("", "0"):
            skipped.append(f"Row {raw['row']} ({raw.get('name') or 'no name'}): compensation is 0, no slip")
            continue
        slip, found = _row(raw, period, days)
        problems += found
        if slip is None:
            continue
        if slip.doj > period.start:
            warnings.append(f"{slip.name} joined {slip.doj:%d/%m/%Y}, inside this period: check the LOP days")
        slips.append(slip)
    seen: dict[str, str] = {}
    for slip in slips:
        if slip.email in seen:
            problems.append(f"{slip.email} is on two rows ({seen[slip.email]} and {slip.name})")
        seen[slip.email] = slip.name
    return Batch(tuple(slips), tuple(problems), tuple(skipped), tuple(warnings))
