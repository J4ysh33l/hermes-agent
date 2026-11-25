"""``/hr reply``: answer HR mail in its own thread, From the HR mailbox, only after your yes.

Three ways to write the reply:
- **Gemini** (default): the mail's new text (not the quoted history), with names, emails, numbers and
  links hidden (``redact``), and your one-line instruction go to one call; it answers JSON
  ``{"paragraphs": [...]}``. The script, not the model, writes "Hi <first>," and the sign-off, so the
  shape of the mail never changes. The draft is checked (``redact.restore``); a draft with a problem is
  asked for once more with the problem named, then the next model is tried; if none passes, nothing is
  drafted and you are told why.
- **A template** (``ack``, ``reject``, ``docs``, ``letter``, ``leave``, ``salary`` or your own, from
  ``hr.replies``): filled by the script, no model.
- **Your own words** (``/hr reply edit <text>``).

The draft waits in ``$HERMES_HOME/hr/reply.json`` (0600) for ``/hr reply yes``, then goes out with
Graph's reply action (Mail.Send), so it stays in the thread; a reply to a waiting mail clears it.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass

from orchestrator import llm
from orchestrator.brief.net import Http, HttpError
from orchestrator.outreach.build import fill
from orchestrator.outreach.errors import OutreachError

from . import redact
from .settings import Settings

GRAPH = "https://graph.microsoft.com/v1.0"
MAX_CHARS = 6000  # of the mail's new text sent to the model
TRIES_PER_MODEL = 2
SIGN_WORDS = (r"(?:regards|best regards|warm regards|kind regards|thanks(?: and regards| & regards)?|thank you|"
              r"sincerely|yours sincerely|yours truly|best|cheers)")
GREETING = re.compile(r"^\s*(hi|hello|hey|dear|greetings)\b[^,.!?\n]{0,40}[,!.]?\s*$", re.IGNORECASE)  # alone
GREETING_LEAD = re.compile(r"^\s*(?:hi|hello|hey|dear|greetings)\b[^,.!?\n]{0,40}[,!.]\s*", re.IGNORECASE)
CLOSING = re.compile(r"^\s*" + SIGN_WORDS + r"\b[\s\S]{0,80}$", re.IGNORECASE)
# A sign-off at the end of the last paragraph: on its own line or after a sentence ends (so "the very
# best." stays), then up to three short lines (a name, a team, a company).
CLOSING_TAIL = re.compile(r"(?:\n|(?<=[.!?])\s+)\s*" + SIGN_WORDS + r"[,!.]?[ \t]*(?:\n[^\n]{0,60}){0,3}\s*$",
                          re.IGNORECASE)

PROMPT = """You draft the body of an HR team's reply to the email below.
Rules:
- Answer JSON only: {{"paragraphs": ["...", "..."]}}. 1 to 4 short paragraphs, plain text, no Markdown.
- No greeting and no sign-off: they are added for you.
- Words in square brackets such as [NAME_1], [EMAIL_1], [AMOUNT_1] stand for hidden details. Copy any you
  need exactly as written, brackets included. Never write a name, email, phone number, link, amount or
  ID number yourself, and never make up a placeholder.
- Promise nothing the instruction does not say: no dates, amounts, decisions or offers of your own.
- Warm, clear, professional; Indian English.
{instruction}
The email (subject, then text):
<<<
Subject: {subject}
{body}
>>>"""
SCHEMA = {"type": "object", "properties": {"paragraphs": {"type": "array", "items": {"type": "string"}}},
          "required": ["paragraphs"]}


class ReplyError(Exception):
    """Shown to you as it is; nothing was drafted or sent."""


@dataclass(frozen=True)
class Mail:
    id: str
    subject: str
    sender: str
    sender_name: str
    text: str  # the new part of the mail, without the quoted thread
    names: tuple[str, ...]  # every name in the headers: sender, To, Cc


@dataclass(frozen=True)
class Draft:
    paragraphs: tuple[str, ...]
    how: str  # "gemini-3.1-flash-lite" · "template ack" · "your words"
    hidden: int = 0  # details hidden from the model
    fixes: tuple[str, ...] = ()


def fetch(http: Http, token: str, msg_id: str) -> Mail:
    headers = {"Authorization": f"Bearer {token}", "Prefer": 'outlook.body-content-type="text"'}
    try:
        data = http.request("GET", f"{GRAPH}/me/messages/{msg_id}", headers=headers,
                            params={"$select": "subject,from,toRecipients,ccRecipients,uniqueBody"}).json()
    except HttpError as exc:
        raise ReplyError(f"Outlook could not open that mail: HTTP {exc.status}") from None
    sender = (data.get("from") or {}).get("emailAddress") or {}
    people = [sender] + [(r.get("emailAddress") or {}) for r in (data.get("toRecipients") or []) +
                         (data.get("ccRecipients") or [])]
    return Mail(msg_id, data.get("subject") or "", sender.get("address", ""), sender.get("name") or "",
                ((data.get("uniqueBody") or {}).get("content") or "").strip()[:MAX_CHARS],
                tuple(p["name"] for p in people if p.get("name") and "@" not in p["name"]))


def first_name(name: str) -> str:
    word = (name or "").split()[0] if (name or "").split() else ""
    return word.capitalize() if word.isalpha() and len(word) > 1 else ""


def _trim(paragraphs: list[str]) -> tuple[list[str], list[str]]:
    """Drop a greeting or sign-off the model wrote anyway (the script writes both): a paragraph of its
    own, or the start of the first paragraph ("Hi [NAME_1], thank you…") and the end of the last."""
    fixes = []
    paras = [p.strip() for p in paragraphs if p and p.strip()]
    if paras and GREETING.match(paras[0]):
        fixes.append(f"dropped its greeting {paras.pop(0)!r}")
    elif paras and (lead := GREETING_LEAD.match(paras[0])):
        rest = paras[0][lead.end():]
        paras[0] = rest[:1].upper() + rest[1:]
        fixes.append(f"dropped its greeting {lead.group(0).strip()!r}")
    if paras and CLOSING.match(paras[-1]):
        fixes.append(f"dropped its sign-off {paras.pop()!r}")
    elif paras and (tail := CLOSING_TAIL.search(paras[-1])):
        paras[-1] = paras[-1][:tail.start()].rstrip()
        fixes.append(f"dropped its sign-off {' '.join(tail.group(0).split())!r}")
    return [p for p in paras if p], fixes


def _answer(text: str) -> list[str]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON in the answer")
    paras = json.loads(match.group(0)).get("paragraphs")
    if not isinstance(paras, list) or not all(isinstance(p, str) for p in paras):
        raise ValueError('the answer has no "paragraphs" list')
    return paras


def write(http: Http, key: str, settings: Settings, mail: Mail, instruction: str) -> Draft:
    """One Gemini draft that passed every check, or ReplyError naming what went wrong."""
    if not key:
        raise ReplyError("GEMINI_API_KEY is not set in $HERMES_HOME/.env")
    (subject, body, said), table = redact.hide([mail.subject, mail.text, instruction],
                                               list(mail.names) + list(settings.redact_names))
    ask = f"Instruction from HR: {said}" if said.strip() else "Instruction from HR: write a suitable reply."
    prompt = PROMPT.format(instruction=ask, subject=subject, body=body or "(no text)")
    failures = []
    for model in settings.reply_models:
        extra = ""
        for _ in range(TRIES_PER_MODEL):
            try:
                raw = llm.gemini(http, key, model.id, prompt + extra, workflow="hr", step="reply",
                                 json_mode=model.json_mode, schema=SCHEMA if model.json_mode else None,
                                 max_output_tokens=1200, temperature=0.3)
                paras, trims = _trim(_answer(raw))
            except (HttpError, ValueError) as exc:
                failures.append(f"{model.id}: {str(exc)[:120]}")
                break
            back = redact.restore("\n\n".join(paras), table)
            if back.problems:
                failures.append(f"{model.id}: " + "; ".join(back.problems))
                extra = ("\n\nYour last answer was refused: " + "; ".join(back.problems) +
                         ". Answer again following every rule.")
                continue
            if not back.text.strip():
                failures.append(f"{model.id}: empty draft")
                break
            return Draft(tuple(back.text.split("\n\n")), model.id, len(table), tuple(trims) + back.fixes)
    raise ReplyError("No draft passed the checks, so nothing was drafted:\n" + "\n".join(f"• {f}" for f in failures))


def from_template(settings: Settings, name: str, arg: str) -> Draft:
    text = settings.template(name)
    if text is None:
        raise ReplyError(f"No template {name!r}.")
    arg = arg.strip()
    body = fill(text, company=settings.interview.company, arg=arg,
                for_role=f" for the {arg} role" if arg else "", by_when=f" by {arg}" if arg else " shortly",
                for_when=f" for {arg}" if arg else "")
    return Draft(tuple(p for p in body.split("\n\n") if p.strip()), f"template {name}")


def own_words(text: str) -> Draft:
    return Draft(tuple(p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()), "your words")


def sign(settings: Settings) -> str:
    return settings.sender_name or "HR Team"


def as_text(draft: Draft, name: str, settings: Settings) -> str:
    first = first_name(name)
    return "\n\n".join([f"Hi {first}," if first else "Hello,", *draft.paragraphs, f"Regards,\n{sign(settings)}"])


def as_html(text: str) -> str:
    return "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in text.split("\n\n"))


def send(http: Http, token: str, msg_id: str, text: str, mailbox: str) -> None:
    """Graph's reply action: the answer joins the thread (Re: subject, headers kept)."""
    message: dict = {"body": {"contentType": "HTML", "content": as_html(text)}}
    if mailbox:
        message["from"] = {"emailAddress": {"address": mailbox}}
    try:  # 202 Accepted, empty body
        http.request("POST", f"{GRAPH}/me/messages/{msg_id}/reply", headers={"Authorization": f"Bearer {token}"},
                     json_body={"message": message})
    except HttpError as exc:
        hint = " (Mail.Send not granted, or the login predates it)" if exc.status == 403 else ""
        if exc.status == 403 and "ErrorSendAsDenied" in str(exc):
            hint = f" (no Send As right on {mailbox}: an Exchange admin grants it)"
        raise OutreachError(f"Outlook reply: HTTP {exc.status}{hint}") from None
