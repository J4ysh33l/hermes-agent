"""Hide people's details from the model, then check its answer before putting them back.

Before an HR mail goes to Gemini, ``hide`` swaps names, emails, phone numbers, links, amounts and ID
numbers (PAN, Aadhaar, IFSC, account numbers) for placeholders such as ``[NAME_1]``. The same value
always gets the same placeholder. The table stays on the host; the model never sees it.

``restore`` checks the model's draft before anything is put back:

- a placeholder written slightly differently (``[name_1]``, ``{NAME_1}``, ``[NAME 1]``, a bare
  ``NAME_1``) is rewritten to its exact form and listed as a fix;
- a placeholder the mail never had (``[NAME_7]``) is a problem: the model made someone up;
- an email, phone number, link, amount or ID number written out in the draft is a problem: every
  real one was hidden, so the model invented it.

With any problem nothing is restored; the caller asks again or refuses. Names are found from the
mail's own headers (sender, To, Cc), the sign-off line and the names you list in ``hr.redact_names``;
a name that appears nowhere of those can still reach the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

KINDS = ("NAME", "EMAIL", "PHONE", "LINK", "AMOUNT", "ID")

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
LINK = re.compile(r"\b(?:https?://|www\.)[^\s<>\"')\]]+", re.IGNORECASE)
PHONE = re.compile(r"(?<![\w+])(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)|(?<![\w+])\+\d[\d\s-]{8,14}\d(?!\d)"
                   r"|(?<![\w+-])\d{3,5}[\s-]\d{3,4}[\s-]\d{4}(?![\w-])")  # landlines: 022 2345 6789
AMOUNT = re.compile(r"(?:₹|\bRs\.?|\bINR)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:lakhs?|lacs?|crores?|k|/-))?"
                    r"|\b\d[\d,]*(?:\.\d+)?\s?(?:lakhs?|lacs?|crores?|lpa|ctc|k|/-)(?!\w)", re.IGNORECASE)
ID = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"  # PAN
                r"|\b[A-Z]{4}0[A-Z0-9]{6}\b"  # IFSC
                r"|(?<!\d)\d{4}\s\d{4}\s\d{4}(?!\d)"  # Aadhaar as written
                r"|(?<![\d/-])(?<!\d\.)\d{6,}(?![\d/-]|\.\d)")  # account, employee, UAN numbers (a full stop may end it)
SIGN_OFF = re.compile(r"^\s*(?:regards|best regards|warm regards|kind regards|thanks(?: and regards)?|"
                      r"thank you|sincerely|yours (?:sincerely|faithfully|truly)|best)\b[\s,.!-]*$",
                      re.IGNORECASE | re.MULTILINE)
SIGNED_NAME = re.compile(r"^\s*([A-Z][a-zA-Z.'-]+(?:\s+[A-Z][a-zA-Z.'-]+){0,3})\s*$")

EXACT = re.compile(r"\[(" + "|".join(KINDS) + r")_(\d+)\]")
LOOSE = re.compile(r"[\[{(<]{1,2}\s*(" + "|".join(KINDS) + r")[\s_-]*(\d+)\s*[\]})>]{1,2}"  # wrong brackets/case/space
                   r"|(?<![\w\[])(" + "|".join(KINDS) + r")_(\d+)(?![\w\]])", re.IGNORECASE)  # brackets dropped
# Order matters: a link holds an email-like part, and an amount or ID must not be split by the phone rule.
FINDERS = (("LINK", LINK), ("EMAIL", EMAIL), ("AMOUNT", AMOUNT), ("PHONE", PHONE), ("ID", ID))
LEAKS = {"EMAIL": EMAIL, "LINK": LINK, "PHONE": PHONE, "AMOUNT": AMOUNT, "ID": ID}


@dataclass(frozen=True)
class Restored:
    text: str  # the draft with real values back; "" when there are problems
    fixes: tuple[str, ...]  # placeholders rewritten to their exact form
    problems: tuple[str, ...]  # why the draft can't be used as it is


def signed_names(text: str) -> list[str]:
    """The name on the line after a sign-off ("Regards,\\nAsha Verma")."""
    names = []
    lines = text.splitlines()
    for n, line in enumerate(lines[:-1]):
        if SIGN_OFF.fullmatch(line):
            nxt = next((ln for ln in lines[n + 1:] if ln.strip()), "")
            if match := SIGNED_NAME.match(nxt):
                names.append(match.group(1))
    return names


def _name_variants(names: list[str]) -> list[str]:
    """Full names first, then each part of three letters or more ("Asha Verma", "Asha", "Verma").
    Shorter ones ("HR", a mailbox's display name) are left alone: hiding them only confuses the model."""
    full = {" ".join(n.split()) for n in names if n and "@" not in n and len(n.strip()) >= 3}
    parts = {p for n in full for p in n.split() if len(p) >= 3 and p[0].isupper()}
    return sorted(full | parts, key=len, reverse=True)


class _Table:
    def __init__(self) -> None:
        self.by_value: dict[tuple[str, str], str] = {}
        self.table: dict[str, str] = {}
        self.count = dict.fromkeys(KINDS, 0)

    def mark(self, kind: str, value: str) -> str:
        key = (kind, value.lower() if kind in ("NAME", "EMAIL") else value)
        if key not in self.by_value:
            self.count[kind] += 1
            place = f"[{kind}_{self.count[kind]}]"
            self.by_value[key] = place
            self.table[place] = value
        return self.by_value[key]


def hide(texts: list[str], names: list[str]) -> tuple[list[str], dict[str, str]]:
    """Hide the same values the same way across several texts (subject and body). Returns the texts
    the model may see and the table (placeholder → real value), which never leaves the host.
    Names match as written (capitalised), so "Will" the word is not taken for Will the person."""
    table = _Table()
    every = _name_variants(names + [n for t in texts for n in signed_names(t)])
    name_re = re.compile(r"(?<![\w\[])(" + "|".join(map(re.escape, every)) + r")(?![\w\]])") if every else None
    out = []
    for text in texts:
        for kind, finder in FINDERS:
            text = finder.sub(lambda m, k=kind: table.mark(k, m.group(0)), text)
        if name_re:
            text = name_re.sub(lambda m: table.mark("NAME", m.group(0)), text)
        out.append(text)
    return out, table.table


def restore(draft: str, table: dict[str, str]) -> Restored:
    fixes: list[str] = []

    def exact(match: re.Match) -> str:
        kind = (match.group(1) or match.group(3)).upper()
        place = f"[{kind}_{int(match.group(2) or match.group(4))}]"
        if match.group(0) != place:
            fixes.append(f"{match.group(0)} → {place}")
        return place

    text = LOOSE.sub(lambda m: m.group(0) if EXACT.fullmatch(m.group(0)) else exact(m), draft)
    used = dict.fromkeys(m.group(0) for m in EXACT.finditer(text))
    problems = [f"{p} is not in the mail (the model made it up)" for p in used if p not in table]
    bare = EXACT.sub(" ", text)
    for kind, finder in LEAKS.items():
        problems += [f"{kind.lower()} {m.group(0).strip()!r} is not in the mail" for m in finder.finditer(bare)]
    if problems:
        return Restored("", tuple(fixes), tuple(problems))
    return Restored(EXACT.sub(lambda m: table[m.group(0)], text), tuple(fixes), ())
