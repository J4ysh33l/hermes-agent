"""Your monthly salary sheet (.xlsx or .csv) → rows of text keyed by field name.

Columns are matched by header, any order and case. Bank columns are only checked for blanks (they
are not on the slip) and never copied anywhere; other extra columns are ignored.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

COLUMNS = {
    "employee name": "name", "name": "name",
    "position": "designation", "designation": "designation",
    "doj": "doj", "date of joining": "doj",
    "email": "email", "email id": "email", "mail": "email",
    "compensation": "compensation",
    "basic": "basic", "basic pay": "basic", "basic salary": "basic",
    "hra": "hra", "house rent allowance": "hra",
    "lop days": "lop", "lop": "lop",
    "reimbursement": "reimbursement", "reimbursements": "reimbursement",
    "other deductions": "other_deductions", "deductions": "other_deductions",
    "ifsc code": "ifsc", "ifsc": "ifsc", "bank account": "bank", "account number": "bank",
}
LABELS = {"name": "Employee Name", "designation": "Position", "doj": "DOJ", "email": "Email",
          "compensation": "Compensation", "basic": "Basic", "hra": "HRA"}
REQUIRED = ("name", "designation", "doj", "email", "compensation", "basic", "hra")


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime | date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _table(path: Path) -> list[list[str]]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook  # only for spreadsheets; csv needs nothing

        book = load_workbook(path, read_only=True, data_only=True)
        return [[_text(v) for v in row] for row in book.worksheets[0].iter_rows(values_only=True)]
    if path.suffix.lower() in (".csv", ".tsv", ".txt"):
        raw = path.read_text(encoding="utf-8-sig")
        dialect = "excel-tab" if "\t" in raw.splitlines()[0] else "excel"
        return [[c.strip() for c in row] for row in csv.reader(raw.splitlines(), dialect)]
    raise ValueError(f"{path.name}: use an .xlsx or .csv file")


def read(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """(rows, missing required columns). Each row also carries 'row' = its line in the sheet."""
    table = [r for r in _table(path) if any(r)]
    if not table:
        return [], list(REQUIRED)
    keys = [COLUMNS.get(" ".join(h.lower().split()), "") for h in table[0]]
    missing = [c for c in REQUIRED if c not in keys]
    rows = []
    for n, cells in enumerate(table[1:], start=2):
        row = {k: cells[i] if i < len(cells) else "" for i, k in enumerate(keys) if k}
        rows.append({**row, "row": str(n)})
    return rows, missing
