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
from test_queue import NIGHT, Stand
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
        for method in ("sendVideo", "sendPhoto", "sendMessage"):
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
        self.assertIn("Research (found with Google Search on", script_ask)
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

    def test_facts_are_read_with_or_without_bullets_and_each_is_kept_once(self):
        plain = ("Here is what I found:\nCAT 2026 is on Sunday, November 29, 2026.\nIIM Indore conducts CAT 2026.\n"
                 "CAT 2026 is held on Sunday, November 29, 2026.\n")  # 2.5 flash's shape: no "- ", one repeat
        self.assertEqual(research.facts(plain), ("CAT 2026 is on Sunday, November 29, 2026.", "IIM Indore conducts CAT 2026."))
        self.assertEqual(research.facts("Facts:\n- One fact here.\n2. Another fact here."),
                         ("One fact here.", "Another fact here."))

    def test_research_can_be_switched_off(self):
        self.brief("  research: false\n")
        ctx = chat.Context(self.home, self.http)
        found = research.gather(self.http, ctx.keys, ctx.settings, TOPIC, 45, date(2026, 11, 24))
        self.assertEqual((found.facts, found.skipped), ((), "studio.research is off"))
        self.assertEqual(self.http.calls, [])


if __name__ == "__main__":
    unittest.main()
