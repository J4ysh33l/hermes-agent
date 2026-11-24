"""Microsoft Graph for Smriti: Teams meetings you organised, and their transcripts and recordings.

- ``ended``: one calendarView call for the window; Teams meetings you organised that have ended.
- ``sessions``: the online meeting behind a join link, then its transcripts and recordings, kept to
  this occurrence's time (a recurring meeting shares one online meeting across occurrences) and
  sorted by start, so a stop-and-restart becomes several sessions in order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http, HttpError
from orchestrator.brief.sources import outlook
from orchestrator.outreach import graph
from orchestrator.outreach.errors import OutreachError

from .errors import NotesError
from .store import Meeting

GRAPH = "https://graph.microsoft.com/v1.0"
IST = ZoneInfo("Asia/Kolkata")
SLACK = timedelta(minutes=30)  # a session may start early or run past the calendar slot


@dataclass(frozen=True)
class Session:
    """One transcript or recording file of a meeting."""

    id: str
    start: datetime  # UTC
    end: datetime | None


@dataclass(frozen=True)
class Files:
    meeting_id: str
    transcripts: tuple[Session, ...]
    recordings: tuple[Session, ...]


class Teams:
    def __init__(self, http: Http, secrets: Secrets) -> None:
        self.http = http
        self.secrets = secrets
        self._token = ""

    def token(self) -> str:
        if not self._token:
            try:
                self._token = graph.access(self.http, self.secrets, outlook.NOTES_SCOPES)
            except OutreachError as exc:
                raise NotesError(str(exc)) from None
        return self._token

    def _get(self, path: str, params: dict | None = None, *, raw: bool = False):
        headers = {"Authorization": f"Bearer {self.token()}", "Prefer": 'outlook.timezone="India Standard Time"'}
        try:
            reply = self.http.request("GET", path if path.startswith("http") else GRAPH + path, params=params,
                                      headers=headers)
        except HttpError as exc:
            hint = " (permission not granted in Entra, or sign in again)" if exc.status == 403 else ""
            raise NotesError(f"Teams: HTTP {exc.status} on {path.split('?')[0].rsplit('/', 1)[-1]}{hint}") from None
        return reply.text() if raw else reply.json()

    def ended(self, since: datetime, now: datetime) -> list[Meeting]:
        params = {"startDateTime": since.isoformat(), "endDateTime": now.isoformat(), "$top": 100,
                  "$select": "subject,start,end,isOnlineMeeting,onlineMeeting,onlineMeetingProvider,"
                             "isOrganizer,isCancelled"}
        found = []
        for row in self._get("/me/calendarView", params).get("value") or []:
            join = ((row.get("onlineMeeting") or {}).get("joinUrl") or "")
            end = datetime.fromisoformat(row["end"]["dateTime"][:19]).replace(tzinfo=IST)
            if (row.get("isCancelled") or not row.get("isOrganizer") or not join
                    or row.get("onlineMeetingProvider") != "teamsForBusiness" or end > now):
                continue
            start = datetime.fromisoformat(row["start"]["dateTime"][:19]).replace(tzinfo=IST)
            found.append(Meeting(row["id"], row.get("subject") or "(no subject)", start, end, join))
        return found

    def files(self, meeting: dict) -> Files:
        """This occurrence's transcripts and recordings, oldest first."""
        safe = meeting["join"].replace("'", "''")
        rows = self._get("/me/onlineMeetings", {"$filter": f"JoinWebUrl eq '{safe}'"}).get("value") or []
        if not rows:
            raise NotesError("Teams has no online meeting for that join link")
        meeting_id = rows[0]["id"]
        start = datetime.fromisoformat(meeting["start"]) - SLACK
        end = datetime.fromisoformat(meeting["end"]) + SLACK

        def sessions(kind: str) -> tuple[Session, ...]:
            out = []
            for row in self._get(f"/me/onlineMeetings/{meeting_id}/{kind}").get("value") or []:
                began = _utc(row["createdDateTime"])
                if start <= began <= end:
                    out.append(Session(row["id"], began, _utc(row["endDateTime"]) if row.get("endDateTime") else None))
            return tuple(sorted(out, key=lambda s: s.start))

        return Files(meeting_id, sessions("transcripts"), sessions("recordings"))

    def transcript(self, meeting_id: str, session: Session) -> str:
        return self._get(f"/me/onlineMeetings/{meeting_id}/transcripts/{session.id}/content",
                         {"$format": "text/vtt"}, raw=True)

    def recording(self, meeting_id: str, session: Session, dest: Path) -> Path:
        """The recording file on disk (streamed when the client can, never sent anywhere else)."""
        url = f"{GRAPH}/me/onlineMeetings/{meeting_id}/recordings/{session.id}/content"
        headers = {"Authorization": f"Bearer {self.token()}"}
        try:
            if hasattr(self.http, "save"):
                return self.http.save(url, dest, headers=headers)
            dest.write_bytes(self.http.request("GET", url, headers=headers).body)
        except HttpError as exc:
            raise NotesError(f"Teams: HTTP {exc.status} downloading the recording") from None
        return dest


def _utc(stamp: str) -> datetime:
    """Graph times carry up to 7 fractional digits and a Z; seconds are enough here."""
    bare = re.sub(r"\.\d+", "", stamp).replace("Z", "+00:00")
    when = datetime.fromisoformat(bare)
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).astimezone(UTC)
