"""What the watcher remembers: ``$HERMES_HOME/watch/watches.json`` (0600).

Each watch, under its number: the page, how to read it (``spec``), what you care about, how often,
paused or not, Claude's setup research and Gemini's notes on or off, the items seen last time
(link → title), when it was last checked and changed, failures in a row, and Claude's setup research
still open.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


class Store:
    def __init__(self, home: Path) -> None:
        self.path = home / "watch" / "watches.json"
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}
        self.watches: dict[str, dict] = self.data.setdefault("watches", {})

    def save(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=1)
        tmp.replace(self.path)

    def add(self, url: str, name: str, what: str, spec: dict, every_hours: float, claude: bool) -> str:
        number = str(self.data.get("next", 1))
        self.data["next"] = int(number) + 1
        self.watches[number] = {"url": url, "name": name, "what": what, "spec": spec, "every": every_hours,
                                "paused": False, "claude": claude, "notes": True, "items": None, "checked": 0.0,
                                "changed": 0.0, "fails": 0, "error": "", "asks": []}
        return number

    def get(self, number: str) -> dict | None:
        return self.watches.get(number.strip().lstrip("#"))
