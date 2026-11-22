"""What ``/hr payslip`` was given: a sheet file or a pasted table, a period, and a pay date.

    /hr payslip November 02/12/2026          + the table pasted on the next lines
    /hr payslip ~/nov.xlsx November 02/12/2026
    /hr payslip ~/nov.xlsx 01/11/2026 30/11/2026 02/12/2026
    /hr payslip check November               + the table   (check needs no pay date)

A month is ``November``, ``Nov``, ``Nov 2026`` or ``11/2026``; without a year it is the latest such
month that has started. A pasted table must keep its tabs (copy the cells from Google Sheets or
Excel); a table whose tabs were lost can't be split safely, since names and positions contain spaces.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

MONTHS = {name.lower(): n for n, name in enumerate(calendar.month_name) if name}
MONTHS |= {name.lower(): n for n, name in enumerate(calendar.month_abbr) if name}
SHEET_SUFFIXES = (".xlsx", ".xlsm", ".csv", ".tsv", ".txt")


@dataclass(frozen=True)
class PayslipRequest:
    sheet: Path | None  # a file you sent; None when the table was pasted
    table: str  # the pasted table (tab-separated), or ""
    start: date
    end: date
    pay_date: date | None  # None for /hr payslip check


def date_word(text: str) -> date:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"'{text}' is not a date (use dd/mm/yyyy)")


def month(words: list[str], today: date) -> tuple[date, date] | None:
    """['November'], ['Nov', '2026'] or ['11/2026'] → its first and last day."""
    text = " ".join(words).strip().lower()
    if m := re.fullmatch(r"(\d{1,2})/(\d{4})", text):
        number, year = int(m.group(1)), int(m.group(2))
    elif m := re.fullmatch(r"([a-z]+)\.?(?:\s+(\d{4}))?", text):
        if m.group(1) not in MONTHS:
            return None
        number = MONTHS[m.group(1)]
        year = int(m.group(2)) if m.group(2) else today.year - (number > today.month)
    else:
        return None
    if not 1 <= number <= 12:
        return None
    return date(year, number, 1), date(year, number, calendar.monthrange(year, number)[1])


def is_sheet(word: str) -> bool:
    return word.lower().endswith(SHEET_SUFFIXES) or "/" in word and not re.fullmatch(r"[\d/]+", word)


def parse(text: str, today: date, need_pay: bool) -> PayslipRequest:
    """Raises ValueError with what to send instead."""
    head, _, table = text.strip().partition("\n")
    if "\t" in head:  # the table came straight after the command, with no month line
        raise ValueError("Put the month and pay date on the first line, e.g. /hr payslip November 02/12/2026, "
                         "then the table on the lines after it.")
    words = head.split()
    sheet = Path(words.pop(0)).expanduser() if words and is_sheet(words[0]) else None
    table = table.strip("\n")
    if sheet is None and not table:
        raise ValueError("Send the sheet file, or paste the table on the lines after the command.")
    if sheet is None and "\t" not in table:
        raise ValueError("The pasted table lost its columns (no tabs). Copy the cells straight from Google "
                         "Sheets or Excel, or send the sheet file instead.")
    pay = None
    if need_pay:
        if not words or not re.fullmatch(r"[\d/-]+", words[-1]):
            raise ValueError("Add the pay date (dd/mm/yyyy) after the month, e.g. November 02/12/2026.")
        pay = date_word(words.pop())
    if len(words) == 2 and all(re.fullmatch(r"[\d/-]+", w) for w in words):
        start, end = date_word(words[0]), date_word(words[1])
    elif (found := month(words, today)) is not None:
        start, end = found
    else:
        raise ValueError(f"'{' '.join(words) or 'nothing'}' is not a month (November, Nov 2026, 11/2026) "
                         "or two dates (dd/mm/yyyy dd/mm/yyyy).")
    if end < start:
        raise ValueError("The period ends before it starts.")
    return PayslipRequest(sheet, table if sheet is None else "", start, end, pay)
