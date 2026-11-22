"""Credentials. Hermes runs cron scripts with a sanitized environment, so the brief reads
``$HERMES_HOME/.env`` itself. Refresh tokens that rotate (Microsoft) live in token files in the
state folder (mode 0600), written by ``python -m orchestrator.brief auth ...``.

Keys read from .env:
  GEMINI_API_KEY (or GOOGLE_API_KEY)
  SLACK_BOT_TOKEN  (xoxb-, preferred) or SLACK_USER_TOKEN (xoxp-, scope search:read)
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET               Gmail (token file: tokens/google.json)
  MS_CLIENT_ID, MS_TENANT_ID                           Outlook (token file: tokens/microsoft.json)
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


class Secrets:
    """Process environment first, then the .env file. Token files under ``tokens/``."""

    def __init__(self, env_file: Path, token_dir: Path, environ: Mapping[str, str] | None = None) -> None:
        self._env = {**read_env_file(env_file), **(os.environ if environ is None else environ)}
        self._token_dir = token_dir

    def get(self, *names: str) -> str:
        return next((self._env[n] for n in names if self._env.get(n)), "")

    def token(self, name: str) -> dict[str, Any]:
        path = self._token_dir / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def save_token(self, name: str, data: dict[str, Any]) -> None:
        self._token_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._token_dir, 0o700)
        path = self._token_dir / f"{name}.json"
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        tmp.replace(path)
