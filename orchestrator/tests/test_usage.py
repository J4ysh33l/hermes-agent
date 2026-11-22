"""Token log and /usage report: one line per call (failed ones too), Hermes hooks, no model call."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from orchestrator import llm, usage
from orchestrator.brief.net import HttpError, Response

NOW = datetime(2026, 11, 22, 9, 0, tzinfo=usage.TZ)


class FakeGemini:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.urls = reply, error, []

    def request(self, method, url, **kw):
        self.urls.append(url)
        if self.error:
            raise self.error
        return Response(200, json.dumps(self.reply).encode())


def answer(text="ok", **meta):
    return {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": text}]}}],
            "usageMetadata": meta}


class UsageCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"HERMES_HOME": self.tmp.name})
        self.env.start()
        self.log = Path(self.tmp.name) / "usage" / "calls.jsonl"

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def lines(self):
        return [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines()]

    def write(self, days_ago, workflow, step, model, tin, tout, ok=True):
        call = usage.Call((NOW - timedelta(days=days_ago)).isoformat(timespec="seconds"), workflow, step, "gemini",
                          model, tin, tout, ok=ok)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with self.log.open("a", encoding="utf-8") as fh:
            fh.write(call.line() + "\n")


class Client(UsageCase):
    def test_success_logs_one_line_with_all_token_buckets(self):
        http = FakeGemini(answer("hi", promptTokenCount=900, candidatesTokenCount=40, thoughtsTokenCount=60,
                                 cachedContentTokenCount=100))
        self.assertEqual(llm.gemini(http, "k", "gemini-3.1-flash-lite", "p", workflow="w", step="s"), "hi",
                         "hidden thinking text is not returned")
        [line] = self.lines()
        self.assertEqual((line["workflow"], line["step"], line["model"], line["in"], line["out"], line["reasoning"],
                          line["cached"], line["ok"]), ("w", "s", "gemini-3.1-flash-lite", 900, 40, 60, 100, True))
        self.assertEqual(len(self.log.read_text(encoding="utf-8").splitlines()), 1, "a single line per call")

    def test_failure_is_logged_then_raised(self):
        http = FakeGemini(error=HttpError(429, "https://x", "quota"))
        with self.assertRaises(HttpError):
            llm.gemini(http, "k", "m", "p", workflow="w", step="s")
        [line] = self.lines()
        self.assertFalse(line["ok"])
        self.assertIn("429", line["note"])

    def test_unwritable_log_never_breaks_the_call(self):
        with mock.patch.object(usage, "log_path", return_value=Path("/proc/nope/calls.jsonl")):
            self.assertEqual(llm.gemini(FakeGemini(answer("x")), "k", "m", "p", workflow="w", step="s"), "x")


class Report(UsageCase):
    def test_week_report_splits_by_workflow_and_model_and_prices_paid_tier(self):
        for day in range(7):
            self.write(day, "brief", "rank", "gemini-3.1-flash-lite", 4000, 400)
        self.write(1, "hermes", "telegram", "gemma-4-31b-it", 9000, 300)
        self.write(40, "brief", "rank", "gemini-3.1-flash-lite", 999999, 1)  # outside the window
        text = usage.report("week", now=NOW)
        self.assertIn("(8 calls)", text)
        self.assertIn("• brief/rank — 7 calls · 28.0k in · 2.8k out · avg 4.0k in", text)
        self.assertIn("• hermes/telegram — 1 calls · 9.0k in", text)
        # 7 * (4000 * 0.25 + 400 * 1.50) / 1e6 = 0.0112
        self.assertIn("$0.0112 for last 7 days", text)
        self.assertIn("No price listed for: gemma-4-31b-it", text)
        self.assertIn("hermes/telegram: average prompt 9.0k tokens", text)

    def test_busy_day_near_the_free_limit_is_flagged(self):
        for _ in range(360):
            self.write(0, "brief", "rank", "gemini-3.1-flash-lite", 100, 10)
        self.assertIn("busiest day used 360 of 500 free requests", usage.report("today", now=NOW))

    def test_empty_log_and_unknown_period(self):
        self.assertIn("No model calls logged.", usage.report("today", now=NOW))
        self.assertIn("/usage week", usage.handle_chat_command("fortnight"))

    def test_torn_line_is_skipped(self):
        self.write(0, "brief", "rank", "m", 10, 1)
        with self.log.open("a", encoding="utf-8") as fh:
            fh.write('{"ts": "2026-11-22T0')
        self.assertIn("(1 calls)", usage.report("today", now=NOW))


class HermesHooks(UsageCase):
    def plugin(self):
        spec = importlib.util.spec_from_file_location("orch_plugin", ROOT / "orchestrator/plugin/__init__.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_agent_turn_aux_call_and_error_are_logged(self):
        p = self.plugin()
        p.on_api_request(platform="telegram", provider="gemini", model="gemini-3.1-flash-lite", api_duration=1.5,
                         usage={"input_tokens": 2000, "prompt_tokens": 2400, "cache_read_tokens": 400,
                                "output_tokens": 150, "reasoning_tokens": 0})
        p.on_aux_call(aux_task="title_generation", provider="gemini", model="gemma-4-31b-it", error=None,
                      usage={"prompt_tokens": 300, "output_tokens": 12})
        p.on_api_error(platform="cron", provider="gemini", model="m", error_type="RateLimitError")
        lines = self.lines()
        self.assertEqual([(x["workflow"], x["step"], x["in"], x["out"], x["ok"]) for x in lines],
                         [("hermes", "telegram", 2400, 150, True), ("hermes", "aux:title_generation", 300, 12, True),
                          ("hermes", "cron", 0, 0, False)])
        self.assertEqual(lines[0]["cached"], 400)
        self.assertEqual(lines[0]["ms"], 1500)

    def test_hook_never_raises(self):
        p = self.plugin()
        with mock.patch.object(usage, "log_call", side_effect=RuntimeError("disk full")):
            p.on_api_request(platform="telegram", usage=None)

    def test_plugin_registers_the_three_hooks(self):
        hooks, cmds = {}, {}

        class Ctx:
            def register_command(self, name, handler, **kw):
                cmds[name] = handler

            def register_hook(self, name, fn):
                hooks[name] = fn

            def register_skill(self, name, path, description=""):
                pass

        self.plugin().register(Ctx())
        self.assertEqual(set(hooks), {"post_api_request", "api_request_error", "post_auxiliary_call"})
        self.assertIn("usage", cmds)


if __name__ == "__main__":
    unittest.main()
