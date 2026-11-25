"""Handoff: after opening an issue, fire the Claude task's API trigger when it is set up; never fail on it."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator" / "brief" / "tests"))

from fakes import FakeHttp, http_error  # noqa: E402

from orchestrator.brief.creds import Secrets  # noqa: E402
from orchestrator.handoff import Handoff  # noqa: E402

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
        self.assertEqual(put, {"tools/claim.sh", "tools/close.sh"})

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


if __name__ == "__main__":
    unittest.main()
