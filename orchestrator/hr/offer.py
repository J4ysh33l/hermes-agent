"""``/hr offer <kind>``: an offer letter (internship, full-time or consultant) from your Word template,
made by script; only the duties come from a model, and only for a position not seen before (``duties``).

One template per kind in ``$HERMES_HOME/hr/templates/`` (``hr.offer_templates`` in brief.yaml):
``offer_internship.docx``, ``offer_fte.docx``, ``offer_consultant.docx``: the letter exactly as HR wrote
it, with square-bracket fields (any case; a field may appear more than once):

    [Name] [Position] [Email]
    [Date]                               today, the letter's date: "26 November 2026"
    [Start date]                         "1 December 2026"
    [End date]                           start + months − 1 day: "28 February 2027" (needs a tenure)
    [duration spelled] [duration number] "three", "3" (the tenure in months)
    [Monthly] [Annual]                   the pay: "₹15,000" and 12 × monthly "₹1,80,000"
    [duties and responsibilities]        a paragraph of its own (any bracket naming duties):
                                         one bullet per duty, each a copy of that paragraph
    [anything else]                      filled from a line you send with the same name, e.g.
                                         "Location: Mohali" fills [Location]

A bracket with no value stops the letter and is named, so a blank never reaches a candidate. Fields
filled inside one run keep that run's font (the bold name stays bold).

What you send::

    /hr offer internship
    Name: Asha Verma
    Position: Marketing Intern
    Start: 01/12/2026
    Tenure: 3 months                 (internship and consultant; a full-time offer may leave it out)
    Stipend: 15000                   (or Salary / Fee: a month; or CTC: a year)
    Email: asha@example.com          (optional; needed for /hr offer yes)

or one line: ``/hr offer internship Asha Verma, Marketing Intern, 01/12/2026, 3, 15000, asha@example.com``
(a full-time offer without a tenure: name, position, start, salary, email).

Also read:
- ``Month: June - July`` (or ``Period:``): starts on the 1st of the first month, the tenure is the months
  counted; with no year, the next time that month comes (June asked in November → next June).
- ``Stipend: Unpaid`` (or nil, none, 0): no pay table; ``hr.unpaid_line`` says it is unpaid.
- ``Key - value`` as well as ``Key: value``; a name in lower case is capitalised.
- Several people in one message: each ``Name:`` line starts a person; a line given once (e.g. one
  ``Stipend: Unpaid`` at the end, or one ``Position:`` at the top) applies to everyone missing it.
A message in some other shape is read by a model (``intake``), then checked here the same way.
"""

from __future__ import annotations

import calendar
import copy
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from orchestrator.brief.render import indian_grouping

from .docfill import TemplateError, _all_paragraphs

BRACKET = re.compile(r"\[([^\[\]\n]{1,60})\]")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
         "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
         "twenty", "twenty-one", "twenty-two", "twenty-three", "twenty-four", "twenty-five", "twenty-six",
         "twenty-seven", "twenty-eight", "twenty-nine", "thirty", "thirty-one", "thirty-two", "thirty-three",
         "thirty-four", "thirty-five", "thirty-six")
MAX_MONTHS = 36


@dataclass(frozen=True)
class Kind:
    name: str  # internship · fte · consultant
    label: str  # in replies: "Internship"
    role: str  # in the mail and the duties prompt: "internship", "full-time role", "consulting engagement"
    pay: str  # what the money is called: Stipend · Salary · Fee
    tenure: bool  # a tenure (months) is required


KINDS = {"internship": Kind("internship", "Internship", "internship", "Stipend", True),
         "fte": Kind("fte", "Full-time", "full-time role", "Salary", False),
         "consultant": Kind("consultant", "Consultant", "consulting engagement", "Fee", True)}
KIND_WORDS = {"internship": "internship", "intern": "internship", "fte": "fte", "full-time": "fte",
              "fulltime": "fte", "employee": "fte", "consultant": "consultant", "consulting": "consultant",
              "contract": "consultant"}
KEYS = {"name": "name", "full name": "name", "candidate": "name",
        "position": "position", "role": "position", "designation": "position", "title": "position",
        "start": "start", "start date": "start", "joining": "start", "date of joining": "start", "doj": "start",
        "tenure": "months", "months": "months", "duration": "months",
        "stipend": "pay", "salary": "pay", "fee": "pay", "monthly": "pay", "pay": "pay",
        "monthly stipend": "pay", "monthly salary": "pay", "monthly fee": "pay",
        "ctc": "annual", "annual": "annual", "annual ctc": "annual", "yearly": "annual",
        "email": "email", "mail": "email", "email id": "email",
        "month": "months", "period": "months", "internship period": "months", "duration of internship": "months"}
UNPAID = re.compile(r"(?i)^\s*(unpaid|nil|none|no stipend|not paid|0|zero|-)\s*\.?\s*$")
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m} | {
    m.lower(): i for i, m in enumerate(calendar.month_abbr) if m} | {"sept": 9}
PERIOD = re.compile(r"(?i)^\s*([a-z]+)\.?\s*(\d{4})?\s*(?:-|–|—|to|till|until)\s*([a-z]+)\.?\s*(\d{4})?\s*$")
ORDER = {True: ("name", "position", "start", "months", "pay", "email"),
         False: ("name", "position", "start", "pay", "email")}
# the template's own fields (lower case, spaces collapsed); anything else comes from your extra lines
OWN = ("name", "position", "email", "date", "start date", "end date", "duration spelled", "duration number",
       "monthly", "annual")


def kind_of(word: str) -> Kind | None:
    found = KIND_WORDS.get(word.strip().lower())
    return KINDS[found] if found else None


@dataclass(frozen=True)
class Offer:
    kind: Kind
    name: str
    position: str
    start: date
    months: int  # 0 = no fixed tenure (a full-time offer)
    monthly: int  # rupees a month
    email: str = ""
    annual: int = 0  # given as CTC; 0 = 12 × monthly
    extra: tuple[tuple[str, str], ...] = field(default=())  # your other lines: (bracket label, text)
    unpaid: bool = False  # Stipend: Unpaid: no pay table, hr.unpaid_line instead

    @property
    def end(self) -> date | None:
        """The day before the same date N months on; from 31 Jan, a month ends on the last of February."""
        if not self.months:
            return None
        later = add_months(self.start, self.months)
        return later if later.day != self.start.day else later - timedelta(days=1)

    @property
    def first(self) -> str:
        return self.name.split()[0] if self.name.split() else ""

    def values(self, today: date) -> dict[str, str]:
        """Bracket label (lower case) → its text. Tenure fields only when there is a tenure."""
        out = {"name": self.name, "position": self.position, "date": long_date(today),
               "start date": long_date(self.start),
               "monthly": "Nil" if self.unpaid else rupees(self.monthly),
               "annual": "Nil" if self.unpaid else rupees(self.annual or self.monthly * 12)}
        if self.email:
            out["email"] = self.email
        if self.months:
            out |= {"end date": long_date(self.end), "duration spelled": WORDS[self.months],
                    "duration number": str(self.months)}
        return {**dict(self.extra), **out}


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


def _amount(text: str) -> int | None:
    plain = re.sub(r"(?i)(rs\.?|inr|₹|/-|per (month|annum|year)|/(month|year|yr)|p\.?a\.?|pm|,|\s)", "", text)
    if m := re.fullmatch(r"(\d+(?:\.\d+)?)(lpa|lakhs?|l)?", plain.lower()):
        value = float(m.group(1)) * (100000 if m.group(2) else 1)
        return round(value) if value.is_integer() or m.group(2) else None
    return None


def period(text: str, today: date) -> tuple[date, int] | None:
    """'June - July' → (1 June of the next June on or after this month, 2); 'Jun 2027 to Aug 2027' too;
    one month name alone → 1 month. None when it is not month names."""
    words = text.strip()
    if m := PERIOD.match(words):
        first, y1, last, y2 = m.group(1).lower(), m.group(2), m.group(3).lower(), m.group(4)
    elif m := re.fullmatch(r"(?i)\s*([a-z]+)\.?\s*(\d{4})?\s*", words):
        first, y1, last, y2 = m.group(1).lower(), m.group(2), m.group(1).lower(), m.group(2)
    else:
        return None
    if first not in MONTHS or last not in MONTHS:
        return None
    a, b = MONTHS[first], MONTHS[last]
    if y1:
        year = int(y1)
    elif y2:
        year = int(y2) - (1 if b < a else 0)
    else:
        year = today.year + (1 if a < today.month else 0)
    months = (int(y2) * 12 + b) - (year * 12 + a) + 1 if y2 else (b - a) % 12 + 1
    return (date(year, a, 1), months) if 1 <= months <= MAX_MONTHS else None


def _lines(text: str) -> list[tuple[str, str]]:
    """Every 'Key: value' (or 'Key - value', 'Key = value') line as (label lower case, value)."""
    out = []
    for line in (ln.strip() for ln in text.split("\n") if ln.strip()):
        head, sep, value = line.partition(":")
        if not sep:
            for mark in (" - ", " – ", "=", " -", "- "):
                head, sep, value = line.partition(mark)
                if sep and " ".join(head.lower().split()) in KEYS:
                    break
                sep = ""
        label = " ".join(head.lower().split())
        if sep and label and value.strip():
            out.append((label, value.strip()))
    return out


def _split_keyed(pairs: list[tuple[str, str]]) -> tuple[dict[str, str], dict[str, str]]:
    keyed, extra = {}, {}
    for label, value in pairs:
        if label in KEYS:
            keyed[KEYS[label]] = value
        elif re.fullmatch(r"[a-z0-9 ()/&'-]{1,40}", label):
            extra[label] = " ".join(value.split())
    return keyed, extra


def _fields(text: str, kind: Kind) -> tuple[dict[str, str], dict[str, str]]:
    """('Key: value' lines read into our keys, your other 'Key: value' lines); or one line of values in
    ORDER split by commas."""
    keyed, extra = _split_keyed(_lines(text))
    if keyed:
        return keyed, extra
    parts = [p.strip() for p in text.replace("\n", ",").split(",") if p.strip()]
    if len(parts) > 3 and re.fullmatch(r"\d{4}", parts[3]):  # "1 Dec, 2026": the comma split the date
        parts = parts[:2] + [" ".join(parts[2:4])] + parts[4:]
    return dict(zip(ORDER[kind.tenure], parts, strict=False)), {}


def people(text: str) -> list[str]:
    """One message with several people → one block of 'Key: value' lines each. A person starts at each
    Name line; a key written only once in the message (e.g. 'Stipend: Unpaid' at the end) is given to
    every person who lacks it. One person (or no Name lines) → the text as it is."""
    pairs = _lines(text)
    starts = [i for i, (label, _v) in enumerate(pairs) if KEYS.get(label) == "name"]
    if len(starts) < 2:
        return [text]
    once: dict[str, tuple[str, str]] = {}
    counts: dict[str, int] = {}
    for label, value in pairs:
        k = KEYS.get(label, label)
        counts[k] = counts.get(k, 0) + 1
        once.setdefault(k, (label, value))
    blocks = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(pairs)
        own = pairs[start:end]
        have = {KEYS.get(label, label) for label, _v in own}
        if n == 0:  # lines before the first name belong to everyone
            own = pairs[:start] + own
            have |= {KEYS.get(label, label) for label, _v in pairs[:start]}
        shared = [once[k] for k, c in counts.items() if c == 1 and k not in have and k not in ("name", "email")]
        blocks.append("\n".join(f"{label}: {value}" for label, value in own + shared))
    return blocks


def _name(text: str) -> str:
    name = " ".join(text.split())
    return name.title() if name == name.lower() else name


def _position(text: str) -> str:
    """'Trainee software developer' → 'Trainee Software Developer'; anything with capitals inside stays."""
    words = " ".join(text.split())
    return words.title() if words[1:] == words[1:].lower() else words


def parse(text: str, kind: Kind, today: date | None = None) -> tuple[Offer | None, list[str]]:
    """(the offer, problems); every problem at once, so one resend fixes them all."""
    today = today or date.today()
    raw, extra = _fields(text, kind)
    span = period(raw["months"], today) if raw.get("months") and not re.match(r"\s*\d", raw["months"]) else None
    needed = [("Name", "name"), ("Position", "position")]
    needed += [] if span else [("Start date", "start")]
    needed += [("Tenure", "months")] if kind.tenure else []
    problems = [f"{label} is missing" for label, k in needed if not raw.get(k)]
    unpaid = bool(raw.get("pay") and UNPAID.match(raw["pay"]))
    if not raw.get("pay") and not raw.get("annual"):
        problems.append(f"{kind.pay} is missing (a month; or CTC: a year; or Unpaid)")
    if problems:
        return None, problems
    start, months, monthly, annual = None, 0, 0, 0
    if raw.get("start"):
        try:
            start = _date(raw["start"])
        except ValueError as exc:
            problems.append(str(exc))
    if span:
        start, months = start or span[0], span[1]
    elif raw.get("months"):
        if m := re.fullmatch(r"(\d{1,2})(?:\s*months?)?", raw["months"].strip().lower()):
            months = int(m.group(1))
            if not 1 <= months <= MAX_MONTHS:
                problems.append(f"Tenure must be 1 to {MAX_MONTHS} months, not {months}")
        else:
            problems.append(f"Tenure '{raw['months']}' is not a number of months (e.g. 6) or months (June - July)")
    if raw.get("pay") and not unpaid:
        monthly = _amount(raw["pay"]) or 0
        if not monthly:
            problems.append(f"{kind.pay} '{raw['pay']}' is not an amount in rupees a month (e.g. 15000) or Unpaid")
    if raw.get("annual") and not unpaid:
        annual = _amount(raw["annual"]) or 0
        if not annual:
            problems.append(f"CTC '{raw['annual']}' is not an amount in rupees a year (e.g. 600000 or 6 LPA)")
        elif not monthly:
            monthly = round(annual / 12)
    email = raw.get("email", "").strip()
    if email and not EMAIL.match(email):
        problems.append(f"'{email}' is not an email address")
    if problems:
        return None, problems
    return Offer(kind, _name(raw["name"]), _position(raw["position"]), start, months, monthly,
                 email, annual, tuple(sorted(extra.items())), unpaid), []


# ---- the Word letter ------------------------------------------------------------------------------


def _label(inner: str) -> str:
    return " ".join(inner.lower().split())


def _is_duties(label: str) -> bool:
    return "duties" in label or "responsibilit" in label


def brackets(path: Path) -> set[str]:
    """Every bracket field in the template, as written."""
    import docx

    return {m for p in _all_paragraphs(docx.Document(str(path))) for m in BRACKET.findall(p.text)}


def unknown(path: Path, values: dict[str, str]) -> list[str]:
    """Brackets in the template with no value: not ours, not given in your extra lines."""
    return sorted(f"[{b}]" for b in brackets(path) if _label(b) not in values and not _is_duties(_label(b)))


def _swap(text: str, values: dict[str, str]) -> str:
    return BRACKET.sub(lambda m: values.get(_label(m.group(1)), m.group(0)), text)


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


def _text_of(element) -> str:
    from docx.oxml.ns import qn

    return "".join(t.text or "" for t in element.iter(qn("w:t")))


def _blank(element) -> bool:
    from docx.oxml.ns import qn

    return element.tag == qn("w:p") and not _text_of(element).strip() and not element.xpath(".//w:drawing")


def unpaid(document, line: str, drop: tuple[str, ...]) -> None:
    """No pay table: each table holding [Monthly] / [Annual] goes with the blank line after it; the line that
    introduced it ("…as follows:") becomes ``line`` (or ``line`` is put in the table's place); paragraphs
    starting with any of ``drop`` go."""
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph

    body = document.element.body
    for table in [t for t in body.iter(qn("w:tbl")) if re.search(r"(?i)\[\s*(monthly|annual)\s*\]", _text_of(t))]:
        before = table.getprevious()
        while before is not None and _blank(before):
            before = before.getprevious()
        after = table.getnext()
        if after is not None and _blank(after):
            after.getparent().remove(after)
        if before is not None and before.tag == qn("w:p") and _text_of(before).rstrip().endswith(":"):
            _set_text(Paragraph(before, document._body), line)
        else:
            clone = copy.deepcopy(before) if before is not None and before.tag == qn("w:p") else None
            if clone is None:
                table.addprevious(document.add_paragraph(line)._p)
            else:
                table.addprevious(clone)
                para = Paragraph(clone, document._body)
                if para.runs:
                    _set_text(para, line)
                else:
                    para.add_run(line)
        table.getparent().remove(table)
    starts = tuple(d.strip().lower() for d in drop if d.strip())
    for paragraph in list(document.paragraphs):
        if starts and paragraph.text.strip().lower().startswith(starts):
            paragraph._p.getparent().remove(paragraph._p)


def _attr(element, name: str) -> str:
    return next((v for k, v in element.attrib.items() if k.rsplit("}", 1)[-1] == name), "")


def signature(document) -> bool:
    """Word's Signature Line box is drawn with a white background. Word puts a signature picture laid over
    it in front, but LibreOffice (the PDF) puts the box in front and hides most of the signature. So a
    paragraph holding both becomes: the picture inline at its own size, a rule, the signer's name (bold)
    and title from the box, as text. True when a box was replaced."""
    import io

    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Emu
    from docx.text.paragraph import Paragraph

    done = False
    for paragraph in list(document.paragraphs):
        p = paragraph._p
        boxes = p.xpath('.//*[local-name()="signatureline"]')
        anchors = p.xpath('.//*[local-name()="anchor"]')
        blips = p.xpath('.//*[local-name()="anchor"]//*[local-name()="blip"]')
        if not (boxes and anchors and blips):
            continue
        blob = document.part.related_parts[blips[0].get(qn("r:embed"))].blob
        extent = anchors[0].xpath('./*[local-name()="extent"]')[0]
        signer, title = _attr(boxes[0], "suggestedsigner"), _attr(boxes[0], "suggestedsigner2")
        for child in list(p):
            if child.tag != qn("w:pPr"):
                p.remove(child)
        mark = p.find(qn("w:pPr"))
        spacing = mark.find(qn("w:spacing")) if mark is not None else None
        if spacing is not None:
            spacing.set(qn("w:after"), "0")
        paragraph.add_run().add_picture(io.BytesIO(blob), width=Emu(int(extent.get("cx"))),
                                        height=Emu(int(extent.get("cy"))))
        last = p
        for n, text in enumerate(t for t in (signer, title) if t):
            line = copy.deepcopy(p)
            for child in list(line):
                if child.tag != qn("w:pPr"):
                    line.remove(child)
            ppr = line.find(qn("w:pPr"))
            if ppr is None:
                ppr = OxmlElement("w:pPr")
                line.insert(0, ppr)
            for old in ppr.findall(qn("w:jc")) + ppr.findall(qn("w:spacing")):
                ppr.remove(old)
            gap = OxmlElement("w:spacing")
            gap.set(qn("w:before"), "0")
            gap.set(qn("w:after"), "0")
            ppr.append(gap)
            if n == 0:  # the signature rule: a line above the name, about a third of the page wide
                border, top = OxmlElement("w:pBdr"), OxmlElement("w:top")
                for key, value in (("val", "single"), ("sz", "8"), ("space", "4"), ("color", "auto")):
                    top.set(qn(f"w:{key}"), value)
                border.append(top)
                ppr.append(border)
                indent = OxmlElement("w:ind")
                indent.set(qn("w:right"), "5600")
                ppr.append(indent)
            last.addnext(line)
            last = line
            run = Paragraph(line, paragraph._parent).add_run(text)
            mark_font = ppr.find(qn("w:rPr"))
            if mark_font is not None:  # the paragraph's own font and colour
                run._r.insert(0, copy.deepcopy(mark_font))
            run.bold = n == 0
        done = True
    return done


def make(template: Path, offer: Offer, duties: tuple[str, ...], out: Path, today: date,
         unpaid_line: str = "", unpaid_drop: tuple[str, ...] = ()) -> None:
    import docx

    values = offer.values(today)
    bad = unknown(template, values)
    if bad:
        hint = (" (the tenure fields need a Tenure: line)" if any(_label(b[1:-1]) in OWN for b in bad) else "")
        raise TemplateError(f"The {offer.kind.label.lower()} template has fields with no value: " + ", ".join(bad) +
                            hint + ". Add a line for each, e.g. \"" + bad[0][1:-1] + ": …\".")
    if not duties:
        raise TemplateError("No duties to put in the letter.")
    document = docx.Document(str(template))
    if offer.unpaid:
        unpaid(document, unpaid_line or "This is an unpaid position: no pay is due for it.", unpaid_drop)
    signature(document)
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
