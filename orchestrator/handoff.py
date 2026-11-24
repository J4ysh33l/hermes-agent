"""Handing work to Claude through your private GitHub repo (the "handoff repo").

Hermes commits the input files under a folder, then opens an issue; the issue-opened event starts
your Claude scheduled task (the Claude GitHub App must be installed on the repo). Claude commits its
answer next to the inputs and closes the issue. Hermes looks for the answer file on its next run.
Each workflow writes its own contract for Claude (``orchestrator/notes/HANDOFF.md``,
``orchestrator/watch/HANDOFF.md``).

Token: ``GITHUB_HANDOFF_TOKEN`` in ``$HERMES_HOME/.env``, fine-grained, that repo only, Contents and
Issues read/write.
"""

from __future__ import annotations

import base64

from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http, HttpError

API = "https://api.github.com"


class HandoffError(Exception):
    """Shown as it is; the work stays queued."""


class Handoff:
    def __init__(self, http: Http, secrets: Secrets, repo: str) -> None:
        self.http = http
        self.repo = repo
        self.token = secrets.get("GITHUB_HANDOFF_TOKEN")

    @property
    def ready(self) -> bool:
        return bool(self.repo and self.token)

    def _call(self, method: str, path: str, **kw):
        if not self.ready:
            raise HandoffError("Claude handoff is not set up: notes.handoff_repo (or watch.handoff_repo) in "
                               "brief.yaml and GITHUB_HANDOFF_TOKEN in .env")
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        return self.http.request(method, f"{API}/repos/{self.repo}/{path}", headers=headers, **kw).json()

    def send(self, files: dict[str, str], title: str, body: str) -> int:
        """Commit each ``path: text``, then open the issue; returns its number."""
        try:
            for path, text in files.items():
                self._call("PUT", f"contents/{path}", json_body={
                    "message": f"handoff: {path}", "content": base64.b64encode(text.encode()).decode()})
            return int(self._call("POST", "issues", json_body={"title": title, "body": body})["number"])
        except HttpError as exc:
            raise HandoffError(f"GitHub handoff: HTTP {exc.status}") from None

    def read(self, path: str) -> str | None:
        """A file Claude committed, or None while it is not there yet."""
        try:
            found = self._call("GET", f"contents/{path}")
        except HttpError as exc:
            if exc.status == 404:
                return None
            raise HandoffError(f"GitHub handoff: HTTP {exc.status}") from None
        return base64.b64decode(found["content"]).decode("utf-8")
