"""Sending results to you on Telegram with Hermes' own bot (``TELEGRAM_BOT_TOKEN``): long messages in
pieces, documents as files, voice clips as voice messages (Smriti, the studio). Plain text, so nothing in a transcript can break formatting."""

from __future__ import annotations

import uuid
from pathlib import Path

from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http, HttpError

from .errors import NotesError

LIMIT = 3900  # Telegram allows 4096 characters a message


class Telegram:
    def __init__(self, http: Http, secrets: Secrets) -> None:
        self.http = http
        self.token = secrets.get("TELEGRAM_BOT_TOKEN")
        self.chat = secrets.get("TELEGRAM_HOME_CHANNEL") or secrets.get("TELEGRAM_ALLOWED_USERS").split(",")[0].strip()
        self.base = (secrets.get("TELEGRAM_API_HOST") or "https://api.telegram.org") + f"/bot{self.token}"

    def _check(self) -> None:
        if not (self.token and self.chat):
            raise NotesError("TELEGRAM_BOT_TOKEN and TELEGRAM_HOME_CHANNEL (or TELEGRAM_ALLOWED_USERS) are not set")

    def text(self, body: str) -> None:
        self._check()
        pieces, current = [], ""
        for line in body.splitlines(keepends=True):
            if len(current) + len(line) > LIMIT and current:
                pieces.append(current)
                current = ""
            current += line[:LIMIT]
        pieces.append(current)
        for piece in pieces:
            try:
                self.http.request("POST", f"{self.base}/sendMessage", json_body={"chat_id": self.chat, "text": piece})
            except HttpError as exc:
                raise NotesError(f"Telegram: HTTP {exc.status}") from None

    def file(self, path: Path, caption: str) -> None:
        self.upload("sendDocument", "document", path, caption)

    def upload(self, method: str, field: str, path: Path, caption: str) -> None:
        """One file: ``sendDocument``/``document``, ``sendVoice``/``voice`` (OGG Opus), ``sendAudio``/``audio``."""
        self._check()
        boundary = uuid.uuid4().hex
        fields = {"chat_id": self.chat, "caption": caption[:1000]}
        body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                        for k, v in fields.items())
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{path.name}"\r\n'
                 "Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        try:
            self.http.request("POST", f"{self.base}/{method}", data=body,
                              headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        except HttpError as exc:
            raise NotesError(f"Telegram: HTTP {exc.status} sending {path.name}") from None
