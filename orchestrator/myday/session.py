"""Everything one command or cron run needs: settings, the clock, the state file and To Do.
Logins are touched only when first used, so a help text never makes a network call."""

from __future__ import annotations

import time
from datetime import date, datetime
from functools import cached_property
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.brief.creds import Secrets
from orchestrator.brief.items import SourceError
from orchestrator.brief.net import Http, HttpError, UrllibHttp
from orchestrator.brief.sources import outlook
from orchestrator.brief.store import default_state_dir as brief_state_dir

from . import settings
from .errors import MyDayError
from .game import State
from .todo import Todo


def default_state_dir() -> Path:
    return brief_state_dir().parent / "myday"


class Session:
    def __init__(self, state_dir: Path | None = None, http: Http | None = None, now: float | None = None) -> None:
        self.state_dir = state_dir or default_state_dir()
        self.http = http or UrllibHttp()
        self.now = time.time() if now is None else now
        self.settings = settings.load(self.state_dir)
        self.tz = ZoneInfo(self.settings.timezone)
        home = self.state_dir.parent
        self.secrets = Secrets(home / ".env", home / "brief" / "tokens")
        self.state = State.load(self.state_dir)
        self._tokens: dict[str, str] = {}

    @property
    def local_now(self) -> datetime:
        return datetime.fromtimestamp(self.now, self.tz)

    @property
    def today(self) -> date:
        return self.local_now.date()

    def token(self, scopes: str) -> str:
        """An access token for ``scopes`` from the brief's Outlook login; saves the rotated refresh token."""
        if scopes not in self._tokens:
            try:
                fresh = outlook.refresh(self.http, self.secrets.get("MS_CLIENT_ID"), self.secrets.get("MS_TENANT_ID"),
                                        self.secrets.token("microsoft"), scopes)
            except (SourceError, HttpError) as exc:
                raise MyDayError(f"Microsoft login: {exc}") from None
            self.secrets.save_token("microsoft", {"refresh_token": fresh["refresh_token"],
                                                  "saved_at": fresh["saved_at"]})
            self._tokens[scopes] = fresh["access_token"]
        return self._tokens[scopes]

    @cached_property
    def todo(self) -> Todo:
        return Todo(self.http, lambda: self.token(outlook.TODO_SCOPES), self.tz)

    def save(self) -> None:
        self.state.save()
