"""State folder ($HERMES_HOME/brief): seen ids, last successful run per source, saved editions."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .items import Item

SEEN_KEEP_DAYS = 14


def default_state_dir() -> Path:
    home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    return Path(home) / "brief"


def _read(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


class Store:
    def __init__(self, state_dir: Path) -> None:
        self.dir = state_dir
        self.editions = state_dir / "editions"
        self._seen_path = state_dir / "seen.json"
        self._runs_path = state_dir / "last_run.json"
        self._seen: dict[str, float] = _read(self._seen_path, {})
        self._runs: dict[str, float] = _read(self._runs_path, {})

    # -- seen items -------------------------------------------------------------------------
    def is_seen(self, uid: str) -> bool:
        return uid in self._seen

    def mark_seen(self, uids: list[str], now: float) -> None:
        cutoff = now - SEEN_KEEP_DAYS * 86400
        self._seen = {k: v for k, v in self._seen.items() if v >= cutoff}
        self._seen.update({uid: now for uid in uids})
        _write(self._seen_path, self._seen)

    # -- per-source watermark ---------------------------------------------------------------
    def since(self, source: str, now: float, lookback_hours: float) -> float:
        """Read from the last successful run, but never further back than the lookback."""
        floor = now - lookback_hours * 3600
        return max(self._runs.get(source, floor), floor)

    def mark_run(self, sources: list[str], now: float) -> None:
        self._runs.update({s: now for s in sources})
        _write(self._runs_path, self._runs)

    # -- editions ---------------------------------------------------------------------------
    def save_edition(self, day: str, text: str, ranked: list[Item], rest: list[Item], meta: dict) -> Path:
        data = {"day": day, "text": text, "meta": meta,
                "top": [asdict(i) for i in ranked], "rest": [asdict(i) for i in rest]}
        path = self.editions / f"{day}.json"
        _write(path, data)
        (self.editions / f"{day}.txt").write_text(text + "\n", encoding="utf-8")
        return path

    def latest_edition(self) -> dict[str, Any] | None:
        files = sorted(self.editions.glob("*.json")) if self.editions.is_dir() else []
        return _read(files[-1], None) if files else None


def now() -> float:
    return time.time()
