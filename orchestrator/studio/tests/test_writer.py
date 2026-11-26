"""/studio write: notes → script → direction → components, against a fake Gemini (and Claude's API).

The promises tested: each call does one job (the script prompt has no scene library, the direction prompt
carries the script locked); good answers become three storyboards (one per hook) the video step accepts;
a director who changes a word, invents evidence or puts a city on a map gets named problems and the fix is
used; a script with a greeting, a banned phrase or the wrong length goes back to the writer once; direction
gets ``studio.direction_retries`` tries, then the next model starts over, and when none gets it right
nothing is saved and every model is named; custom scenes are animated in one call, a component with a
banned API goes back once, one that never comes is drawn as its fallback; the profile reaches the prompts.

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

from orchestrator.brief.net import HttpError

from orchestrator.studio import chat, profile, settings, storyboard, video, writer

GEMINI = "https://generativelanguage.googleapis.com/"
CLAUDE = "https://api.anthropic.com/v1/messages"
NOTES = ("Bun is a JavaScript runtime written in Zig by Jarred Sumner. It installs packages up to 25 times "
         "faster than npm. Its test runner, bundler and package manager ship in one binary. "
         'Jarred said: "Bun is designed as a drop-in replacement for Node.js."')

SCRIPT = {
    "title": "Bun in 15 seconds",
    "hooks": [
        {"family": "definition-twist", "say": "Bun, a JavaScript runtime that *refuses* to wait."},
        {"family": "contrarian", "say": "Everyone thinks Node is fast enough."},
        {"family": "number", "say": "Twenty five times faster than npm."},
    ],
    "lines": [
        {"say": "Jarred Sumner wrote it in *Zig*, a low-level language."},
        {"say": "It installs packages up to *25 times* faster than npm."},
        {"say": "One binary ships three tools."},
        {"say": "A test runner. A bundler. A package manager.", "show": "the three tools land one by one"},
        {"say": "Jarred calls it a *drop-in* replacement."},
    ],
}
BOARD = {
    "hooks": [
        {"type": "title", "say": "Bun, a JavaScript runtime that *refuses* to wait.", "text": "Bun refuses to wait"},
        {"type": "title", "say": "Everyone thinks Node is fast enough.", "text": "Node is fast enough?"},
        {"type": "stat", "say": "Twenty five times faster than npm.", "value": 25, "suffix": "×", "label": "faster installs"},
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
    "cover": {"scene": 3, "words": "25x faster"},
    "music": "fast punchy electronic",
    "theme": {"bg": "#101820", "panel": "#1c2a36", "text": "#f2f5f7", "muted": "#9fb0bd", "accent": "#ff8a3d",
              "cool": "#5ed3c4"},
}
RACE = {"type": "custom", "say": "It installs packages up to *25 times* faster than npm.",
        "brief": "Two progress bars race; Bun's fills while npm's crawls.", "props": {"speedup": 25},
        "fallback": {"type": "stat", "value": 25, "suffix": "×", "label": "faster than npm"}}
TSX = """import React from "react";
import {AbsoluteFill, useCurrentFrame} from "remotion";
import {useTheme} from "studio/theme";
import type {CustomScene} from "studio/types";

export default function Scene({scene, frames}: {scene: CustomScene; frames: number}) {
  const frame = Math.min(useCurrentFrame(), frames - 1);
  const theme = useTheme();
  return <AbsoluteFill style={{color: theme.accent}}>{Math.round(frame / frames * 100)}%</AbsoluteFill>;
}
"""


def component(name: str, code: str) -> str:
    return f"```tsx\n// file: {name}\n{code}```"


FINDINGS = ("- Bun 1.2 added a built-in Postgres client in 2025 (bun.sh, January 2025).\n"
            "- Bun's mascot is a bun with a face (bun.sh, 2025).")


def research_answer() -> dict:
    """What Gemini with Google Search answers: the facts, and the pages it read."""
    return {"candidates": [{"content": {"parts": [{"text": FINDINGS}]},
                            "groundingMetadata": {"groundingChunks": [{"web": {"title": "bun.sh", "uri": "https://r/1"}}]}}]}


def answer(raw: object) -> dict:
    text = raw if isinstance(raw, str) else json.dumps(raw)
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class Writing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = mock.patch.dict("os.environ", {"HERMES_HOME": str(self.home)})  # usage lines land here
        self.env.start()
        self.look = profile.load("default", self.home)
        self.answers: list[object] = []
        self.http = FakeHttp().on("POST", GEMINI, lambda call: research_answer() if "tools" in call.json_body
                                  else answer(self.answers.pop(0)))
        self.job = self.home / "job1"

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def write(self, look: profile.Profile | None = None) -> writer.Draft:
        return writer.write(self.http, settings.Keys("g"), settings.Settings(), look or self.look, NOTES, 15, self.job)

    def prompts(self) -> list[str]:
        return [c.json_body["contents"][0]["parts"][-1]["text"] for c in self.http.calls]

    def test_each_call_does_one_job_and_good_answers_become_three_storyboards(self):
        self.answers = [SCRIPT, BOARD]
        draft = self.write()
        self.assertEqual((draft.rounds, draft.model), (2, "gemini-3.5-flash-lite"))
        script_ask, direction_ask = self.prompts()
        self.assertIn("1 of 3: the script", script_ask)
        self.assertNotIn("The scene library", script_ask)  # the writer only writes words
        self.assertIn("2 of 3: direction", direction_ask)
        self.assertIn("A test runner. A bundler. A package manager.", direction_ask)  # the script, locked
        saved = writer.save(draft, self.job / "bun.json", "default")
        self.assertEqual([p.name for p in saved], ["bun.json", "bun.hook2.json", "bun.hook3.json", "bun.txt"])
        boards = [storyboard.load(p) for p in saved[:3]]
        self.assertEqual([b.scenes[0].type for b in boards], ["title", "title", "stat"])
        self.assertTrue(all(len(b.scenes) == 5 and b.scenes[1].type == "logo" for b in boards))
        self.assertIn("Hook 2 (contrarian): Everyone thinks Node is fast enough.", saved[3].read_text())
        self.assertEqual(draft.cover, (3, "25x faster"))

    def test_a_director_who_changes_a_word_or_invents_evidence_is_named_and_the_fix_is_used(self):
        bad = copy.deepcopy(BOARD)
        bad["scenes"][0]["say"] = "Jarred Sumner built it in *Zig*, a low-level language."
        bad["scenes"][1]["value"] = 40  # not in the notes
        bad["scenes"][3]["text"] = "Node is dead."  # a quote nobody said
        self.answers = [SCRIPT, bad, BOARD]
        draft = self.write()
        self.assertEqual(draft.rounds, 3)
        fix = self.prompts()[2]
        self.assertIn("they differ at word 3: script 'wrote it in", fix)
        self.assertIn("the number 40 is not in the notes", fix)
        self.assertIn("scene 5 (quote): its text is not in the notes", fix)
        self.assertEqual(draft.scenes[1]["value"], 25)

    @unittest.skipUnless(video.WORLD.is_file(), "map data not installed (install.sh)")
    def test_a_city_on_a_map_is_refused(self):
        bad = copy.deepcopy(BOARD)
        bad["scenes"][0] = {"type": "map", "say": bad["scenes"][0]["say"], "route": ["San Francisco", "India"]}
        self.answers = [SCRIPT, bad, BOARD]
        self.write()
        self.assertIn("no country called 'San Francisco'", self.prompts()[2])

    def test_a_script_with_a_greeting_a_banned_phrase_or_the_wrong_length_goes_back_once(self):
        bad = copy.deepcopy(SCRIPT)
        bad["hooks"][1]["say"] = "Hey guys, in this video we look at Bun."
        bad["lines"] = bad["lines"][:1]  # far too short
        self.answers = [bad, SCRIPT, BOARD]
        self.write()
        fix = self.prompts()[1]
        self.assertIn("hook 2: starts with a greeting", fix)
        self.assertIn("says 'in this video', which this page never says", fix)
        self.assertIn("the narration (hook 1 + lines) is", fix)
        self.answers = [bad, bad, SCRIPT, BOARD]  # twice wrong: the next model starts over
        self.assertEqual(self.write().model, "gemini-3.1-flash-lite")

    def test_direction_gets_its_retries_then_every_model_is_named_and_nothing_is_saved(self):
        bad = copy.deepcopy(BOARD)
        bad["scenes"][3]["text"] = "Node is dead."
        self.answers = [SCRIPT, bad, bad, bad] * 2  # the script, then 1 + direction_retries (2) tries, per model
        with self.assertRaisesRegex(writer.WriterError, "gemini-3.5-flash-lite: direction.*gemini-3.1-flash-lite"):
            self.write()
        self.assertEqual(len(self.http.calls), 8)
        self.assertFalse((self.job / "direction.json").exists())

    def test_custom_scenes_are_animated_in_one_call_and_a_banned_api_goes_back_once(self):
        board = copy.deepcopy(BOARD)
        board["scenes"][1] = RACE
        board["scenes"][0]["wish"] = "a real video of Jarred typing"
        cheat = TSX.replace("Math.round(frame / frames * 100)", "Math.random()")
        self.answers = [SCRIPT, board, component("scene03.tsx", cheat), component("scene03.tsx", TSX)]
        draft = self.write()
        animate, fix = self.prompts()[2:]
        self.assertIn("3 of 3: custom scenes", animate)
        self.assertIn("### scene03.tsx (scene 3)", animate)
        self.assertIn("Two progress bars race", animate)
        self.assertIn("no randomness or clock", fix)
        self.assertEqual(draft.scenes[1]["component"], "scene03.tsx")
        self.assertEqual((self.job / "scene03.tsx").read_text(), TSX)
        self.assertEqual(draft.wishes, ("logo: a real video of Jarred typing",))
        self.assertNotIn("wish", draft.scenes[0])
        storyboard.load(writer.save(draft, self.job / "storyboard.json", "default")[0])  # the video step accepts it

    def test_a_component_that_never_comes_is_drawn_as_its_fallback(self):
        board = copy.deepcopy(BOARD)
        board["scenes"][1] = RACE
        self.answers = [SCRIPT, board, "I could not do it.", "Still no."]
        draft = self.write()
        self.assertEqual((draft.scenes[1]["type"], draft.scenes[1]["value"]), ("stat", 25))
        self.assertEqual(draft.scenes[1]["say"], RACE["say"])  # the words stay
        self.assertNotIn("brief", draft.scenes[1])
        storyboard.load(writer.save(draft, self.job / "storyboard.json", "default")[0])

    def test_a_busy_model_hands_the_call_to_the_next_one_and_the_work_so_far_is_kept(self):
        answers = [SCRIPT, BOARD]

        def reply(call):
            if "gemini-3.5-flash-lite" in call.url and len(answers) == 1:  # busy once the script is written
                raise HttpError(503, call.url, "This model is currently experiencing high demand.")
            return answer(answers.pop(0))
        self.http.on("POST", GEMINI, reply)
        draft = self.write()
        self.assertEqual(draft.model, "gemini-3.1-flash-lite")
        self.assertEqual([c.url.split("models/")[1].split(":")[0] for c in self.http.calls],
                         ["gemini-3.5-flash-lite", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"])

    def test_claude_on_request_gets_the_same_prompts_and_a_refusal_is_named(self):
        def reply(raw):
            return {"type": "message", "stop_reason": "end_turn", "usage": {"input_tokens": 9000, "output_tokens": 900},
                    "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": json.dumps(raw)}]}
        replies = [reply(SCRIPT), reply(BOARD),
                   {"type": "message", "stop_reason": "refusal", "content": [],
                    "stop_details": {"type": "refusal", "category": None, "explanation": "policy"}}]
        self.http.on("POST", CLAUDE, lambda _call: replies.pop(0))
        keys = settings.Keys("", "a")
        with self.assertRaisesRegex(writer.WriterError, "needs ANTHROPIC_API_KEY"):
            writer.write(self.http, settings.Keys("g"), settings.Settings(), self.look, NOTES, 15, self.job, True)
        draft = writer.write(self.http, keys, settings.Settings(), self.look, NOTES, 15, self.job, True)
        self.assertEqual((draft.model, draft.rounds), ("claude-opus-5-5", 2))
        call = self.http.calls[-2]
        self.assertEqual(call.headers["anthropic-version"], "2026-10-21")
        self.assertEqual(call.json_body["output_config"], {"effort": "medium"})
        self.assertNotIn("temperature", call.json_body)  # refused by this API version
        self.assertIn(NOTES, call.json_body["messages"][0]["content"][-1]["text"])
        self.assertEqual(self.http.count(GEMINI), 0)
        with self.assertRaisesRegex(writer.WriterError, "Claude declined: policy"):
            writer.write(self.http, keys, settings.Settings(), self.look, NOTES, 15, self.job, True)

    def test_studio_write_in_chat_answers_with_the_hooks_and_saves_the_storyboards(self):
        (self.home / ".env").write_text("GEMINI_API_KEY=g\nANTHROPIC_API_KEY=a\n", encoding="utf-8")
        claude = [SCRIPT, BOARD]
        self.http.on("POST", CLAUDE, lambda _call: {"stop_reason": "end_turn", "usage": {},
                                                   "content": [{"type": "text", "text": json.dumps(claude.pop(0))}]})
        (self.home / "studio/profiles").mkdir(parents=True)
        (self.home / "studio/profiles/shorts.yaml").write_text("writing:\n  seconds: 15\n", encoding="utf-8")
        (self.home / "brief").mkdir()
        (self.home / "brief/brief.yaml").write_text("studio:\n  profile: shorts\n", encoding="utf-8")
        reply = chat.handle("write " + NOTES, self.home, self.http)  # Claude writes by default
        self.assertIn("claude-opus-5-5", reply)
        self.assertIn("1. (definition-twist) Bun, a JavaScript runtime that *refuses* to wait.", reply)
        self.assertIn("[quote] Jarred calls it a *drop-in* replacement.", reply)
        saved = next((self.home / "studio/write").glob("*/storyboard.json"))
        self.assertEqual(len(storyboard.load(saved).scenes), 5)
        self.answers = [SCRIPT, BOARD]
        self.assertIn("gemini-3.5-flash-lite", chat.handle("write gemini " + NOTES, self.home, self.http))
        (self.home / ".env").write_text("GEMINI_API_KEY=g\n", encoding="utf-8")
        self.assertIn("needs ANTHROPIC_API_KEY", chat.handle("write " + NOTES, self.home, self.http))

    def test_the_profile_reaches_each_prompt(self):
        self.answers = [SCRIPT, BOARD]
        self.write(profile.load("bold", self.home))
        script_ask, direction_ask = self.prompts()
        self.assertIn("preferring: pain-point, contrarian, number", script_ask)
        self.assertIn('"game-changer"', script_ask)  # avoid list, inherited from default
        self.assertIn('"X in N seconds" explainer', script_ask)  # the format's beats from PLAYBOOK
        self.assertIn(NOTES, script_ask)
        types = direction_ask.split("Scene types on this page: ")[1].split(".\n")[0]
        self.assertNotIn("meme", types)  # no meme files; image scenes come as stock b-roll
        self.assertIn("image", types)
        self.assertIn("Not possible: photoreal people", direction_ask)
        self.assertIn("as many times as the video deserves", direction_ask)  # no cap on custom scenes


if __name__ == "__main__":
    unittest.main()
