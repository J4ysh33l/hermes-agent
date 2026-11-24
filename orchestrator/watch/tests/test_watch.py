"""/watch against fake pages, a fake job board and a fake GitHub handoff repo.

The promises tested: a known job board is read from its feed; the first read is a baseline, later
reads report only what is new, with Gemini's note written from the new items' pages; a page that
fails or suddenly shows nothing never reports "removed" and is reported once after fail_after;
Claude's setup spec is checked, used, and the old source kept if it fails.

Run: python3 orchestrator/watch/tests/test_watch.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator/brief/tests"))

from fakes import FakeHttp, http_error

from orchestrator.watch import chat, sources, work

NOW = 1_795_000_000.0
GH = "https://api.github.com/repos/me/handoff"
PAGE = "https://acme.example/careers"
LEVER = "https://api.lever.co/v0/postings/acme?mode=json"


def page(*jobs: str) -> str:
    links = "".join(f'<li><a href="/careers/{j.lower().replace(" ", "-")}">{j}</a></li>' for j in jobs)
    return (f"<html><body><nav><a href='/'>Home</a><a href='#top'>Top</a></nav><ul>{links}</ul>"
            "<script>var x = '<a href=/nope>no</a>'</script></body></html>")


class Sources(unittest.TestCase):
    def test_job_boards_are_read_from_their_feed_and_other_pages_as_links_or_feeds(self):
        self.assertEqual(sources.detect("https://jobs.lever.co/acme")["url"], LEVER)
        self.assertEqual(sources.detect("https://boards.greenhouse.io/acme/jobs/1")["url"],
                         "https://boards-api.greenhouse.io/v1/boards/acme/jobs")
        smart = sources.detect("https://careers.smartrecruiters.com/Acme")
        self.assertEqual(smart["link_template"], "https://jobs.smartrecruiters.com/Acme/{id}")
        self.assertEqual(sources.detect("https://blog.example/feed")["kind"], "feed")
        self.assertEqual(sources.detect(PAGE)["kind"], "html")

    def test_links_feeds_and_json_become_items(self):
        http = FakeHttp().on("GET", PAGE, page("Backend Engineer", "Designer"))
        items = sources.read(http, {"kind": "html", "url": PAGE})
        self.assertEqual([i.title for i in items], ["Home", "Backend Engineer", "Designer"])
        self.assertEqual(items[1].link, "https://acme.example/careers/backend-engineer")
        only = sources.read(http, {"kind": "html", "url": PAGE, "match": "/careers/"})
        self.assertEqual(len(only), 2)
        rss = ('<?xml version="1.0"?><rss><channel><item><title>Notice 4</title><link>https://x.gov/n4.pdf</link>'
               '</item></channel></rss>')
        http.on("GET", "https://x.gov/notices", rss)  # a page address that answers with RSS
        self.assertEqual(sources.read(http, {"kind": "html", "url": "https://x.gov/notices"})[0].title, "Notice 4")
        http.on("GET", "https://api.sr/p", {"content": [{"id": "7", "name": "Analyst"}]})
        smart = sources.read(http, {"kind": "json", "url": "https://api.sr/p", "items": "content", "title": "name",
                                    "link_template": "https://jobs.sr/{id}"})
        self.assertEqual((smart[0].title, smart[0].link), ("Analyst", "https://jobs.sr/7"))

    def test_a_bad_spec_is_refused(self):
        self.assertTrue(sources.check_spec({"kind": "pdf", "url": "ftp://x"}))
        self.assertIn("match is not a valid pattern", " ".join(sources.check_spec(
            {"kind": "html", "url": "https://x", "match": "(("})))
        self.assertEqual(sources.check_spec({"kind": "feed", "url": "https://x/rss"}), [])


class Watching(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = mock.patch.dict("os.environ", {"HERMES_HOME": str(self.home)})
        self.env.start()
        (self.home / "brief").mkdir()
        (self.home / ".env").write_text("GITHUB_HANDOFF_TOKEN=gh\nGEMINI_API_KEY=g\n", encoding="utf-8")
        self.prompts: list[str] = []
        self.config(handoff_repo="me/handoff")
        self.jobs = ["Backend Engineer", "Designer"]
        self.github: dict[str, dict] = {}
        self.issues: list[dict] = []
        self.http = FakeHttp()
        self.http.on("GET", PAGE, lambda _c: page(*self.jobs))
        self.http.on("GET", LEVER, lambda _c: [{"text": j, "hostedUrl": f"https://jobs.lever.co/acme/{n}"}
                                               for n, j in enumerate(self.jobs)])
        self.http.on("PUT", GH + "/contents/", self._put)
        self.http.on("GET", GH + "/contents/", self._get)
        self.http.on("POST", GH + "/issues", self._issue)
        self.http.on("GET", "https://jobs.lever.co/acme/", "<html><nav>Menu</nav><main>Bengaluru · Senior · "
                     "backend platform team</main><script>x()</script></html>")
        self.http.on("POST", "https://generativelanguage.googleapis.com/", self._gemini)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _gemini(self, call):
        self.prompts.append(call.json_body["contents"][0]["parts"][-1]["text"])
        return {"candidates": [{"content": {"parts": [{"text": "Platform Engineer: Bengaluru, senior. Worth a look."}]}}]}

    def config(self, **watch):
        (self.home / "brief" / "brief.yaml").write_text(json.dumps({"watch": watch}), encoding="utf-8")

    def _put(self, call):
        self.github[call.url.split("/contents/", 1)[1]] = call.json_body
        return {}

    def _get(self, call):
        path = call.url.split("/contents/", 1)[1]
        if path not in self.github:
            return http_error(404)(call)
        return self.github[path]

    def _issue(self, call):
        self.issues.append(call.json_body)
        return {"number": len(self.issues)}

    def claude_writes(self, name: str, text: str) -> None:
        folder = [p for p in self.github if p.endswith("request.md")][-1].rsplit("/", 1)[0]
        self.github[f"{folder}/{name}"] = {"content": base64.b64encode(text.encode()).decode()}

    def watch(self, words: str, at: float = NOW) -> str:
        return chat.handle(words, self.home, self.http, at)

    def tick(self, at: float) -> str:
        return work.tick(work.context(self.home, self.http, at))

    def test_first_read_is_a_baseline_then_only_new_items_are_reported_with_a_gemini_note(self):
        self.config(handoff_repo="me/handoff", about="Founder; hiring backend engineers in India")
        added = self.watch("add https://jobs.lever.co/acme backend roles in India")
        self.assertIn("✅ Watch 1: jobs.lever.co/acme, read from its job board's feed, every 12 h.", added)
        self.assertIn("2 items now", added)
        self.assertEqual(self.prompts, [])  # the baseline needs no note
        self.assertEqual(self.tick(NOW + 3600), "")  # not due yet
        self.jobs.append("Platform Engineer")
        news = self.tick(NOW + 13 * 3600)
        self.assertIn("👀 **jobs.lever.co/acme** — 1 new\n• Platform Engineer\n  https://jobs.lever.co/acme/2", news)
        self.assertIn("🔎 Platform Engineer: Bengaluru, senior. Worth a look.", news)
        prompt = self.prompts[0]
        self.assertIn("What I care about on this page: backend roles in India", prompt)
        self.assertIn("About me: Founder; hiring backend engineers in India", prompt)
        self.assertIn("Page text: Bengaluru · Senior · backend platform team", prompt)  # the page, without nav/script
        self.assertNotIn("Menu", prompt)
        self.assertEqual(self.issues, [])  # Claude is not asked about changes
        self.assertEqual(self.tick(NOW + 26 * 3600), "")  # nothing new: no message, no model call
        self.assertEqual(len(self.prompts), 1)
        self.watch("notes 1 off")
        self.jobs.append("Data Engineer")
        self.assertNotIn("🔎", self.tick(NOW + 39 * 3600))

    def test_a_failing_or_empty_page_is_reported_once_and_never_looks_like_removals(self):
        self.config(fail_after=2)  # no handoff repo: Claude off
        self.watch("add https://acme.example/careers")
        self.http.on("GET", PAGE, "<html><body>Please enable JavaScript</body></html>")  # a block or redesign
        self.assertEqual(self.tick(NOW + 13 * 3600), "")
        second = self.tick(NOW + 26 * 3600)
        self.assertIn("⚠️ Watch 1 (acme.example/careers) failed 2 times in a row: found no items", second)
        self.assertEqual(self.tick(NOW + 39 * 3600), "")  # said once
        self.http.on("GET", PAGE, lambda _c: page(*self.jobs))
        self.assertEqual(self.tick(NOW + 52 * 3600), "")  # back, nothing new, nothing "removed"
        self.http.on("GET", PAGE, http_error(503))
        self.assertEqual(self.watch("check 1"), "Watch 1: nothing new.")

    def test_claude_sets_up_a_plain_page_and_a_bad_or_unreadable_spec_keeps_the_page(self):
        added = self.watch("add https://acme.example/careers engineering roles")
        self.assertIn("🔎 Claude is looking for the best way to watch it", added)
        self.assertIn("watch/1-setup-", self.issues[0]["title"] + json.dumps(list(self.github)))
        self.claude_writes("spec.json", '{"kind": "pdf"}')
        self.assertIn("Claude's setup was not used (kind must be one of", self.tick(NOW + 600))
        self.watch("ask 1")
        self.claude_writes("spec.json", json.dumps({"kind": "json", "url": "https://gone.example/api", "items": "",
                                                    "title": "t"}))
        self.http.on("GET", "https://gone.example/api", http_error(404))
        self.assertIn("could not be read (HTTP 404); kept the page", self.tick(NOW + 1200))
        self.watch("ask 1")
        self.claude_writes("spec.json", json.dumps({"kind": "json", "url": LEVER, "items": "", "title": "text",
                                                    "link": "hostedUrl", "note": "Lever feed, 2 roles"}))
        done = self.tick(NOW + 1800)
        self.assertIn("🔧 Watch 1 set up by Claude: Lever feed, 2 roles\n👀 Watch 1", done)
        self.assertIn("2 items now", done)

    def test_list_pause_every_match_and_remove(self):
        self.watch("add https://acme.example/careers")
        self.assertIn("every 6 h", self.watch("every 1 6"))
        self.assertIn("⏸ Watch 1 paused", self.watch("pause 1"))
        self.jobs.append("Intern")
        self.assertEqual(self.tick(NOW + 30 * 3600), "")  # paused: not read
        self.assertIn("⏸ paused", self.watch("list"))
        self.watch("resume 1")
        self.assertIn("keeps only items matching 'engineer'", self.watch("match 1 engineer"))
        self.assertIn("1 items now", self.tick(NOW + 31 * 3600))  # a fresh baseline, no alert
        self.assertIn("Removed watch 1", self.watch("remove 1"))
        self.assertIn("No watches yet", self.watch("list"))
        self.assertIn("/watch add", self.watch("help"))
        self.http.on("GET", "https://nowhere.example/x", http_error(404))
        self.assertIn("Couldn't read https://nowhere.example/x: HTTP 404. Nothing was added.",
                      self.watch("add https://nowhere.example/x"))


if __name__ == "__main__":
    unittest.main()
