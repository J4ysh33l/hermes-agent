"""Handing work to Claude through your private GitHub repo (the "handoff repo").

Hermes commits any input files under a folder, then opens an issue labelled ``hermes`` whose body is
the whole task: what to do, the rules, where to write the answer. The issue-opened event starts your
Claude scheduled task (the Claude GitHub App must be installed on the repo); its prompt
(``orchestrator/HANDOFF.md``) only says to take the oldest open ``hermes`` issue (removing the label
claims it), do what its body says and close it. Hermes reads the answer files on its next run.

Token: ``GITHUB_HANDOFF_TOKEN`` in ``$HERMES_HOME/.env``, fine-grained, that repo only, Contents and
Issues read/write.

Issues opened with the Claude GitHub App's own credentials don't start the task (seen 2026-11-24), so
after opening an issue Hermes also fires the task through its API trigger when ``CLAUDE_ROUTINE_URL``
(the task's Fire URL) and ``CLAUDE_ROUTINE_TOKEN`` are in ``.env``. A failed fire is not an error: the
issue waits for the next run (any fire or issue-opened event takes the oldest waiting issue).
"""

from __future__ import annotations

import base64

from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http, HttpError

API = "https://api.github.com"
LABEL = "hermes"  # open + labelled = waiting for Claude; the scheduled task removes it when it starts
MAX_BODY = 65_000  # GitHub refuses issue bodies over 65,536 characters
FIRE_HEADERS = {"anthropic-version": "2023-06-01", "anthropic-beta": "experimental-cc-routine-2026-04-01"}


class HandoffError(Exception):
    """Shown as it is; the work stays queued."""


class Handoff:
    def __init__(self, http: Http, secrets: Secrets, repo: str) -> None:
        self.http = http
        self.repo = repo
        self.token = secrets.get("GITHUB_HANDOFF_TOKEN")
        self.fire_url = secrets.get("CLAUDE_ROUTINE_URL")
        self.fire_token = secrets.get("CLAUDE_ROUTINE_TOKEN")
        self.fire_error = ""  # why the last fire failed ("" when it worked or was not set up)

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

    def put(self, path: str, text: str) -> None:
        """Commit ``text`` at ``path`` (creating or replacing it; nothing when it is already the same)."""
        try:
            found = self._call("GET", f"contents/{path}")
        except HttpError as exc:
            if exc.status != 404:
                raise
            found = None
        if found and base64.b64decode(found["content"]).decode("utf-8") == text:
            return
        body = {"message": f"handoff: {path}", "content": base64.b64encode(text.encode()).decode()}
        if found:
            body["sha"] = found["sha"]
        self._call("PUT", f"contents/{path}", json_body=body)

    def send(self, files: dict[str, str], title: str, body: str) -> int:
        """Commit each ``path: text``, then open the issue (``body`` is Claude's whole task); returns its number."""
        if len(body) > MAX_BODY:
            raise HandoffError(f"the request is {len(body):,} characters; GitHub takes at most {MAX_BODY:,}")
        try:
            for path, text in files.items():
                self.put(path, text)
            self._label()
            number = int(self._call("POST", "issues", json_body={"title": title, "body": body, "labels": [LABEL]})["number"])
        except HttpError as exc:
            raise HandoffError(f"GitHub handoff: HTTP {exc.status}") from None
        self.fire(f"Hermes opened issue #{number}: {title}")
        return number

    def fire(self, text: str = "") -> bool:
        """Start the Claude task through its API trigger; False when not set up or refused (never raises)."""
        self.fire_error = ""
        if not (self.fire_url and self.fire_token):
            return False
        headers = {"Authorization": f"Bearer {self.fire_token}", "Content-Type": "application/json", **FIRE_HEADERS}
        try:
            self.http.request("POST", self.fire_url, headers=headers, json_body={"text": text[:2000]})
        except HttpError as exc:
            self.fire_error = f"Claude task fire: HTTP {exc.status}"
            return False
        except OSError as exc:  # network down: the issue simply waits
            self.fire_error = f"Claude task fire: {exc.__class__.__name__}"
            return False
        return True

    def _label(self) -> None:
        try:
            self._call("POST", "labels", json_body={"name": LABEL, "color": "5319e7",
                                                    "description": "Waiting for Claude (Hermes handoff)"})
        except HttpError as exc:
            if exc.status != 422:  # 422: it exists already
                raise

    def closed(self, number: int) -> bool:
        """True once Claude has closed the issue (its answer is complete)."""
        try:
            return self._call("GET", f"issues/{number}")["state"] == "closed"
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
