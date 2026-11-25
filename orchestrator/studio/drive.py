"""Finished videos and covers to Google Drive, in a "Hermes Studio" folder.

Sign in once with ``python -m orchestrator.studio auth drive``: its own token (``tokens/drive.json``; the
``google*.json`` names are Gmail accounts) with the narrowest Drive scope, ``drive.file``: Hermes sees
only the files and folder it made, nothing else in your Drive. Client id/secret are the Gmail ones.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from orchestrator.brief import auth
from orchestrator.brief.creds import Secrets
from orchestrator.brief.items import AuthError, SourceError
from orchestrator.brief.net import Http, HttpError
from orchestrator.brief.sources import gmail

SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKEN = "drive"
FOLDER = "Hermes Studio"
FILES = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,webViewLink"
LOGIN = "python -m orchestrator.studio auth drive"


class DriveError(Exception):
    """Shown as it is; the video stays on the server."""


def ready(secrets: Secrets) -> bool:
    return bool(secrets.token(TOKEN).get("refresh_token"))


def _token(http: Http, secrets: Secrets) -> str:
    saved = secrets.token(TOKEN)
    if not saved.get("refresh_token"):
        raise DriveError(f"Drive is not signed in: run `{LOGIN}` on the host")
    try:
        return gmail.access_token(http, secrets.get("GOOGLE_CLIENT_ID"), secrets.get("GOOGLE_CLIENT_SECRET"),
                                  saved["refresh_token"])
    except (AuthError, SourceError, HttpError) as exc:  # the Gmail helper words its errors for Gmail
        raise DriveError(f"Drive sign-in failed ({str(exc)[:80]}): run `{LOGIN}` again") from None


def _folder(http: Http, secrets: Secrets, token: str, fresh: bool = False) -> str:
    saved = secrets.token(TOKEN)
    if saved.get("folder") and not fresh:
        return saved["folder"]
    made = http.request("POST", f"{FILES}?fields=id", headers={"Authorization": f"Bearer {token}"},
                        json_body={"name": FOLDER, "mimeType": "application/vnd.google-apps.folder"}).json()
    secrets.save_token(TOKEN, {**saved, "folder": made["id"]})
    return made["id"]


def _multipart(meta: dict, path: Path, mime: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{boundary}\r\nContent-Type: {mime}\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/related; boundary={boundary}"


def upload(http: Http, secrets: Secrets, path: Path, name: str = "", mime: str = "video/mp4") -> str:
    """Uploads ``path`` into the Hermes Studio folder; returns its Drive link."""
    token = _token(http, secrets)
    for fresh in (False, True):  # the folder may have been deleted: make it again once
        meta = {"name": name or path.name, "parents": [_folder(http, secrets, token, fresh)]}
        body, kind = _multipart(meta, path, mime)
        try:
            done = http.request("POST", UPLOAD, data=body,
                                headers={"Authorization": f"Bearer {token}", "Content-Type": kind}).json()
            return done.get("webViewLink") or f"https://drive.google.com/file/d/{done['id']}/view"
        except HttpError as exc:
            if exc.status != 404 or fresh:
                raise DriveError(f"Drive upload of {path.name}: HTTP {exc.status}") from None
    raise DriveError("unreachable")


def login(http: Http, secrets: Secrets) -> None:
    print("Signing in Google Drive for the studio (it can see only the files it makes).")
    data = auth.google_scoped(http, secrets, SCOPE)
    secrets.save_token(TOKEN, {"refresh_token": data["refresh_token"], "saved_at": time.time()})
    print(f"Drive login saved. Videos will go to the '{FOLDER}' folder.")
