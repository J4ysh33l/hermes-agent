"""Documents written by Claude, through your private handoff repo (``notes.handoff_repo``).

For a request marked ``claude``, Hermes commits ``smriti/<id>/transcript.md`` and ``request.md`` and
opens an issue (``orchestrator.handoff``). Claude commits ``smriti/<id>/result.md`` (Markdown) and
closes the issue. Each run, Hermes looks for ``result.md`` and sends it to you. The contract Claude
follows is in ``HANDOFF.md`` (copy it into the repo).
"""

from __future__ import annotations

from orchestrator import handoff
from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http

from .errors import NotesError

REQUEST = """# {title}

Meeting: **{subject}**, {when} IST
Make: **{make}**
Transcript: `smriti/{id}/transcript.md` (Hindi in Latin script)

Write it in English, from the transcript only (never invent names, numbers or dates; write
"Not discussed" where something is missing), as Markdown with # headings and - bullets.
Commit it as `smriti/{id}/result.md`, then close this issue.
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
            return self.repo.send({f"smriti/{req['id']}/transcript.md": transcript,
                                   f"smriti/{req['id']}/request.md": body}, title, body)
        except handoff.HandoffError as exc:
            raise NotesError(str(exc)) from None

    def result(self, req: dict) -> str | None:
        """Claude's ``result.md``, or None while it is not written yet."""
        try:
            return self.repo.read(f"smriti/{req['id']}/result.md")
        except handoff.HandoffError as exc:
            raise NotesError(str(exc)) from None
