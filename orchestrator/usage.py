"""Token log for every model call any workflow makes, and the /usage report. Never calls a model.

One JSON line per call in ``$HERMES_HOME/usage/calls.jsonl``:
  {"ts": "...+05:30", "workflow": "brief", "step": "rank", "provider": "gemini",
   "model": "gemini-3.1-flash-lite", "in": 3120, "out": 410, "cached": 0, "reasoning": 0,
   "ok": true, "ms": 2310, "note": ""}

Writers:
- ``orchestrator.llm``: every direct Gemini call (the brief's ranking, future workflows).
- ``orchestrator/plugin``: Hermes' own agent turns (``post_api_request``) and side calls such as
  titles and compression (``post_auxiliary_call``), with the token counts Hermes reports.
- ``python -m orchestrator.usage record ...``: anything else, e.g. a Claude task that knows its counts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

TZ = ZoneInfo("Asia/Kolkata")
PRICES = Path(__file__).resolve().parent / "prices.yaml"
PERIODS = {"today": 1, "day": 1, "week": 7, "month": 30}

USAGE_HELP = """**/usage** — tokens used by every model call (no command here uses the AI model)
/usage — today
/usage week — last 7 days
/usage month — last 30 days
Each shows: calls and input/output tokens per workflow and per model, the busiest day against
the free-tier daily limit, what the same use would cost on the paid tier, and what to trim.
/usage help (or -help) — this list · /menu — all your commands"""


@dataclass(frozen=True)
class Call:
    ts: str
    workflow: str
    step: str
    provider: str
    model: str
    input: int = 0
    output: int = 0
    cached: int = 0
    reasoning: int = 0
    ok: bool = True
    ms: int = 0
    note: str = ""

    def line(self) -> str:
        data = asdict(self)
        ordered = {k: data[k] for k in ("ts", "workflow", "step", "provider", "model")}
        ordered |= {"in": data["input"], "out": data["output"]}
        ordered |= {k: data[k] for k in ("cached", "reasoning", "ok", "ms", "note")}
        return json.dumps(ordered, ensure_ascii=False, separators=(", ", ": "))

    @classmethod
    def parse(cls, line: str) -> Call:
        data = json.loads(line)
        data["input"], data["output"] = data.pop("in", 0), data.pop("out", 0)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def log_path() -> Path:
    home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    return Path(home) / "usage" / "calls.jsonl"


def log_call(workflow: str, step: str, provider: str, model: str, *, input_tokens: int = 0, output_tokens: int = 0,
             cached: int = 0, reasoning: int = 0, ok: bool = True, ms: int = 0, note: str = "",
             path: Path | None = None) -> Call:
    """Append one line. Logging must never break the work it measures, so I/O errors are
    reported on stderr and swallowed."""
    call = Call(datetime.now(TZ).isoformat(timespec="seconds"), workflow, step, provider, model,
                int(input_tokens or 0), int(output_tokens or 0), int(cached or 0), int(reasoning or 0),
                bool(ok), int(ms), note[:200])
    target = path or log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(call.line() + "\n")
    except OSError as exc:
        print(f"usage log not written: {exc}", file=sys.stderr)
    return call


def read_calls(since: datetime, path: Path | None = None) -> list[Call]:
    target = path or log_path()
    if not target.is_file():
        return []
    calls = []
    for raw in target.read_text(encoding="utf-8").splitlines():
        try:
            call = Call.parse(raw)
        except (ValueError, TypeError):
            continue  # a torn line from a crash; skip it
        if datetime.fromisoformat(call.ts) >= since:
            calls.append(call)
    return calls


# ------------------------------------------------------------------ report
def _k(n: float) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(int(n))


def _prices() -> dict:
    return yaml.safe_load(PRICES.read_text(encoding="utf-8")) or {}


def _cost(call: Call, price: dict) -> float | None:
    if not price or price.get("input") is None or price.get("output") is None:
        return None
    cached_rate = price.get("cached_input", price["input"])
    fresh = max(call.input - call.cached, 0)
    return (fresh * price["input"] + call.cached * cached_rate + (call.output + call.reasoning) * price["output"]) / 1e6


def _group(calls: list[Call], key) -> dict[str, list[Call]]:
    groups: dict[str, list[Call]] = defaultdict(list)
    for call in calls:
        groups[key(call)].append(call)
    return dict(sorted(groups.items(), key=lambda kv: -sum(c.input + c.output for c in kv[1])))


def _row(name: str, calls: list[Call]) -> str:
    tin, tout = sum(c.input for c in calls), sum(c.output + c.reasoning for c in calls)
    failed = sum(not c.ok for c in calls)
    fail = f" · {failed} failed" if failed else ""
    return f"• {name} — {len(calls)} calls · {_k(tin)} in · {_k(tout)} out · avg {_k(tin / len(calls))} in{fail}"


def suggestions(calls: list[Call], prices: dict) -> list[str]:
    limits = prices.get("thresholds") or {}
    tips = []
    per_day = defaultdict(lambda: defaultdict(int))
    for c in calls:
        per_day[c.model][c.ts[:10]] += 1
    for model, days in per_day.items():
        rpd = ((prices.get("models") or {}).get(model) or {}).get("free_rpd")
        peak = max(days.values())
        if rpd and peak * 100 >= rpd * limits.get("free_rpd_warn_pct", 70):
            tips.append(f"{model}: busiest day used {peak} of {rpd} free requests. Move work to another model "
                        "or batch more items per call.")
    for name, group in _group([c for c in calls if c.ok], lambda c: f"{c.workflow}/{c.step}").items():
        avg = sum(c.input for c in group) / len(group)
        if avg > limits.get("avg_input_warn_tokens", 8000):
            tips.append(f"{name}: average prompt {_k(avg)} tokens. Filter more in scripts before the call.")
    failed = sum(not c.ok for c in calls)
    if calls and failed * 100 >= len(calls) * limits.get("failure_warn_pct", 10):
        tips.append(f"{failed} of {len(calls)} calls failed. Run /usage again after checking the model IDs "
                    "(python -m orchestrator.brief models).")
    return tips or ["Nothing to change: usage is well inside the free tier."]


def report(period: str = "today", now: datetime | None = None, path: Path | None = None) -> str:
    days = PERIODS.get(period, 1)
    now = now or datetime.now(TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    calls = read_calls(start, path)
    label = "today" if days == 1 else f"last {days} days"
    if not calls:
        return f"**Model usage · {label}**\nNo model calls logged."
    prices = _prices()
    tin, tout = sum(c.input for c in calls), sum(c.output + c.reasoning for c in calls)
    out = [f"**Model usage · {label}** ({len(calls)} calls)", f"Total: {_k(tin)} in · {_k(tout)} out", "",
           "**By workflow**"]
    out += [_row(name, group) for name, group in _group(calls, lambda c: f"{c.workflow}/{c.step}").items()]
    out += ["", "**By model**"]
    out += [_row(name, group) for name, group in _group(calls, lambda c: c.model).items()]
    costs = [(_cost(c, (prices.get("models") or {}).get(c.model)), c) for c in calls]
    known = sum(cost for cost, _ in costs if cost is not None)
    unpriced = sorted({c.model for cost, c in costs if cost is None})
    monthly = known / days * 30
    out += ["", f"**If this ran on the paid tier:** ${known:.4f} for {label} (≈ ${monthly:.2f} a month)"]
    if unpriced:
        out.append(f"No price listed for: {', '.join(unpriced)} (orchestrator/prices.yaml)")
    out += ["", "**Suggestions**"] + [f"• {tip}" for tip in suggestions(calls, prices)]
    return "\n".join(out)


def handle_chat_command(raw_args: str) -> str:
    period = (raw_args or "").strip().lower() or "today"
    return report(period) if period in PERIODS else USAGE_HELP


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.usage")
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report")
    rep.add_argument("period", nargs="?", default="today", choices=sorted(PERIODS))
    rec = sub.add_parser("record", help="log a call made outside orchestrator.llm (e.g. a Claude task)")
    for name in ("workflow", "step", "provider", "model"):
        rec.add_argument(name)
    rec.add_argument("--in", dest="input_tokens", type=int, default=0)
    rec.add_argument("--out", dest="output_tokens", type=int, default=0)
    rec.add_argument("--failed", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "report":
        print(report(args.period))
        return 0
    print(log_call(args.workflow, args.step, args.provider, args.model, input_tokens=args.input_tokens,
                   output_tokens=args.output_tokens, ok=not args.failed).line())
    return 0


if __name__ == "__main__":
    sys.exit(main())
