"""Custom scenes (custom.py): a picture the library does not have, built for one video and checked.

The promises tested: code that reaches outside the page or is not deterministic is refused before it
runs; without a way to build it (no ANTHROPIC_API_KEY) a custom scene is drawn as its fallback and the
reason is named; Claude's component goes through TypeScript and a real probe render, a failure goes back
to Claude with the error and the fix is used, the reviewer sees the frames; a component that passed is
cached, so the same scene is never paid for twice. The real-render tests need remotion/node_modules
(install.sh) and STUDIO_BROWSER optionally names a Chrome headless shell.

Run: python3 orchestrator/studio/tests/test_custom.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator/brief/tests"))

from fakes import FakeHttp

from orchestrator.studio import cover, custom, profile, settings, storyboard

CLAUDE = "https://api.anthropic.com/v1/messages"
RACE = (Path(__file__).parent / "data/race.tsx").read_text(encoding="utf-8")
HAS_REMOTION = (custom.PROJECT / "node_modules/.bin/remotion").is_file()
BOARD = {"title": "Bun", "scenes": [
    {"type": "title", "say": "Bun installs packages fast.", "text": "Bun is fast"},
    {"type": "custom", "say": "npm crawls. Bun is done, *twenty five* times faster.", "brief": "two lanes race",
     "props": {"slow": "npm install", "fast": "bun install", "times": 25},
     "fallback": {"type": "stat", "value": 25, "suffix": "×", "label": "faster than npm"}}]}


def reply(text: str) -> dict:
    return {"stop_reason": "end_turn", "usage": {}, "content": [{"type": "text", "text": text}]}


class Checks(unittest.TestCase):
    def test_code_that_reaches_outside_the_page_or_is_not_deterministic_is_refused(self):
        self.assertEqual(custom.static_problems(RACE), [])
        bad = 'import fs from "fs";\nexport default function S() { fetch("https://x"); return Math.random(); }'
        problems = " | ".join(custom.static_problems(bad))
        for expected in ("import 'fs' is not allowed", "no network", "no randomness"):
            self.assertIn(expected, problems)
        self.assertIn("no timers", " ".join(custom.static_problems(RACE + "\nsetTimeout(() => 1, 5);")))


class Preparing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = mock.patch.dict("os.environ", {"HERMES_HOME": str(self.home)})
        self.env.start()
        self.board = storyboard.parse(BOARD, self.home)
        self.look = profile.load("default", self.home)
        self.settings = settings.Settings(video_browser=os.environ.get("STUDIO_BROWSER", ""), custom_review=True)
        self.answers: list[str] = []
        self.http = FakeHttp().on("POST", CLAUDE, lambda _call: reply(self.answers.pop(0)))

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def prepare(self, keys: settings.Keys, name: str = "job") -> custom.Result:
        job = self.home / name
        job.mkdir()
        result = custom.prepare(self.http, keys, self.settings, self.home, self.board, self.look, job)
        self.addCleanup(custom.clean, result.entry)
        return result

    def test_without_a_way_to_build_it_the_fallback_is_drawn_and_the_reason_named(self):
        result = self.prepare(settings.Keys())
        self.assertEqual([s.type for s in result.board.scenes], ["title", "stat"])
        self.assertEqual(result.board.scenes[1].fields["value"], 25)
        self.assertEqual(result.entry, "src/index.ts")
        self.assertIn("drawn as its fallback (stat): no ANTHROPIC_API_KEY", result.notes[0])

    @unittest.skipUnless(HAS_REMOTION, "remotion not installed (install.sh)")
    def test_claudes_component_is_typechecked_drawn_repaired_reviewed_and_cached(self):
        broken = RACE.replace("const theme = useTheme();", 'const theme = useTheme();\n  const wrong: number = "x";')
        self.answers = [f"```tsx\n{broken}```", f"```tsx\n{RACE}```", "OK"]
        result = self.prepare(settings.Keys(claude="a"))
        self.assertEqual([s.type for s in result.board.scenes], ["title", "custom"])
        self.assertIn("scene 2: custom scene built", result.notes)
        prompts = [c.json_body["messages"][0]["content"] for c in self.http.calls]
        self.assertIn("two lanes race", prompts[0][-1]["text"])
        self.assertIn("error TS", prompts[1][-1]["text"])  # the fix round sees the compiler's words
        self.assertEqual([b["type"] for b in prompts[2]][:-1], ["image"] * 3)  # the reviewer sees 3 frames
        entry = custom.PROJECT / result.entry
        self.assertIn('"scene02": S0', entry.read_text(encoding="utf-8"))
        self.assertTrue((self.home / "job/custom/scene02.tsx").is_file())
        again = self.prepare(settings.Keys(claude="a"), "job2")  # same scene: from the cache, no call
        self.assertIn("scene 2: custom scene cached", again.notes)
        self.assertEqual(len(self.http.calls), 3)

    @unittest.skipUnless(HAS_REMOTION, "remotion not installed (install.sh)")
    def test_a_scene_that_cannot_be_fixed_falls_back_and_names_the_problem(self):
        crash = RACE.replace("const frame = useCurrentFrame();", 'const frame = useCurrentFrame();\n  if (frame > 5) throw new Error("boom");')
        self.answers = [f"```tsx\n{crash}```"] * 3
        result = self.prepare(settings.Keys(claude="a"))
        self.assertEqual(result.board.scenes[1].type, "stat")
        self.assertIn("failed to draw", result.notes[0])

    @unittest.skipUnless(HAS_REMOTION, "remotion not installed (install.sh)")
    def test_a_cover_of_a_custom_scene_draws_its_component(self):
        # the writer may pick a custom scene for the cover (a real job did): the still needs its component
        (self.home / "scene02.tsx").write_text(RACE, encoding="utf-8")
        raw = {**BOARD, "scenes": [BOARD["scenes"][0], {**BOARD["scenes"][1], "component": "scene02.tsx"}]}
        board = storyboard.parse(raw, self.home)
        out = cover.make(FakeHttp(), settings.Keys(), self.settings, self.home, board, self.home / "c.png", 2,
                         "Twenty five times")
        self.assertEqual(out.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertFalse(any((custom.PROJECT / ".jobs").glob("*/index.tsx")))  # the entry is cleaned up


if __name__ == "__main__":
    unittest.main()
