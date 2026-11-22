"""Morning brief behaviour, end to end against fake services (no network, no real model).

Run: python3 orchestrator/brief/tests/test_brief.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import NOW, FakeHttp, chart, gemini_answer, http_error, query, rss

from orchestrator.brief import cli, filters, pipeline, rank, render, settings
from orchestrator.brief.creds import Secrets
from orchestrator.brief.items import Item
from orchestrator.brief.sources import markets, news
from orchestrator.brief.store import Store

GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/"
KEY = "test-gemini-key-not-real"
CONFIG = """
timezone: Asia/Kolkata
top_items: 3
topics:
  - {name: Mumbai, queries: [Mumbai], feeds: ["https://feeds.example.com/mumbai.xml"], per_run: 5}
markets:
  - {symbol: "^GSPC", label: "S&P 500", group: US}
  - {symbol: "^NSEI", label: "Nifty 50", group: India}
gold: {symbol: "GC=F", fx_symbol: "INR=X"}
mail:
  exclude_subject_words: [payslip]
ranking:
  max_input_tokens: 12000
  models: [{id: model-a}, {id: model-b, json_mode: false}]
"""
ENV = "GEMINI_API_KEY={key}\nSLACK_USER_TOKEN=slack-test\nGOOGLE_CLIENT_ID=g-id\nGOOGLE_CLIENT_SECRET=g-secret\n" \
      "MS_CLIENT_ID=ms-id\nMS_TENANT_ID=tenant\n"


def slack_reply(texts: list[str]) -> dict:
    matches = [{"ts": str(NOW - 600 - n), "text": t, "username": "asha", "permalink": f"https://slack/{n}",
                "channel": {"id": "C1", "name": "ops"}} for n, t in enumerate(texts)]
    return {"ok": True, "messages": {"matches": matches, "paging": {"pages": 1}}}


def gmail_message(mid: str, subject: str, newsletter: bool = False) -> dict:
    headers = [{"name": "From", "value": "Ravi <ravi@example.com>"}, {"name": "Subject", "value": subject}]
    if newsletter:
        headers.append({"name": "List-Unsubscribe", "value": "<mailto:u@example.com>"})
    return {"id": mid, "snippet": f"body of {subject}", "internalDate": str(int((NOW - 900) * 1000)),
            "payload": {"headers": headers}}


def services(gemini=None) -> FakeHttp:
    """Every outside service in a healthy state."""
    http = FakeHttp()
    http.on("GET", "https://slack.com/api/search.messages", slack_reply(["Can you approve the vendor quote today?"]))
    http.on("POST", "https://oauth2.googleapis.com/token", {"access_token": "g-access"})
    http.on("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages?",
            {"messages": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]})
    http.on("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/m1", gmail_message("m1", "Board meeting moved"))
    http.on("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/m2", gmail_message("m2", "Weekly digest", True))
    http.on("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/m3", gmail_message("m3", "Your payslip for Nov"))
    http.on("POST", "https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
            {"access_token": "ms-access", "refresh_token": "ms-refresh-2"})
    http.on("GET", "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages", {"value": [{
        "id": "AAMk1", "subject": "Contract signature needed", "bodyPreview": "Please sign by Friday",
        "receivedDateTime": "2099-01-01T00:00:00Z", "from": {"emailAddress": {"name": "Legal", "address": "l@x.com"}},
        "inferenceClassification": "focused"}]})
    http.on("GET", "https://news.google.com/rss/search", rss([("Metro line 3 opens", "https://n/1", NOW - 3600)],
                                                             source="Mid-day"))
    http.on("GET", "https://feeds.example.com/mumbai.xml", rss([("BMC budget passed", "https://n/2", NOW - 7200),
                                                                 ("Old story", "https://n/3", NOW - 9 * 86400)]))
    for sym, (price, prev) in {"%5EGSPC": (6000, 6100), "%5ENSEI": (25000, 24750), "GC%3DF": (3000, 2970),
                               "INR%3DX": (90, 90)}.items():
        http.on("GET", f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", chart(price, prev))
    http.on("POST", GEMINI, gemini or (lambda call: gemini_answer(["i1", "i2"])))
    return http


class BriefCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.state = self.home / "brief"
        self.state.mkdir()
        (self.state / "brief.yaml").write_text(CONFIG, encoding="utf-8")
        (self.home / ".env").write_text(ENV.format(key=KEY), encoding="utf-8")
        (self.state / "tokens").mkdir()
        (self.state / "tokens" / "google.json").write_text('{"refresh_token": "g-refresh"}', encoding="utf-8")
        (self.state / "tokens" / "microsoft.json").write_text('{"refresh_token": "ms-refresh-1"}', encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_brief(self, http: FakeHttp, now: float = NOW, dry_run: bool = False) -> pipeline.RunResult:
        secrets = Secrets(self.home / ".env", self.state / "tokens", environ={})
        return pipeline.run(http, settings.load(self.state), secrets, Store(self.state), now, dry_run=dry_run)

    def gemini_prompts(self, http: FakeHttp) -> list[str]:
        return [c.json_body["contents"][0]["parts"][0]["text"] for c in http.calls if c.url.startswith(GEMINI)]


class EndToEnd(BriefCase):
    def test_full_brief_has_markets_ranked_items_and_one_model_call(self):
        http = services()
        result = self.run_brief(http)
        self.assertEqual(len(self.gemini_prompts(http)), 1, "exactly one model call")
        self.assertEqual(result.model, "model-a")
        self.assertIn("S&P 500 6,000 ▼1.64%", result.text)
        self.assertIn("₹86,807/10g", result.text)  # 3000 $/oz * 90 ₹/$ / 31.1035 g * 10
        self.assertIn("Summary of i1", result.text)
        self.assertLess(len(result.text), 4096, "fits one Telegram message")

    def test_newsletters_finance_mail_and_old_news_never_reach_the_model(self):
        http = services()
        self.run_brief(http)
        prompt = self.gemini_prompts(http)[0]
        self.assertIn("Board meeting moved", prompt)
        self.assertIn("Contract signature needed", prompt)
        self.assertNotIn("Weekly digest", prompt)
        self.assertNotIn("payslip", prompt.lower())
        self.assertNotIn("Old story", prompt)
        self.assertNotIn(KEY, prompt)

    def test_second_run_with_nothing_new_makes_no_model_call(self):
        self.run_brief(services())
        http = services()
        result = self.run_brief(http, now=NOW + 60)
        self.assertEqual(self.gemini_prompts(http), [])
        self.assertIn("Nothing new since the last brief.", result.text)
        self.assertIn("S&P 500", result.text, "markets still sent on a quiet day")

    def test_dry_run_saves_nothing(self):
        self.run_brief(services(), dry_run=True)
        http = services()
        self.run_brief(http)
        self.assertEqual(len(self.gemini_prompts(http)), 1)

    def test_expired_gmail_login_is_named_and_the_rest_still_arrives(self):
        http = services()
        http.on("POST", "https://oauth2.googleapis.com/token", http_error(400, '{"error": "invalid_grant"}'))
        result = self.run_brief(http)
        self.assertIn("🔑 Gmail needs a new login", result.text)
        self.assertIn("auth google", result.text)
        self.assertNotIn("Board meeting moved", self.gemini_prompts(http)[0])
        self.assertIn("Contract signature needed", self.gemini_prompts(http)[0])

    def test_failed_source_is_retried_from_its_old_watermark(self):
        broken = services()
        broken.on("GET", "https://slack.com/api/search.messages", http_error(503, "down"))
        first = self.run_brief(broken)
        self.assertIn("Slack not included", first.text)
        later = services()
        self.run_brief(later, now=NOW + 3600)
        self.assertIn("vendor quote", self.gemini_prompts(later)[0])

    def test_outlook_refresh_token_rotation_is_saved(self):
        self.run_brief(services())
        stored = json.loads((self.state / "tokens" / "microsoft.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["refresh_token"], "ms-refresh-2")
        self.assertNotIn("access_token", stored)

    def test_first_model_rate_limited_falls_back_to_second(self):
        def gemini(call):
            if "model-a" in call.url:
                raise http_error(429, "quota")(call)
            self.assertNotIn("responseMimeType", call.json_body["generationConfig"])
            return gemini_answer(["i2"])
        result = self.run_brief(services(gemini))
        self.assertEqual(result.model, "model-b")

    def test_every_model_failing_still_sends_an_unranked_brief(self):
        result = self.run_brief(services(http_error(500, "boom")))
        self.assertEqual(result.model, "")
        self.assertIn("not ranked", result.text)
        self.assertIn("Contract signature needed", result.text)

    def test_markets_failure_only_removes_markets(self):
        http = services()
        http.routes = {k: v for k, v in http.routes.items() if "yahoo" not in k}
        http.on("GET", "https://query1.finance.yahoo.com/", http_error(429, "slow down"))
        result = self.run_brief(http)
        self.assertIn("Markets missing", result.text)
        self.assertIn("Summary of i1", result.text)


class ChatCommands(BriefCase):
    def chat(self, words: str, http: FakeHttp | None = None) -> str:
        return cli.handle_chat_command(words, self.state, http or services())

    def test_watch_adds_a_stock_to_the_markets_block(self):
        http = services()
        http.on("GET", "https://query1.finance.yahoo.com/v8/finance/chart/NVDA", chart(180, 170))
        self.assertIn("Added NVDA", self.chat("watch nvda", http))
        self.assertIn("Watchlist (", self.run_brief(http).text)

    def test_watch_rejects_unknown_or_malformed_symbols(self):
        http = services()
        http.on("GET", "https://query1.finance.yahoo.com/v8/finance/chart/ZZZZ", http_error(404, "no data"))
        self.assertIn("no such symbol", self.chat("watch zzzz", http))
        self.assertIn("one Yahoo Finance symbol", self.chat("watch rm -rf /"))
        self.assertEqual(settings.load(self.state).prefs.watchlist, ())

    def test_follow_adds_a_news_search_and_mute_removes_items(self):
        self.chat("follow electric vehicles")
        self.chat("mute metro")
        http = services()
        self.run_brief(http)
        searches = [q for c in http.calls if c.url.startswith("https://news.google.com") for q in query(c)["q"]]
        self.assertIn("electric vehicles when:1d", searches)
        self.assertNotIn("Metro line 3", self.gemini_prompts(http)[0])

    def test_more_lists_the_saved_edition_without_a_model_call(self):
        self.run_brief(services())
        http = services()
        text = self.chat("more", http)
        self.assertIn("All items", text)
        self.assertIn("BMC budget passed", text)
        self.assertEqual(http.calls, [])

    def test_unknown_subcommand_shows_help(self):
        self.assertIn("/brief watch", self.chat("bogus"))


class Units(unittest.TestCase):
    def test_indian_grouping(self):
        self.assertEqual(render.indian_grouping(10473812.4), "1,04,73,812")
        self.assertEqual(render.indian_grouping(999), "999")

    def test_answer_with_unknown_or_repeated_ids_is_cleaned(self):
        a = Item(uid="a", source="news", title="A", ts=1)
        picked, _lines = rank.parse_answer('{"top": [{"id": "i9"}, {"id": "i1", "line": "x"}, {"id": "i1"}]}',
                                          {"i1": a}, 5)
        self.assertEqual(picked, [a])
        with self.assertRaises(ValueError):
            rank.parse_answer('{"top": [{"id": "nope"}]}', {"i1": a}, 5)

    def test_budget_is_shared_across_sources(self):
        items = [Item(uid=f"n{i}", source="news", title="x" * 400, ts=1) for i in range(50)]
        items += [Item(uid="s1", source="slack", title="hello", ts=1)]
        fits, over = filters.fit_budget(items, 1000)
        self.assertIn("s1", {i.uid for i in fits}, "a noisy source cannot crowd out the others")
        self.assertTrue(over)

    def test_atom_feed_and_google_publisher_suffix(self):
        atom = ("<feed xmlns='http://www.w3.org/2005/Atom'><title>Blog</title><entry><title>Post</title>"
                "<link href='https://b/1'/><updated>2026-11-21T10:00:00Z</updated></entry></feed>")
        self.assertEqual([i.url for i in news.parse_feed(atom)], ["https://b/1"])
        google = news.parse_feed(rss([("Headline", "https://g/1", NOW)], source="Reuters"))
        self.assertEqual((google[0].title, google[0].where), ("Headline", "Reuters"))

    def test_us_close_day_uses_the_exchange_time_zone(self):
        # Friday 16:00 New York = Saturday 02:30 in Mumbai; the brief must say Fri.
        friday_close = 1795208400.0  # 2026-11-20 21:00 UTC
        http = FakeHttp().on("GET", "https://query1", chart(1, 1, tz_offset=-18000, as_of=friday_close))
        self.assertEqual(markets.quote(http, settings.Symbol("^GSPC", "S&P")).day, "Fri")

    def test_plugin_registers_brief_command(self):
        spec = importlib.util.spec_from_file_location("brief_plugin", ROOT / "orchestrator/brief/plugin/__init__.py")
        plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plugin)

        registered = {}

        class Ctx:
            def register_command(self, name, handler, **kw):
                registered[name] = handler

        plugin.register(Ctx())
        self.assertIn("brief", registered)


if __name__ == "__main__":
    unittest.main()
