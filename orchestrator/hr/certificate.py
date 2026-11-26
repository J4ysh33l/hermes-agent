"""``/hr certificate``: an experience (completion) certificate from your SVG design, numbered by script.

The template ``$HERMES_HOME/hr/templates/certificate_experience.svg`` is your design with three fields
where the changing text goes: ``{{ref}}``, ``{{name}}`` (with ``{{name_size}}``) and ``{{paragraph}}``;
everything else (logo, shapes, the CEO's signature) is drawn as it is. Chrome turns it into an A4
landscape PDF.

The reference number is ``HR/<year>/<month>/<number>``: the year and month of the day it is made, and a
running number one above the last one given (kept in ``$HERMES_HOME/hr/certificates.json`` with every
certificate made, and in your private repo when the store is set up). ``/hr certificate next 160`` sets
the next number. Numbers are given when the certificate is made; dropping the newest ones gives their
numbers back.

The paragraph: a position that reads as technical (``hr.tech_words``) gets the software wording of your
sample; any other position gets a general one (``hr.certificate_texts``). ``Pronoun: he`` / ``she`` /
``they`` sets the pronouns; without it the text says "they" (past tense, so it always reads right).
No model is used.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import calendar

from .offer import EMAIL, _date, _lines, _position, add_months, long_date, period

FILE = "certificates.json"
TEMPLATE = "certificate_experience.svg"
TECH_WORDS = ("software", "developer", "development", "engineer", "engineering", "sde", "programmer", "devops",
              "frontend", "front-end", "backend", "back-end", "full stack", "full-stack", "fullstack", "data",
              "machine learning", "ml", "ai", "qa", "test", "cloud", "it", "technical", "tech", "android", "ios",
              "web", "app", "security", "database", "analyst")
TEXTS = {
    "tech": "This is to certify that {name} has worked with {company} as {a_position} from {start} to {end}. "
            "During this period, {name} contributed to software development activities and supported the "
            "engineering team in carrying out assigned technical responsibilities. {He} demonstrated technical "
            "proficiency, problem-solving abilities, professionalism, and dedication towards {his} work. We "
            "appreciate {his} valuable contribution and wish {him} continued success in {his} future endeavors.",
    "general": "This is to certify that {name} has worked with {company} as {a_position} from {start} to {end}. "
               "During this period, {name} carried out the responsibilities of the role and supported the team "
               "in its day-to-day work. {He} demonstrated commitment, professionalism, and dedication towards "
               "{his} work. We appreciate {his} valuable contribution and wish {him} continued success in "
               "{his} future endeavors.",
}
PRONOUNS = {"he": ("He", "his", "him"), "she": ("She", "her", "her"), "they": ("They", "their", "them")}
KEYS = {"name": "name", "full name": "name", "candidate": "name", "position": "position", "role": "position",
        "designation": "position", "title": "position", "start": "start", "start date": "start", "from": "start",
        "joining": "start", "date of joining": "start", "doj": "start", "end": "end", "end date": "end",
        "to": "end", "till": "end", "until": "end", "last day": "end", "relieving": "end",
        "email": "email", "mail": "email", "email id": "email", "pronoun": "pronoun", "pronouns": "pronoun",
        "month": "period", "months": "period", "period": "period", "duration": "period", "tenure": "period",
        "gender": "pronoun"}
PERSONAL = ("name", "email", "pronoun")  # never shared from one person to the others
GENDER = {"male": "he", "m": "he", "female": "she", "f": "she"}


class CertificateError(Exception):
    """Shown as it is; no certificate was made."""


@dataclass(frozen=True)
class Person:
    name: str
    position: str
    start: date
    end: date
    email: str = ""
    pronoun: str = "they"

    @property
    def first(self) -> str:
        return self.name.split()[0]


def is_tech(position: str, words: tuple[str, ...] = TECH_WORDS) -> bool:
    plain = " " + re.sub(r"[^a-z0-9+#-]+", " ", position.lower()) + " "
    return any(f" {w} " in plain for w in words)


def article(position: str) -> str:
    """'an SDE Intern', 'a Software Developer', 'an HR Executive', 'a UX Designer'."""
    first = position.split()[0] if position.split() else ""
    if first.isupper() and len(first) > 1:  # an acronym: by the sound of its first letter
        vowel = first[0] in "AEFHILMNORSX"
    else:
        vowel = first[:1].lower() in "aeiou" and not first.lower().startswith(("uni", "use", "usu", "eu", "one"))
    return ("an " if vowel else "a ") + position


def parse(text: str, today: date) -> tuple[list[Person], list[str]]:
    """Each Name line starts a person; a line given once is for everyone. (people, problems). A line that is
    not 'Key: value' (or a key not known) is a problem too, so nothing you wrote is quietly left out."""
    read = _lines(text)
    pairs = [(KEYS.get(label, ""), value) for label, value in read]
    known = {f"{label}\0{value}" for label, value in read if label in KEYS}
    stray = [ln.strip() for ln in text.splitlines() if ln.strip() and not any(
        ln.strip().lower().startswith(k.split("\0")[0]) and k.split("\0")[1] in ln for k in known)]
    starts = [i for i, (k, _v) in enumerate(pairs) if k == "name"]
    if not starts:
        return [], ["Name is missing (Name: …, Position: …, Start: dd/mm/yyyy, End: dd/mm/yyyy)"]
    counts: dict[str, int] = {}
    for k, _v in pairs:
        counts[k] = counts.get(k, 0) + 1
    once = {k: v for k, v in pairs if counts.get(k) == 1}
    people, problems = [], [f"Not understood: '{line[:60]}'" for line in stray]
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(pairs)
        own = dict(pairs[:start] if n == 0 else []) | dict(pairs[start:end])
        raw = {**{k: v for k, v in once.items() if k not in PERSONAL}, **own}
        who = f"{raw['name']}: " if len(starts) > 1 else ""
        span = period(raw["period"], today, past=True) if raw.get("period") else None
        if raw.get("period") and not span:
            problems.append(f"{who}'{raw['period']}' is not months (e.g. June - July 2026)")
            continue
        if span and not raw.get("start"):
            raw["start"] = span[0].strftime("%d/%m/%Y")
        if span and not raw.get("end"):
            last = add_months(span[0], span[1] - 1)
            raw["end"] = last.replace(day=calendar.monthrange(last.year, last.month)[1]).strftime("%d/%m/%Y")
        missing = [label for label, k in (("Position", "position"), ("Start date", "start"), ("End date", "end"))
                   if not raw.get(k)]
        if missing:
            problems += [f"{who}{m} is missing" for m in missing]
            continue
        try:
            first, last = _date(raw["start"]), _date(raw["end"])
        except ValueError as exc:
            problems.append(f"{who}{exc}")
            continue
        if last < first:
            problems.append(f"{who}the end date {long_date(last)} is before the start {long_date(first)}")
            continue
        if last > today:
            problems.append(f"{who}the end date {long_date(last)} has not come yet")
            continue
        email = raw.get("email", "").strip()
        if email and not EMAIL.match(email):
            problems.append(f"{who}'{email}' is not an email address")
            continue
        said = raw.get("pronoun", "they").strip().lower().split("/")[0]
        pronoun = GENDER.get(said, said)
        if pronoun not in PRONOUNS:
            problems.append(f"{who}Pronoun '{raw['pronoun']}' should be he, she or they")
            continue
        name = " ".join(raw["name"].split())
        people.append(Person(name.title() if name == name.lower() else name, _position(raw["position"]),
                             first, last, email, pronoun))
    return people, problems


def paragraph(p: Person, company: str, texts: dict[str, str] | None = None,
              words: tuple[str, ...] = TECH_WORDS) -> str:
    texts = {**TEXTS, **(texts or {})}
    he, his, him = PRONOUNS[p.pronoun]
    text = texts["tech" if is_tech(p.position, words) else "general"]
    return text.format(name=p.name, first=p.first, company=company, position=p.position,
                       a_position=article(p.position), start=long_date(p.start), end=long_date(p.end),
                       He=he, his=his, him=him, he=he.lower())


# ---- reference numbers ---------------------------------------------------------------------------------


class Register:
    """``certificates.json``: {"last": 159, "issued": [{"ref", "name", "position", "start", "end", "made"}]}."""

    def __init__(self, home: Path) -> None:
        self.path = home / FILE
        self.data = (json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file()
                     else {"last": 0, "issued": []})

    @property
    def last(self) -> int:
        return int(self.data.get("last", 0))

    def take(self, p: Person, today: date) -> str:
        number = self.last + 1
        ref = f"HR/{today.year}/{today.month}/{number:04d}"
        self.data["last"] = number
        self.data.setdefault("issued", []).append(
            {"ref": ref, "number": number, "name": p.name, "position": p.position, "start": p.start.isoformat(),
             "end": p.end.isoformat(), "made": today.isoformat()})
        return ref

    def give_back(self, refs: list[str]) -> list[str]:
        """Numbers of dropped certificates, only from the newest down (no gaps reused)."""
        back = []
        issued = self.data.setdefault("issued", [])
        while issued and issued[-1]["ref"] in refs and issued[-1]["number"] == self.last:
            back.append(issued.pop()["ref"])
            self.data["last"] = self.last - 1
        return back

    def set_next(self, number: int) -> None:
        self.data["last"] = number - 1

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=1, ensure_ascii=False)
        tmp.replace(self.path)


# ---- the PDF -------------------------------------------------------------------------------------------


def name_size(name: str) -> float:
    """The big name: 44 px like the design, smaller for a long name so it stays inside the page."""
    return round(min(44.0, 600 / max(1, 0.62 * len(name))), 1)


def fill(svg: str, ref: str, name: str, text: str) -> str:
    for field in ("{{ref}}", "{{name}}", "{{paragraph}}"):
        if field not in svg:
            raise CertificateError(f"The certificate template has no {field} field.")
    return (svg.replace("{{ref}}", html.escape(ref)).replace("{{name_size}}", str(name_size(name)))
            .replace("{{name}}", html.escape(name)).replace("{{paragraph}}", html.escape(text)))


def chrome() -> str:
    for candidate in (os.environ.get("CHROME_PATH"), os.environ.get("CHROME_BIN"), "google-chrome", "chromium",
                      "chromium-browser", "chrome", "/opt/pw-browsers/chromium/chrome-linux/chrome"):
        found = candidate and (shutil.which(candidate) or (candidate if Path(candidate).is_file() else None))
        if found:
            return found
    raise CertificateError("No Chrome or Chromium to make the PDF (set CHROME_PATH in .env).")


def render(svg: str, out: Path) -> Path:
    """The filled SVG → one A4 landscape PDF page, through headless Chrome."""
    page = ("<!doctype html><html><head><meta charset='utf-8'><style>@page{size:297mm 210mm;margin:0}"
            "html,body{margin:0;padding:0}svg{display:block;width:297mm;height:210mm}</style></head><body>"
            + svg[svg.index("<svg"):] + "</body></html>")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "certificate.html"
        src.write_text(page, encoding="utf-8")
        done = subprocess.run([chrome(), "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                               f"--user-data-dir={tmp}/profile", f"--print-to-pdf={out}", src.as_uri()],
                              capture_output=True, text=True, timeout=120, check=False)
    if done.returncode != 0 or not out.is_file():
        raise CertificateError(f"Chrome made no PDF: {(done.stderr or done.stdout).strip()[-300:]}")
    return out


def file_stem(p: Person) -> str:
    safe = re.sub(r"[^\w .-]", "", p.name).strip() or "Certificate"
    return f"Experience Certificate - {safe}"


def key_part(p: Person) -> str:
    return re.sub(r"[^a-z0-9]+", "-", p.name.lower()).strip("-")[:40] or "person"
