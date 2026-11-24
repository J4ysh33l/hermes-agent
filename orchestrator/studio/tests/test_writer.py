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

from orchestrator.studio import chat, profile, settings, storyboard, video, writer

GEMINI = "https://generativelanguage.googleapis.com/"
CLAUDE = "https://api.anthropic.com/v1/messages"
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
        return writer.write(self.http, settings.Keys("g"), settings.Settings(), self.look, NOTES, 15, self.home)

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

    def test_wishes_are_taken_out_logged_and_counted_and_directions_are_not_words(self):
        wishing = copy.deepcopy(GOOD)
        wishing["scenes"][0]["wish"] = "a 3D bun bouncing out of an oven"
        wishing["scenes"][2]["say"] = "One binary ships three tools. [beat] A test runner. A bundler. A package manager."
        self.answers = [wishing, copy.deepcopy(wishing)]
        draft = self.write()
        self.assertEqual(draft.wishes, ("logo: a 3D bun bouncing out of an oven",))
        self.assertNotIn("wish", draft.scenes[0])
        self.assertEqual(draft.words(), self.write().words())
        writer.remember(draft, self.home, NOTES)
        writer.remember(draft, self.home, NOTES)
        self.assertEqual(writer.wishlist(self.home), [(2, "a 3d bun bouncing out of an oven")])
        storyboard.load(writer.save(draft, self.home / "w.json", "default")[0])  # the video step accepts it

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

    def test_claude_on_request_gets_the_same_prompt_and_a_refusal_is_named(self):
        replies = [{"type": "message", "stop_reason": "end_turn", "usage": {"input_tokens": 9000, "output_tokens": 900},
                    "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": json.dumps(GOOD)}]},
                   {"type": "message", "stop_reason": "refusal", "content": [],
                    "stop_details": {"type": "refusal", "category": None, "explanation": "policy"}}]
        self.http.on("POST", CLAUDE, lambda _call: replies.pop(0))
        keys = settings.Keys("", "a")
        with self.assertRaisesRegex(writer.WriterError, "needs ANTHROPIC_API_KEY"):
            writer.write(self.http, settings.Keys("g"), settings.Settings(), self.look, NOTES, 15, self.home, True)
        draft = writer.write(self.http, keys, settings.Settings(), self.look, NOTES, 15, self.home, True)
        self.assertEqual((draft.model, draft.rounds), ("claude-opus-5-5", 1))
        call = self.http.calls[-1]
        self.assertEqual(call.headers["anthropic-version"], "2026-10-21")
        self.assertEqual(call.json_body["output_config"], {"effort": "medium"})
        self.assertNotIn("temperature", call.json_body)  # refused by this API version
        self.assertIn(NOTES, call.json_body["messages"][0]["content"][-1]["text"])
        self.assertEqual(self.http.count(GEMINI), 0)
        with self.assertRaisesRegex(writer.WriterError, "Claude declined: policy"):
            writer.write(self.http, keys, settings.Settings(), self.look, NOTES, 15, self.home, True)

    def test_studio_write_in_chat_answers_with_the_hooks_and_saves_the_storyboards(self):
        (self.home / ".env").write_text("GEMINI_API_KEY=g\nANTHROPIC_API_KEY=a\n", encoding="utf-8")
        self.http.on("POST", CLAUDE, lambda _call: {"stop_reason": "end_turn", "usage": {},
                                                   "content": [{"type": "text", "text": json.dumps(GOOD)}]})
        (self.home / "studio/profiles").mkdir(parents=True)
        (self.home / "studio/profiles/shorts.yaml").write_text("writing:\n  seconds: 15\n", encoding="utf-8")
        (self.home / "brief").mkdir()
        (self.home / "brief/brief.yaml").write_text("studio:\n  profile: shorts\n", encoding="utf-8")
        reply = chat.handle("write " + NOTES, self.home, self.http)  # Claude writes by default
        self.assertIn("claude-opus-5-5", reply)
        self.answers = [GOOD]
        self.assertIn("gemini-3.5-flash-lite", chat.handle("write gemini " + NOTES, self.home, self.http))
        self.assertIn("1. (definition-twist) Bun, a JavaScript runtime that *refuses* to wait.", reply)
        self.assertIn("[quote] Jarred calls it a *drop-in* replacement.", reply)
        saved = next((self.home / "studio/write").glob("*/storyboard.json"))
        self.assertEqual(len(storyboard.load(saved).scenes), 5)
        (self.home / ".env").write_text("GEMINI_API_KEY=g\n", encoding="utf-8")
        self.assertIn("needs ANTHROPIC_API_KEY", chat.handle("write " + NOTES, self.home, self.http))

    def test_the_profiles_writing_reaches_the_prompt(self):
        bold = profile.load("bold", self.home)
        self.answers = [GOOD]
        writer.write(self.http, settings.Keys("g"), settings.Settings(), bold, NOTES, 15, self.home)
        ask = self.prompts()[0]
        self.assertIn("in this order of preference: pain-point, contrarian, number", ask)
        self.assertIn('"game-changer"', ask)  # avoid list, inherited from default
        self.assertIn('"X in N seconds" explainer', ask)  # the format's beats from PLAYBOOK
        self.assertIn(NOTES, ask)
        library = ask.split("The library types (")[1].split(")")[0]
        self.assertNotIn("meme", library)  # no meme files; image scenes come as stock b-roll
        self.assertIn("image", library)
        self.assertNotIn("custom", library)  # custom is not a library type: it is anything else
        self.assertIn("Nothing here limits your ideas except the real", ask)
        self.assertIn("Not possible: photoreal people", ask)



class HookTest(unittest.TestCase):
    """PLAYBOOK § 3: a hook is a 3-second opening, not an intro."""

    def test_an_eight_second_intro_is_not_a_hook(self):
        # a real job's hook 1: 3 sentences, 26 words, 8.4 s on screen
        said = writer._hook("Shinkansen, a bullet train so punctual its delays are counted in *seconds*. Your bus counts "
                            "them in moods. [beat] It's not luck. It's a *system*.")
        self.assertTrue(any("first sentence has 12 words" in p for p in said))
        self.assertTrue(any("not an intro" in p for p in said))

    def test_a_short_claim_with_a_turn_is_one(self):
        self.assertEqual(writer._hook("Japan's trains apologise for being early. Here's why."), [])
        self.assertIn("no pause", writer._hook("Japan's trains [beat] apologise.")[0])

if __name__ == "__main__":
    unittest.main()
