"""Handoff: after opening an issue, fire the Claude task's API trigger when it is set up; never fail on it."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator" / "brief" / "tests"))

from fakes import FakeHttp, http_error

from orchestrator.brief.creds import Secrets
import json

from orchestrator.handoff import DENY, KEEP, SETTINGS, Handoff

GH = "https://api.github.com/repos/me/hand/"
FIRE = "https://api.anthropic.com/v1/claude_code/routines/trig_x/fire"


class FireTest(unittest.TestCase):
    def handoff(self, env: str, fire=None) -> tuple[Handoff, FakeHttp]:
        tmp = Path(tempfile.mkdtemp())
        (tmp / ".env").write_text(env, encoding="utf-8")
        http = FakeHttp()
        http.on("GET", GH + "contents/", http_error(404))
        http.on("PUT", GH + "contents/", {})
        http.on("POST", GH + "labels", {})
        http.on("POST", GH + "issues", {"number": 7})
        if fire is not None:
            http.on("POST", FIRE, fire)
        return Handoff(http, Secrets(tmp / ".env", tmp / "tokens", environ={}), "me/hand"), http

    def test_fires_after_opening_the_issue(self):
        h, http = self.handoff(f"GITHUB_HANDOFF_TOKEN=g\nCLAUDE_ROUTINE_URL={FIRE}\nCLAUDE_ROUTINE_TOKEN=sk\n",
                               {"type": "routine_fire"})
        self.assertEqual(h.send({}, "studio 1: script", "body"), 7)
        call = http.calls[-1]
        self.assertEqual(call.url, FIRE)
        self.assertEqual(call.headers["Authorization"], "Bearer sk")
        self.assertEqual(call.headers["anthropic-beta"], "experimental-cc-routine-2026-04-01")
        self.assertIn("#7", call.json_body["text"])
        self.assertEqual(h.fire_error, "")
        put = {c.url.rsplit("contents/", 1)[1] for c in http.calls if c.method == "PUT"}
        self.assertEqual(put, {"tools/claim.sh", "tools/close.sh", "tools/usage_hook.py", ".claude/settings.json"})

    def test_sonnet_steps_go_to_the_sonnet_task_with_their_own_label(self):
        sonnet = FIRE.replace("trig_x", "trig_s")
        h, http = self.handoff(f"GITHUB_HANDOFF_TOKEN=g\nCLAUDE_ROUTINE_URL={FIRE}\nCLAUDE_ROUTINE_TOKEN=sk\n"
                               f"CLAUDE_ROUTINE_SONNET_URL={sonnet}\nCLAUDE_ROUTINE_SONNET_TOKEN=ss\n", {})
        http.on("POST", sonnet, {"claude_code_session_id": "cse_s"})
        h.lane = "sonnet"
        self.assertEqual(h.send({}, "studio 1: direction", "body"), 7)
        issue = next(c for c in http.calls if c.url == GH + "issues")
        self.assertEqual(issue.json_body["labels"], ["hermes-sonnet"])
        self.assertEqual((http.calls[-1].url, http.calls[-1].headers["Authorization"]), (sonnet, "Bearer ss"))
        self.assertEqual((h.lane_used, h.session), ("sonnet", "cse_s"))

    def test_sonnet_without_its_own_task_goes_to_the_main_one(self):
        h, http = self.handoff(f"GITHUB_HANDOFF_TOKEN=g\nCLAUDE_ROUTINE_URL={FIRE}\nCLAUDE_ROUTINE_TOKEN=sk\n", {})
        h.lane = "sonnet"
        h.send({}, "t", "b")
        self.assertEqual(next(c for c in http.calls if c.url == GH + "issues").json_body["labels"], ["hermes"])
        self.assertEqual((http.calls[-1].url, h.lane_used), (FIRE, ""))

    def test_not_set_up_means_no_fire(self):
        h, http = self.handoff("GITHUB_HANDOFF_TOKEN=g\n")
        self.assertEqual(h.send({}, "t", "b"), 7)
        self.assertFalse(any(c.url == FIRE for c in http.calls))
        self.assertFalse(h.fire())

    def test_refused_fire_keeps_the_issue(self):
        h, _ = self.handoff(f"GITHUB_HANDOFF_TOKEN=g\nCLAUDE_ROUTINE_URL={FIRE}\nCLAUDE_ROUTINE_TOKEN=bad\n",
                            http_error(401))
        self.assertEqual(h.send({}, "t", "b"), 7)
        self.assertEqual(h.fire_error, "Claude task fire: HTTP 401")


class SettingsTest(unittest.TestCase):
    def test_the_repo_settings_keep_the_working_tools_and_remove_the_rest(self):
        settings = json.loads(SETTINGS)
        deny = settings["permissions"]["deny"]
        self.assertFalse(set(KEEP) & set(deny))
        self.assertFalse([d for d in deny if d.startswith("mcp__github__") and d.split("__")[2] in (
            "issue_read", "issue_write", "list_issues", "add_issue_comment", "get_file_contents", "push_files")])
        self.assertTrue({"Agent", "Skill", "mcp__claude-code-remote"} <= set(deny))
        self.assertFalse({"WebSearch", "WebFetch"} & set(deny))  # Claude researches through the handoff
        self.assertEqual(len(deny), len(set(DENY)))
        self.assertIn("usage_hook.py", settings["hooks"]["Stop"][0]["hooks"][0]["command"])


if __name__ == "__main__":
    unittest.main()
