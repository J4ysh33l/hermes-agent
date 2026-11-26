"""Every step of a studio job, timed, with the tokens it used: ``steps.jsonl`` in the job's folder, and the
report (``report.md``) that goes out with the video.

Where the numbers come from:
- Gemini (and Claude API) calls: the usage log (``orchestrator/usage.py``), each line tagged with the job.
- Claude through the handoff repo: the issue's opened/closed times from GitHub, and the tokens the run
  posted on the issue itself (``tools/usage_hook.py``, a Stop hook Hermes keeps in the repo). Fetched once
  and kept in ``claude-usage.json``.
- Hermes' own work (checks, voice and render, cover, QC, delivery): timed here; it uses no tokens.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator import usage

FILE = "steps.jsonl"
CLAUDE = "claude-usage.json"
REPORT = "report.md"


def _now() -> str:
    return datetime.now(usage.TZ).isoformat(timespec="seconds")


def mark(folder: Path, step: str, event: str, **fields: Any) -> None:
    """One line: ``event`` is "asked" / "answered" (Claude), "done" (timed work) or "note"."""
    line = {"ts": _now(), "step": step, "event": event, **{k: v for k, v in fields.items() if v not in ("", None)}}
    try:
        with folder.joinpath(FILE).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass  # the record must never break the work


@contextmanager
def timed(folder: Path, step: str, note: str = "") -> Iterator[None]:
    started, at = time.monotonic(), _now()
    failed = ""
    try:
        yield
    except Exception as exc:  # the row says so; the error goes on to whoever handles it
        failed = "failed: " + ((str(exc).splitlines() or [""])[0][:120] or exc.__class__.__name__)
        raise
    finally:
        mark(folder, step, "done", started=at, seconds=round(time.monotonic() - started, 1),
             note=" · ".join(x for x in (note, failed) if x))


def read(folder: Path) -> list[dict[str, Any]]:
    path = folder / FILE
    if not path.is_file():
        return []
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(raw))
        except ValueError:
            continue
    return rows


def claude_usage(folder: Path, hand: Any, issues: list[int]) -> dict[str, dict[str, Any]]:
    """Per issue: GitHub's times and the run's posted tokens. Cached once both are known."""
    path = folder / CLAUDE
    known = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    for n in issues:
        got = known.get(str(n), {})
        if got.get("closed_at") and got.get("tokens"):
            continue
        if hand is not None:
            got.update({k: v for k, v in hand.issue(n).items() if v})
            tokens = hand.usage(n)
            if tokens:
                got["tokens"] = tokens
        known[str(n)] = got
    try:
        path.write_text(json.dumps(known, indent=1), encoding="utf-8")
    except OSError:
        pass
    return known


# ------------------------------------------------------------------ the report


def _t(stamp: str) -> datetime | None:
    try:
        when = datetime.fromisoformat(stamp)
    except (ValueError, AttributeError):
        return None
    return when.astimezone(usage.TZ)  # a stamp without a zone (job.json's "created") is this server's clock


def _span(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    seconds = round(seconds)
    return f"{seconds // 3600} h {seconds % 3600 // 60} min" if seconds >= 3600 else \
        f"{seconds // 60} min {seconds % 60} s" if seconds >= 60 else f"{seconds} s"


def _k(n: int) -> str:
    return f"{n / 1e6:.2f}M" if n >= 1_000_000 else f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _price(model: str) -> dict[str, Any]:
    try:
        return (usage._prices().get("models") or {}).get(model) or {}
    except OSError:
        return {}


def _cost(model: str, fresh_in: int, out: int, cached: int, written: int = 0) -> float | None:
    """List-price USD (what the same tokens cost on the paid API); None when the price isn't known.
    Prompt-cache writes cost ``cache_write`` (input price when not given)."""
    p = _price(model)
    if p.get("input") is None or p.get("output") is None:
        return None
    return (fresh_in * p["input"] + written * (p.get("cache_write") or p["input"]) + out * p["output"]
            + cached * (p.get("cached_input") or p["input"])) / 1e6


def build(job: dict[str, Any], folder: Path, calls: list[usage.Call], claude: dict[str, dict[str, Any]]) -> str:
    """The markdown report: one row per step, then totals."""
    rows: list[tuple[datetime, list[str]]] = []
    tokens = {"gemini": [0, 0, 0, 0], "claude": [0, 0, 0, 0]}  # in, out, cached, calls
    money: list[float] = []
    unknown_price: set[str] = set()

    # model calls Hermes made itself, grouped by step and model
    groups: dict[tuple[str, str], list[usage.Call]] = {}
    for c in calls:
        groups.setdefault((c.step, c.model), []).append(c)
    for (step, model), group in groups.items():
        ok = [c for c in group if c.ok]
        fin, out, cached = (sum(c.input for c in ok), sum(c.output + c.reasoning for c in ok), sum(c.cached for c in ok))
        side = "claude" if group[0].provider == "anthropic" else "gemini"
        for i, v in enumerate((fin, out, cached, len(group))):
            tokens[side][i] += v
        cost = _cost(model, fin, out, cached)
        money.append(cost) if cost is not None else unknown_price.add(model) if ok else None
        busy = len(group) - len(ok)
        note = f"{len(ok)} call(s)" + (f", {busy} busy/failed attempt(s)" if busy else "")
        first = min(_t(c.ts) for c in group)
        rows.append((first, [step, model, first.strftime("%d %b %H:%M:%S"), _span(sum(c.ms for c in group) / 1000),
                             f"{_k(fin)} / {_k(out)} / {_k(cached)}", note]))

    # Claude through the handoff repo: one row per issue
    asked = [r for r in read(folder) if r.get("event") == "asked"]
    for r in asked:
        n = str(r.get("issue", ""))
        info = claude.get(n, {})
        opened, closed = _t(info.get("created_at") or r["ts"]), _t(info.get("closed_at") or "")
        tok = info.get("tokens") or {}
        model = tok.get("model") or "claude (your plan)"
        if tok:
            fin, out = tok.get("input_tokens", 0), tok.get("output_tokens", 0)
            written, cached = tok.get("cache_creation_input_tokens", 0), tok.get("cache_read_input_tokens", 0)
            for i, v in enumerate((fin + written, out, cached, tok.get("calls", 0))):
                tokens["claude"][i] += v
            cost = _cost(model, fin, out, cached, written)
            money.append(cost) if cost is not None else unknown_price.add(model)
            work = _span((_t(tok["last"]) - _t(tok["first"])).total_seconds()) if tok.get("first") and tok.get("last") else "?"
            used = f"{_k(fin + written)} / {_k(out)} / {_k(cached)}"
            note = f"issue #{n}, {tok.get('calls', 0)} call(s), Claude worked {work}"
        else:
            used, note = "not reported", f"issue #{n}" + (" (still open)" if not closed else ", the run posted no token count")
        if r.get("fire_error"):
            note += f"; fire failed: {r['fire_error']}"
        took = _span((closed - opened).total_seconds()) if opened and closed else "waiting"
        rows.append((opened, [r["step"] + (f" fix {r['round']}" if r.get("round") else ""), model,
                              opened.strftime("%d %b %H:%M:%S"), took, used, note]))

    # Hermes' own work
    for r in read(folder):
        if r.get("event") == "done":
            at = _t(r.get("started") or r["ts"])
            rows.append((at, [r["step"], "Hermes (this server)", at.strftime("%d %b %H:%M:%S"), _span(r.get("seconds")),
                              "—", r.get("note", "")]))

    rows.sort(key=lambda row: row[0])
    created = _t(job.get("created", "")) or (rows[0][0] if rows else None)
    ends = [_t(r["ts"]) for r in read(folder)]
    end = max([e for e in ends if e] or [created]) if created else None
    title = job.get("title") or job.get("id", "")
    lines = [f"# Report · {title} (job {job.get('id', '')})", "",
             f"Started {created:%d %b %Y %H:%M} IST · finished {end:%d %b %H:%M} · total {_span((end - created).total_seconds())}"
             if created and end else "", "",
             "Tokens are input / output / cached-input. Input includes prompt-cache writes; output includes thinking.", "",
             "| # | Step | Done by | Started (IST) | Took | Tokens in / out / cached | Notes |",
             "|---|---|---|---|---|---|---|"]
    lines += [f"| {i} | " + " | ".join(cells) + " |" for i, (_at, cells) in enumerate(rows, 1)]
    g, c = tokens["gemini"], tokens["claude"]
    lines += ["", "## Totals",
              f"- Gemini: {_k(g[0])} in, {_k(g[1])} out, {_k(g[2])} cached over {g[3]} call(s) (free tier: no charge)",
              f"- Claude: {_k(c[0])} in, {_k(c[1])} out, {_k(c[2])} cached over {c[3]} call(s) "
              "(through the handoff: comes out of your Claude plan's usage, no charge)"]
    if money:
        lines.append(f"- The same tokens at paid API list prices: about ${sum(money):.2f}"
                     + (f" (no price known for {', '.join(sorted(unknown_price))})" if unknown_price else ""))
    return "\n".join(lines).replace("\n\n\n", "\n\n") + "\n"


def short(report: str) -> str:
    """The totals, for the Telegram message (the full table goes as report.md)."""
    head = report.split("\n", 3)[2] if report.count("\n") > 2 else ""
    totals = report.split("## Totals\n", 1)[1].strip() if "## Totals\n" in report else ""
    return "\n".join(x for x in ("📊 " + head, totals) if x.strip())
