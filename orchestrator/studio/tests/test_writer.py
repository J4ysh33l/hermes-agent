"""/studio write: notes → a storyboard with 3 hooks, against a fake Gemini.

The promises tested: a good answer becomes three storyboards (one per hook) that the video step accepts,
plus a readable script; evidence the notes do not contain (a number, a quote), a city on a map, a banned
phrase, or a wrong length goes back to the model as named problems, and the fixed answer is used; when no
model gets it right nothing is saved and every attempt is named; the profile's writing reaches the prompt.

Run: python3 orchestrator/studio/tests/test_writer.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator/brief/tests"))

from fakes import FakeHttp

from orchestrator.studio import profile, settings, storyboard, video, writer

GEMINI = "https://generativelanguage.googleapis.com/"
NOTES = ("Bun is a JavaScript runtime written in Zig by Jarred Sumner. It installs packages up to 25 times "
         "faster than npm. Its test runner, bundler and package manager ship in one binary. "
         'Jarred said: "Bun is designed as a drop-in replacement for Node.js."')

GOOD = {
    "title": "Bun in 15 seconds",
    "hooks": [
        {"family": "definition-twist", "scene": {"type": "title", "say": "Bun, a JavaScript runtime that *refuses* to wait.",
                                                 "text": "Bun refuses to wait"}},
        {"family": "contrarian", "scene": {"type": "title", "say": "Everyone thinks Node is fast enough.",
                                           "text": "Node is fast enough?"}},
        {"family": "number", "scene": {"type": "stat", "say": "Twenty five times faster than npm.",
                                       "value": 25, "suffix": "×", "label": "faster installs"}},
    ],
    "scenes": [
        {"type": "logo", "say": "Jarred Sumner wrote it in *Zig*, a low-level language.", "name": "Bun"},
        {"type": "stat", "say": "It installs packages up to *25 times* faster than npm.", "value": 25,
         "suffix": "×", "label": "faster than npm"},
        {"type": "bullets", "say": "One binary ships three tools. A test runner. A bundler. A package manager.",
         "title": "One binary", "items": ["Test runner", "Bundler", "Package manager"]},
        {"type": "quote", "say": "Jarred calls it a *drop-in* replacement.",
         "text": "Bun is designed as a drop-in replacement for Node.js.", "author": "Jarred Sumner"},
    ],
}


def answer(raw: dict) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(raw)}]}}]}


class Writing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = mock.patch.dict("os.environ", {"HERMES_HOME": str(self.home)})  # usage lines land here
        self.env.start()
        self.look = profile.load("default", self.home)
        self.answers: list[dict] = []
        self.http = FakeHttp().on("POST", GEMINI, lambda _call: answer(self.answers.pop(0)))

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def write(self) -> writer.Draft:
        return writer.write(self.http, "g", settings.Settings(), self.look, NOTES, 15, self.home)

    def prompts(self) -> list[str]:
        return [c.json_body["contents"][0]["parts"][-1]["text"] for c in self.http.calls]

    def test_a_good_answer_becomes_three_storyboards_the_video_step_accepts(self):
        self.answers = [GOOD]
        draft = self.write()
        self.assertEqual((draft.rounds, draft.model), (1, "gemini-3.5-flash-lite"))
        saved = writer.save(draft, self.home / "out" / "bun.json", "default")
        self.assertEqual([p.name for p in saved], ["bun.json", "bun.hook2.json", "bun.hook3.json", "bun.txt"])
        boards = [storyboard.load(p) for p in saved[:3]]
        self.assertEqual([b.scenes[0].type for b in boards], ["title", "title", "stat"])
        self.assertTrue(all(len(b.scenes) == 5 and b.scenes[1].type == "logo" for b in boards))
        self.assertIn("Hook 2 (contrarian): Everyone thinks Node is fast enough.", saved[3].read_text())

    def test_invented_evidence_goes_back_as_named_problems_and_the_fix_is_used(self):
        bad = copy.deepcopy(GOOD)
        bad["scenes"][1]["value"] = 40  # not in the notes
        bad["scenes"][3]["text"] = "Node is dead."  # a quote nobody said
        self.answers = [bad, GOOD]
        draft = self.write()
        self.assertEqual(draft.rounds, 2)
        fix = self.prompts()[1]
        self.assertIn("the number 40 is not in the notes", fix)
        self.assertIn("scene 5 (quote): its text is not in the notes", fix)
        self.assertEqual(draft.scenes[1]["value"], 25)

    @unittest.skipUnless(video.WORLD.is_file(), "map data not installed (install.sh)")
    def test_a_city_on_a_map_is_refused(self):
        bad = copy.deepcopy(GOOD)
        bad["scenes"].insert(1, {"type": "map", "say": "From *San Francisco* to the world.",
                                 "route": ["San Francisco", "India"]})
        self.answers = [bad, GOOD]
        self.write()
        self.assertIn("no country called 'San Francisco'", self.prompts()[1])

    def test_banned_phrases_greetings_and_wrong_length_are_refused(self):
        bad = copy.deepcopy(GOOD)
        bad["hooks"][1]["scene"]["say"] = "Hey guys, in this video we look at Bun."
        bad["scenes"] = bad["scenes"][:1]  # far too short
        self.answers = [bad, GOOD]
        self.write()
        fix = self.prompts()[1]
        self.assertIn("hook 2: starts with a greeting", fix)
        self.assertIn("says 'in this video', which this page never says", fix)
        self.assertIn("the narration is", fix)

    def test_when_no_model_gets_it_right_nothing_is_saved_and_every_try_is_named(self):
        bad = copy.deepcopy(GOOD)
        bad["hooks"][2]["family"] = "contrarian"
        self.answers = [bad] * 4
        with self.assertRaisesRegex(writer.WriterError, "gemini-3.5-flash-lite \\(try 2\\).*gemini-3.1-flash-lite"):
            self.write()
        self.assertEqual(len(self.http.calls), 4)
        self.assertFalse((self.home / "out").exists())

    def test_the_profiles_writing_reaches_the_prompt(self):
        bold = profile.load("bold", self.home)
        self.answers = [GOOD]
        writer.write(self.http, "g", settings.Settings(), bold, NOTES, 15, self.home)
        ask = self.prompts()[0]
        self.assertIn("in this order of preference: pain-point, contrarian, number", ask)
        self.assertIn('"game-changer"', ask)  # avoid list, inherited from default
        self.assertIn('"X in N seconds" explainer', ask)  # the format's beats from PLAYBOOK
        self.assertIn(NOTES, ask)
        self.assertNotIn("image,", ask.split("Allowed scene types:")[1].split("\n")[0])


if __name__ == "__main__":
    unittest.main()
