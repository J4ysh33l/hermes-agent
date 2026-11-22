"""Everything one command needs, built once: settings, secrets, the clock, Slack and Outlook
access, the people directory and the plan store. Logins are only touched when first used, so a
help text or a rejected command never makes a network call."""

from __future__ import annotations

import time
from datetime import datetime
from functools import cached_property
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http, UrllibHttp

from . import graph, settings
from .errors import OutreachError
from .people import Directory
from .plan import Store


class Session:
    def __init__(self, state_dir: Path, http: Http | None = None, now: float | None = None) -> None:
        self.state_dir = state_dir
        self.http = http or UrllibHttp()
        self.now = time.time() if now is None else now
        self.settings = settings.load(state_dir)
        self.tz = ZoneInfo(self.settings.timezone)
        self.secrets = Secrets(state_dir.parent / ".env", state_dir / "tokens")
        self.store = Store(state_dir, self.tz)
        self._graph = ""

    @property
    def local_now(self) -> datetime:
        return datetime.fromtimestamp(self.now, self.tz)

    @property
    def gemini_key(self) -> str:
        return self.secrets.get("GEMINI_API_KEY", "GOOGLE_API_KEY")

    @property
    def slack_token(self) -> str:
        token = self.secrets.get("SLACK_USER_TOKEN")
        if not token:
            raise OutreachError("SLACK_USER_TOKEN is not set in $HERMES_HOME/.env (sending needs the user token).")
        return token

    def graph_token(self) -> str:
        if not self._graph:
            self._graph = graph.access(self.http, self.secrets)
        return self._graph

    @cached_property
    def directory(self) -> Directory:
        outlook = self.graph_token if self.secrets.token("microsoft") else None
        return Directory(self.http, self.slack_token, self.state_dir, outlook, self.now)
