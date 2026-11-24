"""Documents written by Claude, through your private handoff repo (``notes.handoff_repo``).

For a request marked ``claude``, Hermes commits ``smriti/<id>/transcript.md`` and ``request.md`` and
opens an issue; that issue is the GitHub event your Claude scheduled task listens for. Claude
commits ``smriti/<id>/result.md`` (Markdown) and closes the issue. Each run, Hermes looks for
``result.md`` and sends it to you. The contract Claude follows is in ``HANDOFF.md`` (copy it into the
repo). Token: ``GITHUB_HANDOFF_TOKEN`` in ``$HERMES_HOME/.env``, fine-grained, that repo only,
Contents and Issues read/write.
"""

from __future__ import annotations

import base64

from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http, HttpError

from .errors import NotesError

API = "https://api.github.com"
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
        self.http = http
        self.repo = repo
        self.token = secrets.get("GITHUB_HANDOFF_TOKEN")

    def _call(self, method: str, path: str, **kw):
        if not (self.repo and self.token):
            raise NotesError("Claude handoff is not set up: notes.handoff_repo in brief.yaml and "
                             "GITHUB_HANDOFF_TOKEN in .env")
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        return self.http.request(method, f"{API}/repos/{self.repo}/{path}", headers=headers, **kw).json()

    def _put(self, path: str, text: str, message: str) -> None:
        self._call("PUT", f"contents/{path}",
                   json_body={"message": message, "content": base64.b64encode(text.encode()).decode()})

    def send(self, req: dict, meeting: dict, transcript: str, make: str) -> int:
        """Commit the transcript and the request, open the issue; returns its number."""
        when = meeting["start"][:16].replace("T", " ")
        title = f"Smriti: {make} — {meeting['subject']} ({meeting['start'][:10]})"
        body = REQUEST.format(title=title, subject=meeting["subject"], when=when, make=make, id=req["id"])
        try:
            self._put(f"smriti/{req['id']}/transcript.md", transcript, f"smriti {req['id']}: transcript")
            self._put(f"smriti/{req['id']}/request.md", body, f"smriti {req['id']}: request")
            return int(self._call("POST", "issues", json_body={"title": title, "body": body})["number"])
        except HttpError as exc:
            raise NotesError(f"GitHub handoff: HTTP {exc.status}") from None

    def result(self, req: dict) -> str | None:
        """Claude's ``result.md``, or None while it is not written yet."""
        try:
            found = self._call("GET", f"contents/smriti/{req['id']}/result.md")
        except HttpError as exc:
            if exc.status == 404:
                return None
            raise NotesError(f"GitHub handoff: HTTP {exc.status}") from None
        return base64.b64decode(found["content"]).decode("utf-8")
