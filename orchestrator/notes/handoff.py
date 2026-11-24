"""Documents written by Claude, through your private handoff repo (``notes.handoff_repo``).

For a request marked ``claude``, Hermes commits ``smriti/<id>/transcript.md`` and opens an issue whose
body is the whole task (``REQUEST``: what to write, the rules, where to put it); the Claude scheduled
task (``orchestrator/HANDOFF.md``) reads the transcript, commits ``smriti/<id>/result.md`` (Markdown)
and closes the issue. Each run, Hermes looks for ``result.md`` and sends it to you.
"""

from __future__ import annotations

from orchestrator import handoff
from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http

from .errors import NotesError

REQUEST = """# {title}

Meeting: **{subject}**, {when} IST
Make: **{make}**

The meeting's transcript is `smriti/{id}/transcript.md` in this repo: one line per turn,
`[mm:ss] Name: words`, with Hindi typed in Latin script. Read that file; nothing else in the repo
is part of this task.

Write the {make} in English **from the transcript only**:
- Never invent names, numbers or dates; write "Not discussed" where something is missing.
- Markdown with `#` headings and `-` bullets (Hermes turns it into a Word file).

Save it as `smriti/{id}/result.md`, commit it to main, push, then close this issue. The transcript
is private meeting content: never post it anywhere else.
"""


class Handoff:
    def __init__(self, http: Http, secrets: Secrets, repo: str) -> None:
        self.repo = handoff.Handoff(http, secrets, repo)

    def send(self, req: dict, meeting: dict, transcript: str, make: str) -> int:
        """Commit the transcript and the request, open the issue; returns its number."""
        when = meeting["start"][:16].replace("T", " ")
        title = f"Smriti: {make} — {meeting['subject']} ({meeting['start'][:10]})"
        body = REQUEST.format(title=title, subject=meeting["subject"], when=when, make=make, id=req["id"])
        try:
            return self.repo.send({f"smriti/{req['id']}/transcript.md": transcript}, title, body)
        except handoff.HandoffError as exc:
            raise NotesError(str(exc)) from None

    def result(self, req: dict) -> str | None:
        """Claude's ``result.md``, or None while it is not written yet."""
        try:
            return self.repo.read(f"smriti/{req['id']}/result.md")
        except handoff.HandoffError as exc:
            raise NotesError(str(exc)) from None
