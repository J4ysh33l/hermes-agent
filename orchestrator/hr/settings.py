"""The ``hr:`` section of ``$HERMES_HOME/brief/brief.yaml`` → frozen Settings.

Files live in ``$HERMES_HOME/hr/`` (mode 0700): ``templates/payslip.docx`` (your Word template
with ``{{fields}}``), ``payslips/<YYYY-MM>/`` (generated slips), ``pending.json`` and ``sent.jsonl``.
Salary figures never go to a model and are never written to the log.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from orchestrator.brief.settings import EXAMPLE, ModelChoice

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass(frozen=True)
class InterviewTexts:
    """Your wording for ``/hr interview``. Placeholders: {first} {name} {position} {day} {start} {end}
    {length} {join} {sender} {company}; the panel's also {positions} {schedule}. Bodies are HTML."""
    company: str = "Medoc Health"
    candidate_subject: str = "Interview for {position} at {company} | {day}, {start} IST"
    candidate_body: str = (
        "Hi {first},<br><br>Thank you for applying for the <b>{position}</b> role at {company}. "
        "Your interview is on <b>{day}, {start}–{end} IST</b> ({length} min), on Microsoft Teams.<br><br>"
        "<a href=\"{join}\">Join the interview</a> at your time. You'll wait in the lobby until the panel "
        "lets you in.<br><br>Please keep your camera on and have your resume handy. If this time doesn't "
        "work, reply to this email and we'll find another slot.<br><br>Best regards,<br>{sender}")
    panel_subject: str = "Interviews: {positions} | {day}"
    panel_body: str = ("Interview schedule for {day}. One Teams link for every slot; candidates wait in "
                       "the lobby until you admit them.<br><br>{schedule}<br><br>{sender}")


# /hr reply templates: the middle of the reply (the script adds "Hi {first}," and the sign-off).
# {company}; and from the words after the template name: {for_role} (" for the X role"),
# {by_when} (" by X", else " shortly"), {for_when} (" for X"), {arg} (the words as written).
REPLY_TEMPLATES = {
    "ack": "Thank you for applying{for_role} at {company}. We have received your application and our team is "
           "reviewing it. If your profile is a fit, we'll write to you with the next steps.",
    "reject": "Thank you for your interest{for_role} at {company} and for the time you took to apply. After "
              "reviewing your profile, we won't be moving forward at this time. We'll keep your details on file "
              "and reach out if a suitable role opens up. We wish you the very best.",
    "docs": "Thank you, we have received your documents. We'll let you know if anything else is needed.",
    "letter": "Thank you for writing. Your letter is being prepared and we'll send it to you{by_when}.",
    "leave": "Thank you for letting us know. Your leave{for_when} has been noted.",
    "salary": "Thank you for writing to us. We have received your query and are looking into it. "
              "We'll get back to you{by_when}.",
}
# Duties for a new position: one call; the next model only if one fails (Gemma takes no JSON mode).
DUTIES_MODELS = (ModelChoice("gemma-4-31b-it", False), ModelChoice("gemma-4-26b-a4b-it", False),
                 ModelChoice("gemini-3.1-flash-lite"), ModelChoice("gemini-3.5-flash-lite"))
REPLY_MODELS = (ModelChoice("gemini-3.1-flash-lite"), ModelChoice("gemini-3.5-flash-lite"),
                ModelChoice("gemma-4-31b-it", False))


@dataclass(frozen=True)
class Settings:
    weekly_off: frozenset[int] = frozenset({6})  # 0 = Monday … 6 = Sunday; LOP divides by the other days
    holidays: frozenset[date] = frozenset()
    payslip_template: str = "payslip.docx"  # in $HERMES_HOME/hr/templates/
    max_per_run: int = 200
    preview_minutes: int = 120
    sender_name: str = ""
    mailbox: str = ""  # HR mail goes out From this address (needs Send As on it); "" = your own
    mail_subject: str = "Payslip for {month}"
    mail_body: str = ("Hi {first},<br><br>Please find attached your payslip for {month}.<br><br>"
                      "Regards,<br>{sender}")
    interview: InterviewTexts = InterviewTexts()
    max_interviews: int = 30  # candidates in one /hr interview batch
    interview_minutes: int = 30  # a candidate's slot when the End is left out
    reply_templates: tuple[tuple[str, str], ...] = tuple(REPLY_TEMPLATES.items())
    reply_models: tuple[ModelChoice, ...] = REPLY_MODELS  # Gemini drafts; tried in order
    redact_names: tuple[str, ...] = ()  # more names to hide from the model (your team, frequent senders)
    reply_bulk_max: int = 30  # applications acknowledged in one /hr reply applications ack
    offer_templates: tuple[tuple[str, str], ...] = (("internship", "offer_internship.docx"), ("fte", "offer_fte.docx"),
                                                    ("consultant", "offer_consultant.docx"))  # in hr/templates/
    company_about: str = "a healthcare technology company in India"  # all the duties model hears of you
    duties_models: tuple[ModelChoice, ...] = DUTIES_MODELS
    duties_count: int = 5
    offer_subject: str = "Offer letter: {position} at {company}"
    offer_body: str = ("Hi {first},<br><br>We are delighted to offer you the <b>{position}</b> {role} at "
                       "{company}, starting {start}. Your offer letter is attached. Please read it, sign it and "
                       "send us a signed copy by replying to this email.<br><br>Regards,<br>{sender}")
    # Stipend: Unpaid → the pay table goes, this line takes the place of the line that introduced it, and
    # paragraphs starting with any of unpaid_drop (about pay changes) go too.
    unpaid_line: str = "This is an unpaid internship: no stipend, salary or other compensation is payable for its duration."
    unpaid_drop: tuple[str, ...] = ("Any changes to your salary",)
    max_offers: int = 20  # letters made from one message
    store_repo: str = ""  # private owner/name keeping hr/templates and hr/duties.json (default notes.handoff_repo)

    def template(self, name: str) -> str | None:
        return dict(self.reply_templates).get(name)


def parse(raw: dict[str, Any]) -> Settings:
    hr = raw.get("hr") or {}
    base = Settings()
    off = hr.get("weekly_off")
    return Settings(
        weekly_off=frozenset(DAYS.index(str(d).lower()) for d in off) if off is not None else base.weekly_off,
        holidays=frozenset(date.fromisoformat(str(d)) for d in hr.get("holidays") or ()),
        payslip_template=str(hr.get("payslip_template", base.payslip_template)),
        max_per_run=int(hr.get("max_per_run", base.max_per_run)),
        preview_minutes=int(hr.get("preview_minutes", base.preview_minutes)),
        sender_name=str(hr.get("sender_name", base.sender_name)),
        mailbox=str(hr.get("mailbox", base.mailbox)),
        mail_subject=str(hr.get("mail_subject", base.mail_subject)),
        mail_body=str(hr.get("mail_body", base.mail_body)),
        interview=InterviewTexts(**{k: str(v) for k, v in (hr.get("interview") or {}).items()
                                    if k in InterviewTexts.__dataclass_fields__}),
        max_interviews=int(hr.get("max_interviews", base.max_interviews)),
        interview_minutes=int(hr.get("interview_minutes", base.interview_minutes)),
        reply_templates=tuple({**REPLY_TEMPLATES, **{str(k): str(v) for k, v in (hr.get("replies") or {}).items()}}.items()),
        reply_models=tuple(ModelChoice(str(m["id"]), bool(m.get("json_mode", True)))
                           for m in hr["reply_models"]) if hr.get("reply_models") else base.reply_models,
        redact_names=tuple(str(n) for n in hr.get("redact_names") or ()),
        reply_bulk_max=int(hr.get("reply_bulk_max", base.reply_bulk_max)),
        offer_templates=tuple({**dict(base.offer_templates),
                               **{str(k): str(v) for k, v in (hr.get("offer_templates") or {}).items()}}.items()),
        company_about=str(hr.get("company_about", base.company_about)),
        duties_models=tuple(ModelChoice(str(m["id"]), bool(m.get("json_mode", True)))
                            for m in hr["duties_models"]) if hr.get("duties_models") else base.duties_models,
        duties_count=int(hr.get("duties_count", base.duties_count)),
        offer_subject=str(hr.get("offer_subject", base.offer_subject)),
        offer_body=str(hr.get("offer_body", base.offer_body)),
        unpaid_line=str(hr.get("unpaid_line", base.unpaid_line)),
        unpaid_drop=tuple(str(x) for x in hr["unpaid_drop"]) if "unpaid_drop" in hr else base.unpaid_drop,
        max_offers=int(hr.get("max_offers", base.max_offers)),
        store_repo=str(hr.get("store_repo") or (raw.get("notes") or {}).get("handoff_repo") or ""),
    )


def load(state_dir: Path) -> Settings:
    """``state_dir`` is ``$HERMES_HOME/brief`` (where brief.yaml lives)."""
    path = state_dir / "brief.yaml"
    raw = yaml.safe_load((path if path.is_file() else EXAMPLE).read_text(encoding="utf-8")) or {}
    return parse(raw)
