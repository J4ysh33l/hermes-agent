"""An offer request in a shape ``offer.parse`` does not read → a model lists the people in it as
``Key: value`` lines, which ``offer.parse`` then checks like any typed request.

Only used when the plain reading fails (a missing field, a sentence instead of lines, a pasted table).
Unlike the duties call, this one has to send your message as it is (names, emails, months) to Google,
because that is what it reads. Models are tried in order (``hr.duties_models``: Gemma 4 31B, Gemma 4
26B, Gemini 3.1 Flash-Lite, 3.5 Flash-Lite, 2.5 Flash); the next only when one fails or answers nothing usable.
The model copies; it is told never to fill a gap, so a value you did not write comes back missing and
the reply asks you for it.
"""

from __future__ import annotations

import json
import re
from datetime import date

from orchestrator import llm
from orchestrator.brief.net import HttpError

PROMPT = """Read this request for {role} offer letters and list every person it is for.
Today is {today}.
For each person copy, exactly as written:
- name
- position (the role or designation)
- start: the start date as dd/mm/yyyy, or "" when only months are given
- period: the months as words, e.g. "June - July" or "June 2027 - August 2027", or ""
- months: the length in months as digits, or ""
- pay: "unpaid" if it says unpaid / no stipend; else the amount a month in rupees as digits; or ""
- email: or ""
A value written once for everyone (e.g. "Stipend: Unpaid" at the end) applies to every person.
Never guess or invent a value: leave it "" when it is not written.
Answer JSON only: {{"people": [{{"name": "", "position": "", "start": "", "period": "", "months": "", "pay": "", "email": ""}}]}}

Request:
<<<
{text}
>>>"""
FIELDS = ("name", "position", "start", "period", "months", "pay", "email")
SCHEMA = {"type": "object", "properties": {"people": {"type": "array", "items": {
    "type": "object", "properties": {f: {"type": "string"} for f in FIELDS}}}}, "required": ["people"]}
LINES = {"name": "Name", "position": "Position", "start": "Start", "period": "Period", "months": "Tenure",
         "pay": "Stipend", "email": "Email"}


class IntakeError(Exception):
    """No model read the request; the plain reading's problems are shown instead."""


def _people(text: str) -> list[dict]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON in the answer")
    people = json.loads(match.group(0)).get("people")
    if not isinstance(people, list) or not people or not all(isinstance(p, dict) for p in people):
        raise ValueError("no people in the answer")
    return people


def blocks(people: list[dict], pay_word: str = "Stipend") -> list[str]:
    """Each person as the 'Key: value' lines offer.parse reads; a period wins over a bare month count."""
    out = []
    for person in people:
        values = {f: " ".join(str(person.get(f) or "").split()) for f in FIELDS}
        if values["period"]:
            values["months"] = ""
        lines = [f"{(pay_word if f == 'pay' else LINES[f])}: {v}" for f, v in values.items() if v]
        out.append("\n".join(lines))
    return out


def read(http, key: str, models, text: str, role: str, today: date, pay_word: str = "Stipend") -> tuple[list[str], str]:
    """(one block of lines per person, the model that read it)."""
    if not key:
        raise IntakeError("GEMINI_API_KEY is not set")
    prompt = PROMPT.format(role=role, today=f"{today.day} {today:%B %Y}", text=text.strip()[:6000])
    failures = []
    for model in models:
        try:
            raw = llm.gemini(http, key, model.id, prompt, workflow="hr", step="offer-intake",
                             json_mode=model.json_mode, schema=SCHEMA if model.json_mode else None,
                             max_output_tokens=2000, temperature=0)
            return blocks(_people(raw), pay_word), model.id
        except (HttpError, ValueError, json.JSONDecodeError, AttributeError) as exc:
            failures.append(f"{model.id}: {str(exc)[:100]}")
    raise IntakeError("; ".join(failures))


CERT_PROMPT = """Read this request for experience (completion) certificates and list every person it is for.
Today is {today}.
For each person copy, exactly as written:
- name
- position (the role or designation)
- start: the start date as dd/mm/yyyy, or "" when only months are given
- end: the end date as dd/mm/yyyy, or "" when only months are given
- period: the months as words exactly as written, e.g. "June - July" or "June 2026 - July 2026", or ""
- email: or ""
A value written once for everyone applies to every person. An email on its own line belongs to the person
written just above it.
Never guess or invent a value (no years, no dates, no pronouns): leave it "" when it is not written.
Answer JSON only: {{"people": [{{"name": "", "position": "", "start": "", "end": "", "period": "", "email": ""}}]}}

Request:
<<<
{text}
>>>"""
CERT_FIELDS = ("name", "position", "start", "end", "period", "email")
CERT_SCHEMA = {"type": "object", "properties": {"people": {"type": "array", "items": {
    "type": "object", "properties": {f: {"type": "string"} for f in CERT_FIELDS}}}}, "required": ["people"]}


def read_certificates(http, key: str, models, text: str, today: date) -> tuple[str, str]:
    """(the people as 'Key: value' lines, one block per person, the model that read them). A pronoun is
    never taken from the model: only a Pronoun: line you write sets one."""
    if not key:
        raise IntakeError("GEMINI_API_KEY is not set")
    prompt = CERT_PROMPT.format(today=f"{today.day} {today:%B %Y}", text=text.strip()[:6000])
    failures = []
    for model in models:
        try:
            raw = llm.gemini(http, key, model.id, prompt, workflow="hr", step="certificate-intake",
                             json_mode=model.json_mode, schema=CERT_SCHEMA if model.json_mode else None,
                             max_output_tokens=2000, temperature=0)
            blocks = []
            for person in _people(raw):
                values = {f: " ".join(str(person.get(f) or "").split()) for f in CERT_FIELDS}
                if not values["period"] and not re.search(r"\d", values["start"] + values["end"]) and values["start"]:
                    values["period"] = " - ".join(v for v in (values["start"], values["end"]) if v)  # month names
                if values["period"]:  # the months as written decide the dates, never a date the model made up
                    values["start"] = values["end"] = ""
                blocks.append("\n".join(f"{f.title()}: {v}" for f, v in values.items() if v))
            return "\n\n".join(blocks), model.id
        except (HttpError, ValueError, json.JSONDecodeError, AttributeError) as exc:
            failures.append(f"{model.id}: {str(exc)[:100]}")
    raise IntakeError("; ".join(failures))
