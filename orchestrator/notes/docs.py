"""Documents from a saved transcript: summary, tasks, PRD, or any document you name (``doc <what>``).

One Gemini text call each; the audio is never sent again. Summary and tasks come back as Telegram
messages; a PRD or a named document as a .docx file (``to_docx``) with a short note.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import docx

from orchestrator import llm
from orchestrator.brief.net import Http, HttpError

from .errors import NotesError
from .settings import Settings
from .transcribe import Clock, wait_for_room

RULES = ("The transcript is below. Hindi in it is written in Latin script; write in English. Use only what "
         "was said: never invent names, numbers or dates, and write 'Not discussed' where something is missing. "
         "Use Markdown: # headings, - bullets.")


@dataclass(frozen=True)
class Kind:
    title: str
    ask: str
    max_tokens: int
    as_file: bool  # a .docx rather than a Telegram message


KINDS = {
    "summary": Kind("Summary", "Write a meeting summary: one line on the purpose, the key points, decisions "
                    "made, and open questions. At most 250 words.", 2_000, False),
    "tasks": Kind("Tasks", "List the action items that were agreed, one per line: '- Owner: task (due date if "
                  "said)'. If none were agreed, say so in one line.", 1_500, False),
    "prd": Kind("PRD", "Write a product requirements document from what was discussed: title, problem, goals "
                "and non-goals, users, functional requirements (numbered), non-functional requirements, "
                "decisions from the meeting, open questions.", 8_000, True),
    "doc": Kind("Document", "Write this document: {what}.", 6_000, True),
}


def write(http: Http, key: str, settings: Settings, clock: Clock, kind: str, what: str, transcript: str) -> str:
    spec = KINDS[kind]
    prompt = f"{spec.ask.format(what=what)}\n{RULES}\n\n{transcript}"
    wait_for_room(len(prompt) // 3 + spec.max_tokens, settings, clock)
    errors = []
    for model in settings.models:
        try:
            text = llm.gemini(http, key, model, prompt, workflow="notes", step=kind, max_output_tokens=spec.max_tokens,
                              temperature=0.2)
        except (HttpError, ValueError) as exc:
            errors.append(f"{model}: {str(exc)[:120]}")
            continue
        if text.strip():
            return text.strip()
        errors.append(f"{model}: empty answer")
    raise NotesError("Gemini could not write it: " + "; ".join(errors))


BOLD = re.compile(r"\*\*(.+?)\*\*")
STYLES = (("### ", "Heading 3"), ("## ", "Heading 2"), ("# ", "Heading 1"), ("- ", "List Bullet"),
          ("* ", "List Bullet"))


def _runs(paragraph, text: str) -> None:
    for n, piece in enumerate(BOLD.split(text)):
        paragraph.add_run(piece).bold = n % 2 == 1


def to_docx(markdown: str, path: Path) -> Path:
    """The Markdown a model writes (headings, bullets, numbered lines, **bold**) as a Word file."""
    document = docx.Document()
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        style = next(((s, prefix) for prefix, s in STYLES if line.lstrip().startswith(prefix)), None)
        if style:
            _runs(document.add_paragraph(style=style[0]), line.lstrip()[len(style[1]):])
        elif re.match(r"\s*\d+[.)]\s", line):
            _runs(document.add_paragraph(style="List Number"), re.sub(r"^\s*\d+[.)]\s", "", line))
        else:
            _runs(document.add_paragraph(), line)
    document.save(path)
    path.chmod(0o600)
    return path
