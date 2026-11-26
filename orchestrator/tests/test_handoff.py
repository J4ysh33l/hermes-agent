"""Handoff: after opening an issue, fire the Claude task's API trigger when it is set up; never fail on it."""

import os
import subprocess
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator" / "brief" / "tests"))

from fakes import FakeHttp, http_error

from orchestrator.brief.creds import Secrets
import json

from orchestrator.handoff import CLOSE, DENY, KEEP, SETTINGS, USAGE_MARK, Handoff

GH = "https://api.github.com/repos/me/hand/"
FIRE = "https://api.anthropic.com/v1/claude_code/routines/trig_x/fire"


class FireTest(unittest.TestCase):
    def handoff(self, env: str, fire=None) -> tuple[Handoff, FakeHttp]:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
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
        self.assertEqual(put, {"tools/claim.sh", "tools/close.sh", "tools/usage_hook.py", ".claude/settings.json", ".gitignore"})

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
        self.assertTrue({"Skill", "mcp__claude-code-remote"} <= set(deny))
        self.assertFalse({"Agent", "WebSearch"} & set(deny))  # the research subagent
        self.assertFalse({"WebSearch", "WebFetch"} & set(deny))  # Claude researches through the handoff
        self.assertEqual(len(deny), len(set(DENY)))
        self.assertIn("usage_hook.py", settings["hooks"]["Stop"][0]["hooks"][0]["command"])


if __name__ == "__main__":
    unittest.main()


class HandInTest(unittest.TestCase):
    """tools/close.sh on real git repos: jobs side by side hand in within seconds of each other."""

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout

    def test_close_pushes_after_pulling_when_main_moved_then_closes(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        bin_ = tmp / "bin"
        bin_.mkdir()
        (bin_ / "gh").write_text(f'#!/bin/sh\necho "$@" >> {tmp}/gh.log\n', encoding="utf-8")
        (bin_ / "gh").chmod(0o755)
        env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.git(tmp, "init", "-q", "--bare", "-b", "main", "origin.git")
        clones = []
        for name in ("a", "b"):
            self.git(tmp, "clone", "-q", "origin.git", name)
            clones.append(tmp / name)
        a, b = clones
        (a / "tools").mkdir()
        (a / "tools/close.sh").write_text(CLOSE.format(repo="me/hand"), encoding="utf-8")
        (a / "tools/old.pyc").write_text("1", encoding="utf-8")  # a tracked leftover the checks rewrite
        subprocess.run("git add -A && git commit -qm tools && git push -q origin HEAD:main", shell=True, cwd=a,
                       env=env, check=True)
        subprocess.run("git pull -q origin main", shell=True, cwd=b, env=env, check=True)
        for clone, job in ((a, "one"), (b, "two")):
            (clone / f"{job}.json").write_text("{}", encoding="utf-8")
            subprocess.run(f"git add -A && git commit -qm {job}", shell=True, cwd=clone, env=env, check=True)
        subprocess.run("git push -q origin HEAD:main", shell=True, cwd=a, env=env, check=True)  # a hands in first
        (b / "tools/old.pyc").write_text("2", encoding="utf-8")  # a dirty tree: a plain pull --rebase refuses
        (b / ".git/hermes-issue").write_text("9\n", encoding="utf-8")  # what tools/claim.sh claimed
        out = subprocess.run(["sh", "tools/close.sh"], cwd=b, env=env, capture_output=True, text=True)
        self.assertEqual(out.stdout.strip().splitlines()[-1:], ["CLOSED 9"], out.stderr)
        self.assertEqual(self.git(tmp / "origin.git", "ls-tree", "--name-only", "main").split(),
                         ["one.json", "tools", "two.json"])
        self.assertIn("repos/me/hand/issues/9 -f state=closed", (tmp / "gh.log").read_text(encoding="utf-8"))


class AnsweredTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        (tmp / ".env").write_text("GITHUB_HANDOFF_TOKEN=g\n", encoding="utf-8")
        self.http = FakeHttp()
        self.h = Handoff(self.http, Secrets(tmp / ".env", tmp / "tokens", environ={}), "me/hand")

    def test_open_with_the_run_still_going_is_not_answered(self):
        self.http.on("GET", GH + "issues/9", {"state": "open"})
        self.http.on("GET", GH + "issues/9/comments", [])
        self.assertFalse(self.h.answered(9))

    def test_a_run_that_ended_without_closing_is_answered_and_closed(self):
        self.http.on("GET", GH + "issues/9", {"state": "open"})
        self.http.on("GET", GH + "issues/9/comments", [{"body": USAGE_MARK + '\n{"issue": 9}'}])
        self.http.on("PATCH", GH + "issues/9", {})
        self.assertTrue(self.h.answered(9))
        self.assertEqual(self.http.calls[-1].json_body, {"state": "closed"})
