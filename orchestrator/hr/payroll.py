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
    problems: tuple[str, ...]  # any → nothing is generated, unless you choose to leave those rows out
    skipped: tuple[str, ...]  # Compensation 0: listed, not paid
    warnings: tuple[str, ...]
    left_out: tuple[str, ...] = ()  # "Row 6 (Avni)" for every row with a problem; never in ``slips``


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


MONEY = {"compensation": "Compensation", "basic": "Basic", "hra": "HRA", "lop": "LOP Days",
         "other_deductions": "Other Deductions", "reimbursement": "Reimbursement"}


def _row(raw: dict[str, str], period: Period, days: int, absent: frozenset[str]) -> tuple[Slip | None, list[str]]:
    """Every problem in the row at once. Checks of a column the sheet doesn't have are skipped
    (that column is reported once, not on every row); such a row never becomes a slip."""
    who = f"Row {raw['row']} ({raw.get('name') or 'no name'})"
    problems = [f"{who}: {field} is missing" for field in ("name", "designation", "email")
                if field not in absent and raw.get(field, "").strip() in ("", "0")]
    if raw.get("email", "").strip() not in ("", "0") and not EMAIL.match(raw["email"].strip()):
        problems.append(f"{who}: '{raw['email']}' is not an email address")
    try:
        doj = _date(raw.get("doj", ""))
    except ValueError:
        problems.append(f"{who}: DOJ '{raw.get('doj', '')}' is not a date (use dd/mm/yyyy)")
        doj = period.start
    money: dict[str, Decimal] = {}
    for key, label in MONEY.items():
        try:
            money[key] = _money(raw.get(key, ""))
        except InvalidOperation:
            problems.append(f"{who}: {label} '{raw.get(key)}' is not a number")
    if len(money) < len(MONEY):
        return None, problems
    comp, basic, lop = money["compensation"], money["basic"], money["lop"]
    hra = money["hra"] if "hra" in raw else comp - basic  # a sheet without HRA: the rest of Compensation
    if "basic" not in absent and "hra" in raw and basic + hra != comp:
        problems.append(f"{who}: Basic + HRA ({basic + hra}) is not Compensation ({comp})")
    if "basic" not in absent and not 0 <= basic <= comp:
        problems.append(f"{who}: Basic {basic} must be between 0 and Compensation ({comp})")
    if not 0 <= lop <= days:
        problems.append(f"{who}: LOP days {lop} is outside 0–{days} working days")
    if doj > period.end:
        problems.append(f"{who}: joins {doj:%d/%m/%Y}, after this pay period")
    if problems or absent:
        return None, problems
    lop_amount = (comp / days * lop).quantize(RUPEE, ROUND_HALF_UP)
    return Slip(int(raw["row"]), " ".join(raw["name"].split()), raw["email"].strip().lower(),
                " ".join(raw["designation"].split()), doj, basic, hra, comp, lop, lop_amount,
                money["other_deductions"], money["reimbursement"], days), []


def build(rows: list[dict[str, str]], period: Period, settings: Settings,
          absent: frozenset[str] = frozenset()) -> Batch:
    """``absent``: required columns the sheet lacks; the rows are still checked for everything else."""
    days = working_days(period, settings)
    slips: list[Slip] = []
    problems: list[str] = []
    skipped: list[str] = []
    warnings: list[str] = []
    left_out: list[str] = []
    for raw in rows:
        if raw.get("compensation", "").replace(",", "").strip() in ("", "0"):
            skipped.append(f"Row {raw['row']} ({raw.get('name') or 'no name'}): compensation is 0, no slip")
            continue
        if any(raw.get(k, "x").strip() in ("", "0") for k in ("ifsc", "bank")):
            warnings.append(f"Row {raw['row']} ({raw.get('name')}): bank details are blank or 0 (not on the slip; "
                            "check before paying)")
        slip, found = _row(raw, period, days, absent)
        problems += found
        if found:
            left_out.append(f"Row {raw['row']} ({raw.get('name') or 'no name'})")
        if slip is None:
            continue
        if slip.doj > period.start:
            warnings.append(f"{slip.name} joined {slip.doj:%d/%m/%Y}, inside this period: check the LOP days")
        slips.append(slip)
    by_email: dict[str, list[Slip]] = {}
    for slip in slips:
        by_email.setdefault(slip.email, []).append(slip)
    for email, same in by_email.items():
        if len(same) > 1:  # neither row can be trusted to be that person's address
            problems.append(f"{email} is on {len(same)} rows (" + " and ".join(s.name for s in same) + ")")
            left_out += [f"Row {s.row} ({s.name})" for s in same]
    slips = [s for s in slips if len(by_email[s.email]) == 1]
    return Batch(tuple(slips), tuple(problems), tuple(skipped), tuple(warnings), tuple(left_out))
