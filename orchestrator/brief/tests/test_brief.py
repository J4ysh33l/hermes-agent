"""Morning brief behaviour, end to end against fake services (no network, no real model).

Run: python3 orchestrator/brief/tests/test_brief.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import NOW, FakeHttp, chart, gemini_answer, http_error, query, rss

from orchestrator.brief import auth, cli, filters, pipeline, rank, render, settings
from orchestrator.brief.creds import Secrets
from orchestrator.brief.items import Item
from orchestrator.brief.sources import markets, news, outlook
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
  private_subject_words: [payslip]
  noise_subject_patterns: ['verification code']
ranking:
  max_input_tokens: 12000
  models: [{id: model-a}, {id: model-b, json_mode: false}]
"""
ENV = "GEMINI_API_KEY={key}\nSLACK_USER_TOKEN=slack-test\nGOOGLE_CLIENT_ID=g-id\nGOOGLE_CLIENT_SECRET=g-secret\n" \
      "MS_CLIENT_ID=ms-id\nMS_TENANT_ID=tenant\n"


IBJA_PAGE = (
    '<input type="hidden" id="HdnGold" value="{&quot;labels&quot;:[&quot;19/11/2026&quot;,&quot;20/11/2026&quot;],'
    '&quot;purity999&quot;:[125000,123893],&quot;purity916&quot;:[1,1]}" />'
    '<span id="GoldRatesCompare999">12389</span>'
)


def slack_reply(texts: list[str], channel: str = "C1") -> dict:
    matches = [{"ts": f"{NOW - 600 - n:.6f}", "text": t, "user": "U1", "permalink": f"https://slack/{n}",
                "channel": {"id": channel, "name": "ops"}} for n, t in enumerate(texts)]
    return {"ok": True, "messages": {"matches": matches, "paging": {"pages": 1}}}


SLACK_CONVERSATIONS = {"ok": True, "channels": [
    {"id": "C1", "name": "ops", "is_channel": True},
    {"id": "D1", "is_im": True, "user": "U2"},
    {"id": "G1", "name": "mpdm-asha--ravi--me-1", "is_mpim": True}]}
SLACK_PEOPLE = {"U1": "Asha", "U2": "Ravi"}


def slack_user(call) -> dict:
    uid = query(call)["user"][0]
    return {"ok": True, "user": {"id": uid, "profile": {"display_name": SLACK_PEOPLE.get(uid, "")}}}


def gmail_batch(messages: dict[str, dict]):
    """Answers the Gmail batch endpoint like Google: one multipart part per requested id."""
    def answer(call) -> str:
        ids = re.findall(r"GET /gmail/v1/users/me/messages/([^?]+)\?", call.data.decode())
        parts = []
        for mid in ids:
            body = messages.get(mid)
            status = "200 OK" if body else "429 Too Many Requests"
            payload = body or {"error": {"message": "Too many concurrent requests for user."}}
            parts.append(f"--batch_r\r\nContent-Type: application/http\r\nContent-ID: <response-{mid}>\r\n\r\n"
                         f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n\r\n{json.dumps(payload)}\r\n")
        return "".join(parts) + "--batch_r--\r\n"
    return answer


def gmail_message(mid: str, subject: str, newsletter: bool = False) -> dict:
    headers = [{"name": "From", "value": "Ravi <ravi@example.com>"}, {"name": "Subject", "value": subject}]
    if newsletter:
        headers.append({"name": "List-Unsubscribe", "value": "<mailto:u@example.com>"})
    return {"id": mid, "snippet": f"body of {subject}", "internalDate": str(int((NOW - 900) * 1000)),
            "payload": {"headers": headers}}


def services(gemini=None) -> FakeHttp:
    """Every outside service in a healthy state."""
    http = FakeHttp()
    http.on("GET", "https://slack.com/api/users.conversations", SLACK_CONVERSATIONS)
    http.on("GET", "https://slack.com/api/users.list", {"ok": True, "members": [
        {"id": "U1", "profile": {"display_name": "Asha"}}]})
    http.on("GET", "https://slack.com/api/users.info", slack_user)  # only for ids users.list missed (U2)
    http.on("GET", "https://slack.com/api/search.messages", slack_reply(["Can you approve the vendor quote today?"]))
    http.on("POST", "https://oauth2.googleapis.com/token", {"access_token": "g-access"})
    mails = {"m1": gmail_message("m1", "Board meeting moved"), "m2": gmail_message("m2", "Weekly digest", True),
             "m3": gmail_message("m3", "Your payslip for Nov"),
             "m4": gmail_message("m4", "618363 is your KIRI verification code")}
    http.on("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages?", {"messages": [{"id": m} for m in mails]})
    http.on("POST", "https://www.googleapis.com/batch/gmail/v1", gmail_batch(mails))
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
    http.on("GET", "https://ibjarates.com/", IBJA_PAGE)
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
        self.env = mock.patch.dict(os.environ, {"HERMES_HOME": str(self.home)})  # usage log stays in the temp home
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def usage_lines(self) -> list[dict]:
        path = self.home / "usage" / "calls.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []

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
        [line] = self.usage_lines()
        self.assertEqual((line["workflow"], line["step"], line["model"], line["in"], line["out"], line["ok"]),
                         ("brief", "rank", "model-a", 1500, 120, True))
        self.assertIn("S&P 500 6,000 ▼1.64%", result.text)
        self.assertIn("₹86,807/10g", result.text)  # 3000 $/oz * 90 ₹/$ / 31.1035 g * 10
        self.assertIn("Gold India*: ₹1,23,893/10g ▼0.89% (20 Nov)", result.text)
        self.assertIn("*India rate: IBJA 24K (999), excl. GST.", result.text)
        self.assertIn("Summary of i1", result.text)
        self.assertLess(render.visible_length(result.text), 4096, "fits one Telegram message")

    def test_newsletters_finance_mail_codes_and_old_news_never_reach_the_model(self):
        http = services()
        result = self.run_brief(http)
        prompt = self.gemini_prompts(http)[0]
        self.assertIn("Board meeting moved", prompt)
        self.assertIn("Contract signature needed", prompt)
        for absent in ("Weekly digest", "payslip", "verification code", "Old story", KEY):
            self.assertNotIn(absent.lower(), prompt.lower())
        self.assertIn("Money & HR · 1", result.text, "private mail is still listed, by the script")
        self.assertIn("Your payslip for Nov", result.text)
        self.assertNotIn("verification code", result.text, "one-time codes are dropped entirely")

    def test_mail_is_read_with_one_batch_request_not_one_call_per_mail(self):
        http = services()
        self.run_brief(http)
        self.assertEqual(http.count("https://www.googleapis.com/batch/gmail/v1"), 1)
        self.assertEqual(http.count("https://gmail.googleapis.com/gmail/v1/users/me/messages/"), 0)

    def test_mail_parts_throttled_inside_a_batch_are_retried(self):
        http = services()
        mails = {"m1": gmail_message("m1", "Board meeting moved")}
        attempts = []

        def flaky(call):
            attempts.append(call)
            return gmail_batch(mails if len(attempts) > 1 else {})(call)
        http.on("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages?", {"messages": [{"id": "m1"}]})
        http.on("POST", "https://www.googleapis.com/batch/gmail/v1", flaky)
        with mock.patch("orchestrator.brief.sources.gmail.time.sleep"):
            self.run_brief(http)
        self.assertEqual(len(attempts), 2)
        self.assertIn("Board meeting moved", self.gemini_prompts(http)[0])

    def test_second_run_with_nothing_new_makes_no_model_call(self):
        self.run_brief(services())
        http = services()
        result = self.run_brief(http, now=NOW + 60)
        self.assertEqual(self.gemini_prompts(http), [])
        self.assertEqual(len(self.usage_lines()), 1, "only the first run logged a call")
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
        self.assertEqual([(u["model"], u["ok"]) for u in self.usage_lines()], [("model-a", False), ("model-b", True)],
                         "the failed attempt is logged too")

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


class Layout(BriefCase):
    def brief_with_everything_picked(self) -> str:
        http = services(lambda call: gemini_answer([f"i{n}" for n in range(1, 10)]))
        replies = slack_reply(["Can you approve the vendor quote today?"])
        dm = slack_reply(["Lunch?"], channel="D1")["messages"]["matches"]
        dm[0]["user"] = "U2"
        replies["messages"]["matches"] += dm
        http.on("GET", "https://slack.com/api/search.messages", replies)
        return self.run_brief(http).text

    def test_sections_come_in_a_fixed_order_with_dms_apart_from_channels(self):
        text = self.brief_with_everything_picked()
        heads = ["**📈 Markets**", "**✉️ Gmail**", "**📧 Outlook**", "**💬 Slack**", "**📰 News · Top 2**"]
        self.assertEqual([text.index(h) for h in heads], sorted(text.index(h) for h in heads))
        slack = text[text.index("**💬 Slack**"):text.index("**📰 News")]
        self.assertLess(slack.index("_Direct messages_"), slack.index("• Ravi: "), "a DM is named once")
        self.assertLess(slack.index("_Channels_"), slack.index("• #ops — Asha: "))
        self.assertLess(slack.index("• Ravi: "), slack.index("_Channels_"))
        gmail = text[text.index("**✉️ Gmail**"):text.index("**📧 Outlook**")]
        self.assertIn("Your payslip for Nov", gmail, "money mail sits under its own account")

    def test_the_brief_carries_no_links_but_the_saved_edition_keeps_them(self):
        text = self.brief_with_everything_picked()
        self.assertNotIn("](", text)
        self.assertNotIn("https://", text)
        edition = Store(self.state).latest_edition()
        self.assertIn("https://n/2", [i["url"] for i in edition["top"] + edition["rest"]])
        self.assertNotIn("https://", cli.handle_chat_command("more", self.state, services()))


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
        limits = {True: 5, False: 5}
        picked, _lines = rank.parse_answer(
            '{"news": [{"id": "i9"}, {"id": "i1", "line": "x"}], "work": [{"id": "i1"}]}', {"i1": a}, limits)
        self.assertEqual(picked, [a])
        with self.assertRaises(ValueError):
            rank.parse_answer('{"news": [{"id": "nope"}]}', {"i1": a}, limits)

    def render(self, picked: list[Item], lines: dict[str, str]) -> str:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Kolkata")
        return render.brief_text(day=datetime.fromtimestamp(NOW, tz), ranked=picked, lines=lines, rest=[],
                                 markets=None, results=[], model="m", tz=tz)

    def test_sender_is_not_repeated_when_the_line_opens_with_their_name(self):
        dm = Item(uid="s", source="slack", title="t", ts=1, sender="Kasak Zutshi", where="Kasak Zutshi",
                  topic="Direct messages")
        text = self.render([dm], {"s": "Kasak Zutshi asked when Dipesh gets his ID."})
        self.assertIn("• Kasak Zutshi asked when Dipesh gets his ID.", text)

    def test_a_long_brief_drops_the_lowest_ranked_work_items_to_stay_one_message(self):
        work = [Item(uid=f"w{n}", source="gmail", title="t", ts=1, sender="A", where="a@x.com") for n in range(60)]
        news = [Item(uid="n", source="news", title="Headline", ts=1, topic="AI", where="Wire", url="https://n/1")]
        text = self.render(work + news, {i.uid: "x" * 150 for i in work + news})
        self.assertLessEqual(render.visible_length(text), render.TELEGRAM_BUDGET)
        self.assertIn("• A: " + "x" * 150, text, "the best work items stay")
        self.assertIn("1. AI · Wire: " + "x" * 150, text, "headlines go last")
        self.assertRegex(text, r"\+\d+ more")

    def test_default_filters_drop_sign_in_and_security_notices(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "brief.yaml").write_text((ROOT / "orchestrator/brief/brief.example.yaml").read_text())
            config = settings.load(Path(tmp))
        subjects = {"Security alert": False, "Reset your Inboundr password": False,
                    "[GitHub] A new public key was added to me/repo": False, "New sign-in to your account": False,
                    "Board meeting moved": True, "Re-Confirmation: Vipassana course": True}
        mails = [Item(uid=t, source="gmail", title=t, ts=1) for t in subjects]
        kept, _private, _ = filters.keep(mails, config, lambda uid: False)
        self.assertEqual({i.title for i in kept}, {t for t, keep in subjects.items() if keep})

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

    def test_ibja_headline_rate_is_the_fallback(self):
        http = FakeHttp().on("GET", "https://ibjarates.com/", '<span id="GoldRatesCompare999"> 12,389</span>')
        self.assertEqual(markets.india_gold(http).price_10g, 123890)
        broken = FakeHttp().on("GET", "https://ibjarates.com/", "<html>redesigned</html>")
        with self.assertRaises(ValueError):
            markets.india_gold(broken)


class SlackUser(BriefCase):
    def test_user_token_reads_member_conversations_in_two_calls_grouped_and_named(self):
        http = services()
        replies = slack_reply(["Can you approve the vendor quote today?", "Also the invoice"])
        replies["messages"]["matches"] += slack_reply(["Lunch?"], channel="D1")["messages"]["matches"]
        replies["messages"]["matches"] += slack_reply(["Not my channel"], channel="C9")["messages"]["matches"]
        http.on("GET", "https://slack.com/api/search.messages", replies)
        (self.state / "brief.yaml").write_text(CONFIG + "slack:\n  groups: {Core: [ops]}\n  weights: {Core: 2}\n",
                                               encoding="utf-8")
        self.run_brief(http)
        self.assertEqual(http.count("https://slack.com/api/users.conversations"), 1)
        self.assertEqual(http.count("https://slack.com/api/search.messages"), 1)
        self.assertEqual(http.count("https://slack.com/api/conversations.history"), 0)
        self.assertEqual(http.count("https://slack.com/api/users.info"), 1, "only the person users.list missed")
        prompt = self.gemini_prompts(http)[0]
        self.assertNotIn("Not my channel", prompt, "public channels you have not joined stay out")
        self.assertIn("Core · #ops", prompt)
        self.assertIn("Direct messages · Ravi", prompt)
        self.assertIn("Core (2)", prompt)
        self.assertEqual(prompt.count("| slack |"), 2, "one item per conversation, not per message")

    def test_reply_to_an_older_thread_is_its_own_item(self):
        http = services()
        reply = slack_reply(["Done, merged"])
        reply["messages"]["matches"][0]["permalink"] = "https://x/archives/C1/p1?thread_ts=1700000000.000100&cid=C1"
        http.on("GET", "https://slack.com/api/search.messages", reply)
        self.run_brief(http)
        self.assertIn("#ops (thread)", self.gemini_prompts(http)[0])

    def test_search_switched_off_falls_back_to_history(self):
        http = services()
        http.on("GET", "https://slack.com/api/search.messages", {"ok": False, "error": "method_deprecated"})
        http.on("GET", "https://slack.com/api/auth.test", {"ok": True, "url": "https://acme.slack.com/"})
        http.on("GET", "https://slack.com/api/conversations.history", {"ok": True, "messages": [
            {"ts": f"{NOW - 300:.6f}", "user": "U1", "text": "Ship the release today?"}]})
        self.run_brief(http)
        self.assertEqual(http.count("https://slack.com/api/conversations.history"), 3)
        self.assertIn("Ship the release today?", self.gemini_prompts(http)[0])


class GmailAccounts(BriefCase):
    def test_each_account_is_read_and_an_expired_one_is_named_alone(self):
        tokens = self.state / "tokens"
        (tokens / "google-work.json").write_text('{"refresh_token": "g-work", "email": "w@x.com"}', encoding="utf-8")
        (tokens / "google-old.json").write_text('{"refresh_token": "g-old"}', encoding="utf-8")
        http = services()

        def token(call):
            if call.form["refresh_token"] == "g-old":
                raise http_error(400, '{"error": "invalid_grant"}')(call)
            return {"access_token": "g-access"}
        http.on("POST", "https://oauth2.googleapis.com/token", token)
        result = self.run_brief(http)
        self.assertEqual(http.count("https://www.googleapis.com/batch/gmail/v1"), 2, "main and work")
        self.assertIn("🔑 Gmail (old) needs a new login", result.text)
        self.assertIn("auth google --account old", result.text)
        prompt = self.gemini_prompts(http)[0]
        self.assertIn("w@x.com", prompt)
        self.assertIn("Board meeting moved", prompt)
        gmail = result.text[result.text.index("**✉️ Gmail**"):result.text.index("**📧 Outlook**")]
        self.assertEqual(gmail.count("_w@x.com_"), 1, "each account's mail sits under one heading")


class SlackBot(BriefCase):
    def bot_services(self) -> FakeHttp:
        http = services()
        http.on("GET", "https://slack.com/api/auth.test", {"ok": True, "url": "https://acme.slack.com/"})
        http.on("GET", "https://slack.com/api/users.list", {"ok": True, "members": [
            {"id": "U1", "name": "asha", "profile": {"display_name": "Asha"}}]})
        http.on("GET", "https://slack.com/api/conversations.list", {"ok": True, "channels": [
            {"id": "C1", "name": "ops", "is_member": True}, {"id": "C2", "name": "random", "is_member": False}]})
        http.on("GET", "https://slack.com/api/conversations.history", {"ok": True, "messages": [
            {"ts": f"{NOW - 300:.6f}", "user": "U1", "text": "Ship the release today?"},
            {"ts": f"{NOW - 200:.6f}", "user": "U1", "subtype": "channel_join", "text": "joined"}]})
        return http

    def use_bot_token(self) -> None:
        env = (self.home / ".env").read_text(encoding="utf-8").replace("SLACK_USER_TOKEN=slack-test\n", "")
        (self.home / ".env").write_text(env + "SLACK_BOT_TOKEN=bot-test\n", encoding="utf-8")

    def test_bot_token_reads_member_channels_only(self):
        self.use_bot_token()
        http = self.bot_services()
        self.run_brief(http)
        read = [query(c)["channel"][0] for c in http.calls if "conversations.history" in c.url]
        self.assertEqual(read, ["C1"], "only channels the bot was invited to")
        self.assertEqual(http.count("https://slack.com/api/search.messages"), 0)
        prompt = self.gemini_prompts(http)[0]
        self.assertIn("Asha", prompt)
        self.assertIn("Ship the release today?", prompt)
        self.assertNotIn("joined", prompt)

    def test_missing_bot_scope_is_reported_as_a_login_problem(self):
        self.use_bot_token()
        http = self.bot_services()
        http.on("GET", "https://slack.com/api/conversations.list",
                {"ok": False, "error": "missing_scope", "needed": "groups:read"})
        self.assertIn("needs groups:read", self.run_brief(http).text)


class LoginCase(unittest.TestCase):
    """The one-time logins: paste-back with PKCE, no device code, no secret for Microsoft."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / ".env").write_text(ENV.format(key=KEY), encoding="utf-8")
        self.secrets = Secrets(self.home / ".env", self.home / "tokens", environ={})
        self.shown: list[str] = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def login(self, service, http: FakeHttp, landed: str) -> None:
        service(http, self.secrets, ask=lambda _prompt: landed, say=self.shown.append)

    def link(self) -> dict[str, list[str]]:
        url = next(line for line in self.shown if line.startswith("https://"))
        return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query) | {"_base": [url.split("?")[0]]}

    def test_microsoft_login_uses_pkce_and_no_device_code_or_secret(self):
        http = FakeHttp().on("POST", "https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
                             {"access_token": "a", "refresh_token": "ms-new"})
        self.login(auth.microsoft, http, "http://localhost:8765/?code=the-code&state=x")
        link = self.link()
        self.assertEqual(link["_base"], ["https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize"])
        self.assertEqual(link["code_challenge_method"], ["S256"])
        self.assertEqual(http.count("https://login.microsoftonline.com/tenant/oauth2/v2.0/devicecode"), 0)
        form = http.calls[-1].form
        self.assertEqual((form["grant_type"], form["code"]), ("authorization_code", "the-code"))
        self.assertNotIn("client_secret", form)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest())
        self.assertEqual(challenge.rstrip(b"=").decode(), link["code_challenge"][0])
        self.assertEqual(self.secrets.token("microsoft")["refresh_token"], "ms-new")

    def test_microsoft_login_asks_for_every_scope_a_later_refresh_needs(self):
        # A refresh token only yields scopes consented at sign-in; User.Read is not implied.
        http = FakeHttp().on("POST", "https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
                             {"access_token": "a", "refresh_token": "ms-new"})
        self.login(auth.microsoft, http, "http://localhost:8765/?code=the-code&state=x")
        asked = set(self.link()["scope"][0].split())
        for needed in (outlook.SCOPES, outlook.MEETING_SCOPES, outlook.SEND_SCOPES):
            self.assertLessEqual(set(needed.split()), asked, needed)

    def test_microsoft_refusal_in_the_pasted_address_is_shown_and_nothing_is_saved(self):
        landed = "http://localhost:8765/?error=access_denied&error_description=AADSTS65004%3A+User+declined"
        with self.assertRaises(SystemExit) as stop:
            self.login(auth.microsoft, FakeHttp(), landed)
        self.assertIn("AADSTS65004", str(stop.exception))
        self.assertEqual(self.secrets.token("microsoft"), {})

    def test_google_login_still_saves_its_refresh_token(self):
        http = FakeHttp().on("POST", "https://oauth2.googleapis.com/token", {"access_token": "a", "refresh_token": "g-new"})
        http.on("GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile", {"emailAddress": "me@gmail.com"})
        self.login(auth.google, http, "http://localhost:8765/?code=g-code&scope=x")
        self.assertEqual(http.calls[0].form["code"], "g-code")
        self.assertEqual(self.secrets.token("google"), {**self.secrets.token("google"), "refresh_token": "g-new",
                                                        "email": "me@gmail.com"})

    def test_second_gmail_account_gets_its_own_token_and_the_same_one_twice_is_refused(self):
        http = FakeHttp().on("POST", "https://oauth2.googleapis.com/token", {"access_token": "a", "refresh_token": "g-2"})
        http.on("GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile", {"emailAddress": "work@gmail.com"})
        auth.google(http, self.secrets, ask=lambda _p: "http://localhost:8765/?code=c", say=self.shown.append,
                    account="work")
        self.assertEqual(self.secrets.token("google-work")["email"], "work@gmail.com")
        with self.assertRaises(SystemExit) as stop:
            auth.google(http, self.secrets, ask=lambda _p: "http://localhost:8765/?code=c", say=self.shown.append,
                        account="family")
        self.assertIn("already saved as 'work'", str(stop.exception))


if __name__ == "__main__":
    unittest.main()
