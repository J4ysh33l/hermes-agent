"""The rules each writing call must pass, and the checker Claude runs in the handoff repo.

The promises tested: a hook is a 3-second opening, not an intro; numbers count as the words the voice
reads; the checker Hermes commits to the handoff repo (``tools/check.py`` + ``tools/studio/``) runs on
its own there (copied out of Hermes, isolated, no Hermes package on the path) and gives the same verdicts
as Hermes for each call: script, direction (the script's words locked) and components.

Run: python3 orchestrator/studio/tests/test_rules.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from test_writer import BOARD, NOTES, RACE, SCRIPT, TSX

from orchestrator.studio import handoff, rules
from orchestrator.studio.text import said_words

PARAMS = rules.Params(words=49, avoid=("game-changer",), scenes=("title", "stat", "logo", "bullets", "quote", "custom"),
                      stock=False, notes=NOTES)


class HookTest(unittest.TestCase):
    """PLAYBOOK § 3: a hook is a 3-second opening, not an intro."""

    def test_an_eight_second_intro_is_not_a_hook(self):
        # a real job's hook 1: 3 sentences, 26 words, 8.4 s on screen
        said = rules.hook_problems("Shinkansen, a bullet train so punctual its delays are counted in *seconds*. Your "
                                   "bus counts them in moods. [beat] It's not luck. It's a *system*.")
        self.assertTrue(any("first sentence has 12 words" in p for p in said))
        self.assertTrue(any("not an intro" in p for p in said))

    def test_a_short_claim_with_a_turn_is_one(self):
        self.assertEqual(rules.hook_problems("Japan's trains apologise for being early. Here's why."), [])
        self.assertIn("no pause", rules.hook_problems("Japan's trains [beat] apologise.")[0])


class SpokenLengthTest(unittest.TestCase):
    """A number is budgeted as the words the voice reads: a real script full of years ran 53 s, not 45."""

    def test_numbers_count_as_they_are_read(self):
        self.assertEqual(said_words("Work began in 1887. [beat] It was built for the 1889 World's Fair."), 16)
        self.assertEqual(said_words("It's about 18,000 iron parts, held by 2.5 million *rivets*."), 13)
        self.assertEqual(said_words("Blue whales: the *biggest* animals ever."), 6)


class RepoChecker(unittest.TestCase):
    """What Claude runs before handing in, in a copy of the handoff repo."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        for path, text in handoff.tools().items():
            self.repo.joinpath(path).parent.mkdir(parents=True, exist_ok=True)
            self.repo.joinpath(path).write_text(text, encoding="utf-8")
        self.job = self.repo / "studio/j1"
        self.job.mkdir(parents=True)
        self.job.joinpath("rules.json").write_text(PARAMS.dumps(), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, value: object) -> None:
        text = value if isinstance(value, str) else json.dumps(value)
        self.job.joinpath(name).write_text(text, encoding="utf-8")

    def check(self, stage: str) -> tuple[int, str]:
        done = subprocess.run([sys.executable, "-I", "tools/check.py", stage, "studio/j1"], cwd=self.repo,
                              capture_output=True, text=True, timeout=60, check=False)
        return done.returncode, done.stdout + done.stderr

    def test_the_script_check_matches_hermes(self):
        self.write("script.json", SCRIPT)
        self.assertEqual(self.check("script"), (0, "OK: ready to hand in\n"))
        bad = copy.deepcopy(SCRIPT)
        bad["hooks"][0]["say"] = "Hey, Bun is a JavaScript runtime that refuses to wait for anything."
        self.write("script.json", bad)
        code, said = self.check("script")
        self.assertEqual(code, 1)
        self.assertEqual(said.splitlines(), [f"- {p}" for p in rules.check_script(bad, PARAMS)])
        self.assertIn("hook 1: starts with a greeting", said)

    def test_direction_is_checked_against_the_locked_script(self):
        self.write("script.json", SCRIPT)
        self.write("storyboard.json", BOARD)
        self.assertEqual(self.check("direction")[0], 0)
        edited = copy.deepcopy(BOARD)
        edited["scenes"][3]["say"] = "Jarred calls it a *perfect* replacement."
        self.write("storyboard.json", edited)
        code, said = self.check("direction")
        self.assertEqual(code, 1)
        self.assertIn("word for word", said)

    def test_components_are_checked_by_name(self):
        board = copy.deepcopy(BOARD)
        board["scenes"][1] = RACE
        self.write("script.json", SCRIPT)
        self.write("storyboard.json", board)
        self.assertIn("scene03.tsx: missing", self.check("animation")[1])
        self.write("scene03.tsx", TSX.replace("Math.min", "Date.now() + Math.min"))
        self.assertIn("no randomness or clock", self.check("animation")[1])
        self.write("scene03.tsx", TSX)
        self.assertEqual(self.check("animation"), (0, "OK: ready to hand in\n"))


if __name__ == "__main__":
    unittest.main()
