"""``/hr offer``: an internship offer letter from your Word template, made by script; only the
duties come from a model, and only for a position not seen before (``duties``).

Your template is ``$HERMES_HOME/hr/templates/offer_intern.docx``, the letter exactly as HR wrote it,
with these square-bracket fields (any case; a field may appear more than once):

    [Name]                               the person's full name
    [Position]                           e.g. Marketing Intern
    [Start date]                         "1 December 2026"
    [End date]                           start + months − 1 day: "28 February 2027"
    [duration spelled] [duration number] "three", "3"
    [Monthly] [Annual]                   the stipend: "₹15,000" and 12 × monthly "₹1,80,000"
    [4-5 duties and responsibilities]    a paragraph of its own: becomes one bullet per duty,
                                         each a copy of that paragraph (same bullet and font)

A bracket the script does not know stops the letter and is named, so a typo never reaches a
candidate. Fields filled inside one run keep that run's font (the bold name stays bold).

What you send::

    /hr offer
    Name: Asha Verma
    Position: Marketing Intern
    Start: 01/12/2026
    Months: 3
    Stipend: 15000
    Email: asha@example.com          (optional; needed for /hr offer yes)

or one line: ``/hr offer Asha Verma, Marketing Intern, 01/12/2026, 3, 15000, asha@example.com``.
"""

from __future__ import annotations

import calendar
import copy
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from orchestrator.brief.render import indian_grouping

from .docfill import TemplateError, _all_paragraphs

BRACKET = re.compile(r"\[([^\[\]\n]{1,60})\]")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
         "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
         "twenty", "twenty-one", "twenty-two", "twenty-three", "twenty-four")
MAX_MONTHS = 24
KEYS = {"name": "name", "full name": "name", "candidate": "name", "intern": "name",
        "position": "position", "role": "position", "designation": "position",
        "start": "start", "start date": "start", "joining": "start", "date of joining": "start", "doj": "start",
        "months": "months", "duration": "months", "duration months": "months",
        "stipend": "stipend", "monthly": "stipend", "monthly stipend": "stipend", "salary": "stipend",
        "email": "email", "mail": "email", "email id": "email"}
ORDER = ("name", "position", "start", "months", "stipend", "email")
# the template's bracket text (lower case, spaces collapsed) → the value it takes
FIELDS = {"name": "name", "position": "position", "start date": "start_date", "end date": "end_date",
          "duration spelled": "duration_words", "duration number": "duration_number",
          "monthly": "monthly", "annual": "annual"}


@dataclass(frozen=True)
class Offer:
    name: str
    position: str
    start: date
    months: int
    stipend: int  # rupees a month
    email: str = ""

    @property
    def end(self) -> date:
        """The day before the same date N months on; from 31 Jan, a month ends on the last of February."""
        later = add_months(self.start, self.months)
        return later if later.day != self.start.day else later - timedelta(days=1)

    @property
    def first(self) -> str:
        return self.name.split()[0] if self.name.split() else ""

    def values(self) -> dict[str, str]:
        return {"name": self.name, "position": self.position, "start_date": long_date(self.start),
                "end_date": long_date(self.end), "duration_words": WORDS[self.months],
                "duration_number": str(self.months), "monthly": rupees(self.stipend),
                "annual": rupees(self.stipend * 12)}


def add_months(day: date, months: int) -> date:
    total = day.month - 1 + months
    year, month = day.year + total // 12, total % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def long_date(day: date) -> str:
    return f"{day.day} {day:%B %Y}"


def rupees(amount: int) -> str:
    return "₹" + indian_grouping(float(amount))


def _date(text: str) -> date:
    text = " ".join(text.replace(",", " ").split())
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"'{text}' is not a date (use dd/mm/yyyy)")


def _fields(text: str) -> dict[str, str]:
    """'Key: value' lines, or one line of values in ORDER split by commas (or semicolons)."""
    lines = [ln.strip() for ln in re.split(r"[\n;]", text) if ln.strip()]
    keyed = {}
    for line in lines:
        head, sep, value = line.partition(":")
        name = KEYS.get(" ".join(head.lower().split()))
        if sep and name:
            keyed[name] = value.strip()
    if keyed:
        return keyed
    parts = [p.strip() for p in text.replace("\n", ",").split(",") if p.strip()]
    if len(parts) > 3 and re.fullmatch(r"\d{4}", parts[3]):  # "1 Dec, 2026": the comma split the date
        parts = parts[:2] + [" ".join(parts[2:4])] + parts[4:]
    return dict(zip(ORDER, parts, strict=False))


def parse(text: str) -> tuple[Offer | None, list[str]]:
    """(the offer, problems); every problem at once, so one resend fixes them all."""
    raw = _fields(text)
    problems = [f"{label} is missing" for label, k in (("Name", "name"), ("Position", "position"),
                                                       ("Start date", "start"), ("Months", "months"),
                                                       ("Stipend", "stipend")) if not raw.get(k)]
    if problems:
        return None, problems
    start = months = stipend = None
    try:
        start = _date(raw["start"])
    except ValueError as exc:
        problems.append(str(exc))
    if m := re.fullmatch(r"(\d{1,2})(?:\s*months?)?", raw["months"].strip().lower()):
        months = int(m.group(1))
        if not 1 <= months <= MAX_MONTHS:
            problems.append(f"Months must be 1 to {MAX_MONTHS}, not {months}")
    else:
        problems.append(f"Months '{raw['months']}' is not a number of months")
    amount = re.sub(r"(?i)(rs\.?|inr|₹|/-|per month|/month|pm|,|\s)", "", raw["stipend"])
    if amount.isdigit():
        stipend = int(amount)
    else:
        problems.append(f"Stipend '{raw['stipend']}' is not an amount in rupees (e.g. 15000)")
    email = raw.get("email", "").strip()
    if email and not EMAIL.match(email):
        problems.append(f"'{email}' is not an email address")
    name, position = " ".join(raw["name"].split()), " ".join(raw["position"].split())
    if problems:
        return None, problems
    return Offer(name, position, start, months, stipend, email), []


# ---- the Word letter ------------------------------------------------------------------------------


def _label(inner: str) -> str:
    return " ".join(inner.lower().split())


def _is_duties(label: str) -> bool:
    return "duties" in label or "responsibilit" in label


def brackets(path: Path) -> set[str]:
    """Every bracket field in the template, as written."""
    import docx

    return {m for p in _all_paragraphs(docx.Document(str(path))) for m in BRACKET.findall(p.text)}


def unknown(path: Path) -> list[str]:
    return sorted(f"[{b}]" for b in brackets(path) if _label(b) not in FIELDS and not _is_duties(_label(b)))


def _swap(text: str, values: dict[str, str]) -> str:
    return BRACKET.sub(lambda m: values[FIELDS[_label(m.group(1))]] if _label(m.group(1)) in FIELDS
                       else m.group(0), text)


def _set_text(paragraph, text: str) -> None:
    """The whole paragraph's text in its first run (keeps that run's font); other runs emptied."""
    runs = paragraph.runs
    runs[0].text = text
    for run in runs[1:]:
        run.text = ""


def _bullets(paragraph, items: tuple[str, ...]) -> None:
    """The duties placeholder paragraph becomes one paragraph per duty: copies of it, so each keeps
    its bullet, indent and font."""
    from docx.text.paragraph import Paragraph

    anchor = paragraph._p
    for item in items[1:][::-1]:
        clone = copy.deepcopy(anchor)
        anchor.addnext(clone)
        _set_text(Paragraph(clone, paragraph._parent), item)
    _set_text(paragraph, items[0])


def make(template: Path, offer: Offer, duties: tuple[str, ...], out: Path) -> None:
    import docx

    bad = unknown(template)
    if bad:
        raise TemplateError("The offer template has fields Hermes can't fill: " + ", ".join(bad) +
                            ". Rename them to one of: " + ", ".join(f"[{k}]" for k in FIELDS) +
                            ", or [duties and responsibilities].")
    if not duties:
        raise TemplateError("No duties to put in the letter.")
    document = docx.Document(str(template))
    values = offer.values()
    placed = False
    for paragraph in list(_all_paragraphs(document)):
        found = BRACKET.findall(paragraph.text)
        if not found:
            continue
        if any(_is_duties(_label(b)) for b in found):
            if paragraph.text.strip() != f"[{found[0]}]" or len(found) != 1:
                raise TemplateError("The duties field must be a paragraph of its own, e.g. "
                                    "[4-5 duties and responsibilities] alone on a bullet line.")
            _bullets(paragraph, duties)
            placed = True
            continue
        for run in paragraph.runs:  # a field inside one run: replaced there, the run's font kept
            if "[" in run.text:
                run.text = _swap(run.text, values)
        if BRACKET.search(paragraph.text):  # Word split a field over several runs
            _set_text(paragraph, _swap(paragraph.text, values))
    if not placed:
        raise TemplateError("The offer template has no [duties and responsibilities] paragraph.")
    out.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(out))


def key_part(offer: Offer) -> str:
    """A folder name for this letter: 'asha-verma'."""
    return re.sub(r"[^a-z0-9]+", "-", offer.name.lower()).strip("-")[:40] or "intern"


def file_stem(offer: Offer) -> str:
    safe = re.sub(r"[^\w .-]", "", offer.name).strip() or "Intern"
    return f"Offer Letter - {safe}"
