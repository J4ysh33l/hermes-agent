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

from orchestrator.brief.settings import EXAMPLE

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


@dataclass(frozen=True)
class Settings:
    weekly_off: frozenset[int] = frozenset({6})  # 0 = Monday … 6 = Sunday; LOP divides by the other days
    holidays: frozenset[date] = frozenset()
    payslip_template: str = "payslip.docx"  # in $HERMES_HOME/hr/templates/
    max_per_run: int = 200
    preview_minutes: int = 120
    sender_name: str = ""
    mail_subject: str = "Payslip for {month}"
    mail_body: str = ("Hi {first},<br><br>Please find attached your payslip for {month}.<br><br>"
                      "Regards,<br>{sender}")
    interview: InterviewTexts = InterviewTexts()
    max_interviews: int = 30  # candidates in one /hr interview batch
    interview_minutes: int = 30  # a candidate's slot when the End is left out


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
        mail_subject=str(hr.get("mail_subject", base.mail_subject)),
        mail_body=str(hr.get("mail_body", base.mail_body)),
        interview=InterviewTexts(**{k: str(v) for k, v in (hr.get("interview") or {}).items()
                                    if k in InterviewTexts.__dataclass_fields__}),
        max_interviews=int(hr.get("max_interviews", base.max_interviews)),
        interview_minutes=int(hr.get("interview_minutes", base.interview_minutes)),
    )


def load(state_dir: Path) -> Settings:
    """``state_dir`` is ``$HERMES_HOME/brief`` (where brief.yaml lives)."""
    path = state_dir / "brief.yaml"
    raw = yaml.safe_load((path if path.is_file() else EXAMPLE).read_text(encoding="utf-8")) or {}
    return parse(raw)
