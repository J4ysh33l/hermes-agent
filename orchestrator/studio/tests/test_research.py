"""Call 0: the researcher, against a fake Gemini with Google Search.

The promises tested: the researcher searches (Google Search grounding) with its own prompt; its facts
reach the script writer as part of the notes, so a researched number may go on screen; its sources are
kept with the job and reach Telegram with the video; a model that may not search hands over to the
next; when none can, the video is still written from your notes and you are told why; research can be
switched off.

Run: python3 orchestrator/studio/tests/test_research.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator/brief/tests"))
sys.path.insert(0, str(Path(__file__).parent))

from fakes import FakeHttp, http_error

from orchestrator.brief.net import Response
from test_queue import DAY, NIGHT, Hub, Stand
from test_writer import BOARD, SCRIPT

from orchestrator.studio import chat, queue, research, settings

GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/"
TG = "https://api.telegram.org/bott/"
TOPIC = "CAT, the MBA entrance exam of the IIMs."
FOUND = ("Here is what I found:\n"
         "- CAT 2026 is conducted by IIM Indore on 29 November 2026 (iimcat.ac.in, November 2026).\n"
         "- Only 12 candidates scored 100 percentile in CAT 2025 (careers360.com, December 2025).\n"
         "- ok\n")
RESEARCHED = {**SCRIPT, "lines": [*SCRIPT["lines"][:4], {"say": "Only *12* people scored a perfect 100."}]}
SHOWN = {**BOARD,  # no Bun numbers on screen: only the researched 12
         "hooks": [*BOARD["hooks"][:2], {"type": "title", "say": BOARD["hooks"][2]["say"], "text": "25x"}],
         "scenes": [BOARD["scenes"][0], {"type": "title", "say": BOARD["scenes"][1]["say"], "text": "Faster"},
                    BOARD["scenes"][2], {"type": "stat", "say": "Only *12* people scored a perfect 100.",
                                         "value": 12, "label": "scored 100 percentile"}]}


class Researching(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = mock.patch.dict("os.environ", {"HERMES_HOME": str(self.home), "PATH": os.environ["PATH"]}, clear=True)
        self.env.start()
        (self.home / "brief").mkdir()
        (self.home / "studio/profiles").mkdir(parents=True)
        (self.home / "studio/profiles/shorts.yaml").write_text("writing:\n  seconds: 15\n", encoding="utf-8")
        self.brief("")
        (self.home / ".env").write_text("GEMINI_API_KEY=g\nTELEGRAM_BOT_TOKEN=t\nTELEGRAM_HOME_CHANNEL=42\n",
                                        encoding="utf-8")
        self.searchers = {"gemini-2.5-flash": FOUND}  # model → its answer; missing = may not search (429)
        self.writing = [RESEARCHED, SHOWN]
        self.http = FakeHttp().on("POST", GEMINI, self.gemini)
        for method in ("sendVideo", "sendPhoto", "sendMessage", "sendDocument"):
            self.http.on("POST", TG + method, {"ok": True})

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def brief(self, extra: str) -> None:
        (self.home / "brief/brief.yaml").write_text("studio:\n  profile: shorts\n  writer: gemini\n" + extra,
                                                    encoding="utf-8")

    def gemini(self, call):
        model = call.url.split("models/")[1].split(":")[0]
        if "tools" not in call.json_body:
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(self.writing.pop(0))}]}}]}
        if model not in self.searchers:
            return http_error(429)(call)
        return {"candidates": [{"content": {"parts": [{"text": self.searchers[model]}]},
                                "groundingMetadata": {"groundingChunks": [
                                    {"web": {"title": "iimcat.ac.in", "uri": "https://vertex/1"}},
                                    {"web": {"title": "careers360.com", "uri": "https://vertex/2"}}]}}]}

    def prompts(self) -> list[str]:
        return [c.json_body["contents"][0]["parts"][-1]["text"] for c in self.http.calls if c.url.startswith(GEMINI)]

    def test_the_researchers_facts_reach_the_writer_the_checks_and_telegram(self):
        reply = chat.handle("make " + TOPIC, self.home, self.http)
        self.assertIn("🔎 research: 2 facts by gemini-2.5-flash from iimcat.ac.in, careers360.com", reply)
        search, script_ask = self.http.calls[0], self.prompts()[1]
        self.assertEqual(search.json_body["tools"], [{"google_search": {}}])
        self.assertIn("Studio research", search.json_body["contents"][0]["parts"][0]["text"])
        self.assertIn(TOPIC, search.json_body["contents"][0]["parts"][0]["text"])
        self.assertIn("Research (found with web search on", script_ask)
        self.assertIn("Only 12 candidates scored 100 percentile in CAT 2025", script_ask)
        self.assertNotIn("Here is what I found", script_ask)  # facts only, one per line
        job = queue.jobs(self.home)[0]
        self.assertEqual(job.state, "ready")  # the researched 12 may go on screen: it is in the notes
        self.assertEqual(job.folder.joinpath("asked.txt").read_text(encoding="utf-8"), TOPIC)
        stand = Stand()
        queue.run(chat.Context(self.home, self.http), NIGHT, False, stand.tools())
        message = [c for c in self.http.calls if c.url == TG + "sendMessage"][-1].json_body["text"]
        self.assertIn("Facts researched from: iimcat.ac.in, careers360.com", message)

    def test_a_model_that_may_not_search_hands_over_and_without_any_the_notes_alone_are_used(self):
        self.searchers = {"gemini-2.5-flash-lite": FOUND}
        found = research.gather(self.http, settings.Keys("g"), settings.Settings(), TOPIC, 45, date(2026, 11, 24))
        self.assertEqual((found.model, len(found.facts)), ("gemini-2.5-flash-lite", 2))
        self.searchers = {}
        self.writing = [SCRIPT, BOARD]
        reply = chat.handle("make " + TOPIC + " Bun is a JavaScript runtime written in Zig by Jarred Sumner. It "
                            "installs packages up to 25 times faster than npm. Its test runner, bundler and package "
                            "manager ship in one binary. Jarred said: \"Bun is designed as a drop-in replacement for "
                            "Node.js.\"", self.home, self.http)
        self.assertIn("research skipped (gemini-2.5-flash: HTTP 429; gemini-2.5-flash-lite: HTTP 429)", reply)
        self.assertIn("written by gemini-3.5-flash-lite", reply)
        job = queue.jobs(self.home)[-1]
        self.assertNotIn("Research", job.folder.joinpath("notes.txt").read_text(encoding="utf-8"))

    def test_claude_researches_with_its_own_web_search_when_it_writes_and_gemini_is_not_called(self):
        claude = "https://api.anthropic.com/v1/messages"
        searched = {"content": [
            {"type": "text", "text": "Let me search."},
            {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "CAT 2026"}},
            {"type": "web_search_tool_result", "tool_use_id": "s1", "content": [
                {"type": "web_search_result", "url": "https://www.iimcat.ac.in/x", "title": "CAT"}]},
            {"type": "text", "text": FOUND, "citations": [
                {"type": "web_search_result_location", "url": "https://careers360.com/y", "cited_text": "12"}]}],
            "stop_reason": "end_turn", "usage": {"input_tokens": 900, "output_tokens": 300}}
        self.http.on("POST", claude, searched)
        st = settings.Settings(writer="claude", claude_via="api")
        found = research.gather(self.http, settings.Keys("g", "sk"), st, TOPIC, 45, date(2026, 11, 24), "claude-api")
        self.assertEqual((found.model, len(found.facts)), ("claude-sonnet-5-5", 2))  # the smaller searcher
        self.assertEqual(found.sites(), ["iimcat.ac.in", "careers360.com"])
        body = self.http.calls[-1].json_body
        self.assertEqual((body["model"], body["tools"][0]["type"]), ("claude-sonnet-5-5", "web_search_20260209"))
        self.assertFalse([c for c in self.http.calls if c.url.startswith(GEMINI)])
        research.gather(self.http, settings.Keys("g", "sk"), settings.Settings(research_claude="claude-haiku-5-5"),
                        TOPIC, 45, date(2026, 11, 24), "claude-api")
        self.assertEqual(self.http.calls[-1].json_body["tools"][0]["type"], "web_search_20250305")  # Haiku: basic search
        handoff = research.gather(self.http, settings.Keys("g"), st, TOPIC, 45, date(2026, 11, 24), "handoff")
        self.assertEqual(handoff.skipped, "Claude researches through the handoff")  # its own issue, not Gemini
        self.assertFalse([c for c in self.http.calls if c.url.startswith(GEMINI)])
        gem = research.gather(self.http, settings.Keys("g"), settings.Settings(researcher="gemini"), TOPIC, 45,
                              date(2026, 11, 24), "handoff")
        self.assertEqual(gem.model, "gemini-2.5-flash")

    def test_facts_are_read_with_or_without_bullets_and_each_is_kept_once(self):
        plain = ("Here is what I found:\nCAT 2026 is on Sunday, November 29, 2026.\nIIM Indore conducts CAT 2026.\n"
                 "CAT 2026 is held on Sunday, November 29, 2026.\n")  # 2.5 flash's shape: no "- ", one repeat
        self.assertEqual(research.facts(plain), ("CAT 2026 is on Sunday, November 29, 2026.", "IIM Indore conducts CAT 2026."))
        self.assertEqual(research.facts("Facts:\n- One fact here.\n2. Another fact here."),
                         ("One fact here.", "Another fact here."))

    def test_on_the_plan_a_sonnet_subagent_researches_inside_the_writing_run_and_gemini_is_not_called(self):
        (self.home / ".env").write_text("GEMINI_API_KEY=g\nGITHUB_HANDOFF_TOKEN=g\n", encoding="utf-8")
        self.brief("  writer: claude\n  handoff_repo: me/hand\n")  # claude_via: handoff (the default)
        hub = Hub(self.http)
        reply = chat.handle("make " + TOPIC, self.home, self.http)
        self.assertIn("issue #1", reply)
        self.assertFalse([c for c in self.http.calls if c.url.startswith(GEMINI)])
        job_id = queue.jobs(self.home)[0].id
        ask, folder = hub.issues[1]["body"], f"studio/{job_id}"
        self.assertIn('Part 0: research, by a subagent', ask)
        self.assertIn('model "sonnet"', ask)
        self.assertIn(f"Read {folder}/research-brief.md", ask)
        self.assertIn("1 of 3: the script", ask)  # the same run writes the script and the direction
        self.assertIn("Studio research", hub.files[f"{folder}/research-brief.md"])
        self.assertIn(TOPIC, hub.files[f"{folder}/research-brief.md"])
        hub.answer(1, {f"{folder}/research.txt": FOUND, f"{folder}/script.json": json.dumps(RESEARCHED),
                       f"{folder}/storyboard.json": json.dumps(SHOWN)})
        queue.run(chat.Context(self.home, self.http), DAY, False, Stand().tools())
        job = queue.load(self.home, job_id)
        self.assertEqual(job.state, "ready")  # the researched 12 on screen passes: it counts as notes
        self.assertIn("research: 2 facts by claude sonnet (subagent, handoff) from iimcat.ac.in, careers360.com",
                      job.data["research"])
        self.assertIn("Only 12 candidates scored 100 percentile", job.folder.joinpath("notes.txt").read_text(encoding="utf-8"))
        self.assertEqual(len(hub.issues), 1)  # research, script and direction: one run

    def test_the_checker_claude_runs_counts_its_research_as_notes(self):
        import subprocess
        from orchestrator.studio import brief, handoff, profile
        for path, text in handoff.tools().items():
            (self.home / path).parent.mkdir(parents=True, exist_ok=True)
            (self.home / path).write_text(text, encoding="utf-8")
        job = self.home / "studio/j"
        job.mkdir(parents=True)
        job.joinpath("rules.json").write_text(brief.params(profile.load("default", self.home), TOPIC, 15).dumps())
        job.joinpath("script.json").write_text(json.dumps(RESEARCHED))
        job.joinpath("storyboard.json").write_text(json.dumps(SHOWN))
        check = lambda: subprocess.run([sys.executable, "tools/check.py", "direction", "studio/j"], cwd=self.home,
                                       capture_output=True, text=True, timeout=60, check=False)
        self.assertIn("the number 12 is not in the notes", check().stdout)
        job.joinpath("research.txt").write_text(FOUND)
        self.assertEqual(check().stdout.strip(), "OK: ready to hand in")

    def test_whatever_stops_gemini_the_research_goes_to_claude_on_the_claude_path(self):
        (self.home / "brief/brief.yaml").write_text("studio:\n  profile: shorts\n  writer: claude\n"
                                                    "  researcher: gemini\n  handoff_repo: me/hand\n", encoding="utf-8")
        hub = Hub(self.http)
        failures = {"no connection": http_error(0), "quota used up": http_error(429),
                    "unreadable": lambda _c: Response(200, b"<html>busy</html>", {})}
        for why, fail in failures.items():
            self.http.on("POST", GEMINI, fail)
            (self.home / ".env").write_text("GEMINI_API_KEY=g\nGITHUB_HANDOFF_TOKEN=g\n", encoding="utf-8")
            chat.handle("make " + TOPIC, self.home, self.http)
            self.assertIn("Studio research", hub.issues[len(hub.issues)]["body"], why)
        (self.home / ".env").write_text("GITHUB_HANDOFF_TOKEN=g\n", encoding="utf-8")  # no Gemini key at all
        chat.handle("make " + TOPIC, self.home, self.http)
        self.assertIn("Studio research", hub.issues[len(hub.issues)]["body"])
        self.assertEqual(len(hub.issues), 4)

    def test_research_can_be_switched_off(self):
        self.brief("  research: false\n")
        ctx = chat.Context(self.home, self.http)
        found = research.gather(self.http, ctx.keys, ctx.settings, TOPIC, 45, date(2026, 11, 24))
        self.assertEqual((found.facts, found.skipped), ((), "studio.research is off"))
        self.assertEqual(self.http.calls, [])


if __name__ == "__main__":
    unittest.main()
