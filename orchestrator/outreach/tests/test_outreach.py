"""Outreach behaviour against fake Slack, Microsoft Graph and Gemini (no network, no real model).

Run: python3 orchestrator/outreach/tests/test_outreach.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone, UTC
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator/brief/tests"))

from fakes import FakeHttp, http_error

from orchestrator.brief.sources import outlook
from orchestrator.outreach import chat, slots, times

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 23, 10, 0, tzinfo=IST).timestamp()  # Monday 10:00 IST
SLACK = "https://slack.com/api/"
GRAPH = "https://graph.microsoft.com/v1.0"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/"

MEMBERS = [
    {"id": "UME", "name": "jay", "profile": {"real_name": "Jay Patel", "email": "jay@co.com"}},
    {"id": "U1", "name": "priya", "profile": {"real_name": "Priya Shah", "email": "priya@co.com"}},
    {"id": "U2", "name": "rahul", "profile": {"real_name": "Rahul Mehta", "email": "rahul@co.com"}},
    {"id": "U3", "name": "prao", "profile": {"real_name": "Priya Rao", "email": "prao@co.com"}},
    {"id": "U4", "name": "amit", "profile": {"real_name": "Amit Jain", "email": "amit@co.com"}},
    {"id": "U5", "name": "neha", "profile": {"real_name": "Neha Iyer", "email": "neha@co.com"}},
    {"id": "U6", "name": "dev", "profile": {"real_name": "Dev Rao", "email": "dev@co.com"}},
    {"id": "B1", "name": "bot", "is_bot": True, "profile": {"real_name": "Bot"}},
]


def utc(hour: int, minute: int = 0, day: int = 23) -> str:
    """IST wall clock on the test day → the UTC ISO string Graph is sent."""
    return datetime(2026, 11, day, hour, minute, tzinfo=IST).astimezone(UTC).isoformat()


def graph_event(start_ist: tuple[int, int], end_ist: tuple[int, int]) -> dict:
    def stamp(hm):
        return datetime(2026, 11, 23, *hm, tzinfo=IST).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.0000000")
    return {"start": {"dateTime": stamp(start_ist)}, "end": {"dateTime": stamp(end_ist)}, "showAs": "busy"}


def gemini(answer: dict) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}],
            "usageMetadata": {"promptTokenCount": 400, "candidatesTokenCount": 200}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.state = home / "brief"
        (self.state / "tokens").mkdir(parents=True)
        (home / ".env").write_text("GEMINI_API_KEY=k-test\nSLACK_USER_TOKEN=slack-test\nMS_CLIENT_ID=ms\n"
                                   "MS_TENANT_ID=t\n", encoding="utf-8")
        (self.state / "tokens/microsoft.json").write_text('{"refresh_token": "r0"}', encoding="utf-8")
        self.busy: list[dict] = []
        self.events: list[dict] = []
        self.http = FakeHttp()
        self.http.on("GET", SLACK + "users.list", {"ok": True, "members": MEMBERS})
        self.http.on("GET", SLACK + "auth.test", {"ok": True, "user_id": "UME"})
        self.http.on("GET", SLACK + "users.lookupByEmail", {"ok": False, "error": "users_not_found"})
        self.http.on("GET", SLACK + "users.conversations",
                     {"ok": True, "channels": [{"id": "CHOME", "name": "home"}, {"id": "CCORE", "name": "core"}]})
        self.http.on("GET", SLACK + "conversations.members", {"ok": True, "members": ["UME", "U1", "U2", "B1"]})
        self.http.on("POST", SLACK + "conversations.open",
                     lambda c: {"ok": True, "channel": {"id": "D-" + c.json_body["users"]}})
        self.http.on("POST", SLACK + "chat.postMessage", {"ok": True, "ts": "1.1"})
        self.http.on("POST", SLACK + "chat.scheduleMessage", {"ok": True, "scheduled_message_id": "Q1"})
        self.http.on("POST", "https://login.microsoftonline.com/t/oauth2/v2.0/token",
                     {"access_token": "ms-access", "refresh_token": "r1"})
        self.http.on("GET", GRAPH + "/me/calendarView", lambda _c: {"value": self.busy})
        self.http.on("GET", GRAPH + "/users", {"value": []})
        self.http.on("POST", GRAPH + "/me/events", self._event)

    def tearDown(self):
        self.tmp.cleanup()

    def _event(self, call):
        self.events.append(call.json_body)
        return {"id": f"E{len(self.events)}", "onlineMeeting": {"joinUrl": "https://teams.example/j/1"}}

    def model(self, answer: dict) -> None:
        self.http.on("POST", GEMINI, gemini(answer))

    def slack(self, words: str, at: float = NOW) -> str:
        return chat.handle_slack(words, self.state, self.http, at)

    def meet(self, words: str, at: float = NOW) -> str:
        return chat.handle_meet(words, self.state, self.http, at)

    def posts(self) -> list[dict]:
        return [c.json_body for c in self.http.calls if c.url.startswith(SLACK + "chat.postMessage")]

    def model_calls(self) -> list[str]:
        return [c.url.removeprefix(GEMINI).split(":")[0] for c in self.http.calls if c.url.startswith(GEMINI)]

    def sent_log(self) -> list[dict]:
        path = self.state / "outreach/sent.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.is_file() else []


class Slots(unittest.TestCase):
    def test_ten_one_on_ones_are_packed_back_to_back_not_spread(self):
        start = datetime(2026, 11, 23, 15, 0, tzinfo=IST)
        placed, left = slots.pack([(f"p{n}", 15) for n in range(10)], start, start + timedelta(hours=4), [], 5)
        self.assertEqual(left, [])
        self.assertEqual([s.start.strftime("%H:%M") for s in placed][:3], ["15:00", "15:20", "15:40"])
        self.assertEqual(placed[-1].end.strftime("%H:%M"), "18:15", "the hour after 18:15 stays free")

    def test_busy_event_keeps_the_gap_on_both_sides(self):
        start = datetime(2026, 11, 23, 15, 0, tzinfo=IST)
        busy = [(start + timedelta(minutes=30), start + timedelta(minutes=60))]
        placed, _ = slots.pack([("a", 15), ("b", 15), ("c", 15)], start, None, busy, 5)
        self.assertEqual([s.start.strftime("%H:%M") for s in placed], ["15:00", "16:05", "16:25"])

    def test_what_does_not_fit_is_listed(self):
        start = datetime(2026, 11, 23, 15, 0, tzinfo=IST)
        placed, left = slots.pack([("a", 30), ("b", 30), ("c", 30)], start, start + timedelta(hours=1), [], 5)
        self.assertEqual([s.who for s in placed], ["a"])
        self.assertEqual(left, ["b", "c"])

    def test_clock_words(self):
        today = date(2026, 11, 23)
        self.assertEqual(times.window("3pm-6pm"), (time(15), time(18)))
        self.assertIsNone(times.clock("3"), "a bare 3 could be am or pm")
        self.assertIsNone(times.day("monica", today), "a name is not a weekday")
        self.assertEqual(times.day("wed", today), date(2026, 11, 25))
        self.assertEqual(times.length("1h30m"), 90)


class SlackSend(Base):
    def test_send_goes_out_at_once_in_your_exact_words(self):
        reply = self.slack("send @priya @rahul: Please send the Q3 numbers by 5")
        self.assertIn("Sent", reply)
        self.assertEqual([p["text"] for p in self.posts()], ["Please send the Q3 numbers by 5"] * 2)
        self.assertEqual([p["channel"] for p in self.posts()], ["D-U1", "D-U2"])
        self.assertEqual(len(self.sent_log()), 2)
        self.assertEqual(self.model_calls(), [])

    def test_a_name_that_fits_two_people_sends_nothing(self):
        reply = self.slack("send Priya, @rahul: hello")
        self.assertIn("Priya Shah", reply)
        self.assertIn("Priya Rao", reply)
        self.assertEqual(self.posts(), [])

    def test_a_typo_stops_and_suggests_but_never_picks(self):
        reply = self.slack("send @rahull: hello")
        self.assertIn("Did you mean Rahul Mehta", reply)
        self.assertEqual(self.posts(), [])

    def test_a_partial_name_is_refused_when_sending_at_once_but_shown_in_a_preview(self):
        reply = self.slack("send @ami: hello")
        self.assertIn("Did you mean Amit Jain", reply)
        self.assertEqual(self.posts(), [])
        self.model({"messages": [{"to": "p1", "text": "Hi Amit."}]})
        self.assertIn("Amit Jain: Hi Amit.", self.slack("draft @ami: say hi"))

    def test_schedule_lets_slack_deliver_it_later(self):
        self.slack("schedule tomorrow 9am @priya: Standup moved to 10")
        body = next(c.json_body for c in self.http.calls if c.url.startswith(SLACK + "chat.scheduleMessage"))
        self.assertEqual(body["post_at"], int(datetime(2026, 11, 24, 9, 0, tzinfo=IST).timestamp()))
        self.assertEqual(self.posts(), [])

    def test_draft_waits_for_yes_and_yes_picks_lines(self):
        self.model({"messages": [{"to": "p1", "text": "Hi Priya, could you share the Q3 numbers by Friday?"},
                                 {"to": "p2", "text": "Hi Rahul, could you share the Q3 numbers by Friday?"}]})
        reply = self.slack("draft @priya @rahul: ask for Q3 numbers by Friday")
        self.assertIn("Nothing is sent yet", reply)
        self.assertEqual(self.posts(), [])
        self.assertEqual(self.model_calls(), ["gemma-4-31b-it"], "two people: Gemma first")
        self.slack("yes 2")
        self.assertEqual(self.posts(), [{"channel": "D-U2", "text": "Hi Rahul, could you share the Q3 numbers by Friday?"}])
        self.assertIn("Nothing is waiting", self.slack("yes"))

    def test_drafts_are_written_in_the_style_file_and_keep_the_facts_rule(self):
        (self.state / "outreach").mkdir(exist_ok=True)
        (self.state / "outreach/style.md").write_text("Hinglish with teammates. Example: {bhai} update?",
                                                      encoding="utf-8")
        self.model({"messages": [{"to": "p1", "text": "Priya, Q3 numbers Friday tak bhej dena?"}]})
        self.slack("draft @priya: ask for Q3 numbers by Friday")
        prompt = json.dumps([c.json_body for c in self.http.calls if c.url.startswith(GEMINI)])
        self.assertIn("Hinglish with teammates. Example: {bhai} update?", prompt)
        self.assertIn("invent nothing", prompt)
        self.assertNotIn("Greet the person by first name", prompt, "the default style is replaced")

    def test_edit_replaces_a_draft_before_sending(self):
        self.model({"messages": [{"to": "p1", "text": "Hi Priya, draft one."}]})
        self.slack("draft @priya: say hi")
        self.slack("edit 1 Hi Priya, my own words.")
        self.slack("yes")
        self.assertEqual(self.posts()[0]["text"], "Hi Priya, my own words.")

    def test_a_plan_expires(self):
        self.model({"messages": [{"to": "p1", "text": "Hi Priya."}]})
        self.slack("draft @priya: say hi")
        self.assertIn("Nothing is waiting", self.slack("yes", at=NOW + 31 * 60))
        self.assertEqual(self.posts(), [])

    def test_daily_cap_refuses_the_whole_batch(self):
        (self.state / "brief.yaml").write_text("outreach: {daily_cap: 3}\n", encoding="utf-8")
        self.slack("send @priya @rahul: one")
        reply = self.slack("send @amit @neha: two")
        self.assertIn("Not sent", reply)
        self.assertEqual(len(self.posts()), 2)


class Meetings(Base):
    def test_one_named_person_at_a_free_time_is_booked_at_once(self):
        reply = self.meet("15:00 30m @priya: vendor contract")
        self.assertIn("Sent", reply)
        self.assertEqual(len(self.events), 1)
        event = self.events[0]
        self.assertEqual(event["start"]["dateTime"], "2026-11-23T09:30:00")  # 15:00 IST in UTC
        self.assertEqual(event["attendees"][0]["emailAddress"]["address"], "priya@co.com")
        self.assertTrue(event["isOnlineMeeting"])
        self.assertIn("vendor contract", self.posts()[0]["text"])
        self.assertIn("Join on Teams: https://teams.example/j/1", self.posts()[0]["text"])
        self.assertTrue(event["responseRequested"])
        self.assertEqual(self.model_calls(), [])

    def test_a_retried_invite_carries_the_same_transaction_id(self):
        self.meet("15:00 30m @priya: vendor contract")
        self.meet("15:00 30m @priya: vendor contract")
        self.assertEqual(self.events[0]["transactionId"], self.events[1]["transactionId"],
                         "Outlook returns the first event instead of sending a second invite")

    def test_busy_at_that_time_shows_the_next_free_slot_instead(self):
        self.busy = [graph_event((15, 0), (15, 30))]
        reply = self.meet("15:00 30m @priya: vendor contract")
        self.assertIn("3:35 PM", reply)
        self.assertIn("busy at 3:00 PM", reply)
        self.assertEqual(self.events, [])

    def test_a_big_batch_sentence_uses_gemini_and_packs_from_the_start(self):
        self.model({"kind": "meetings", "people": ["Rahul", "Amit", "Neha", "Dev", "@priya"], "date": "2026-11-23",
                    "start": "15:00", "end": "19:00", "length_min": 15, "gap_min": 5, "topic": "Q3 review"})
        reply = self.meet("one-on-ones with Rahul, Amit, Neha, Dev and @priya from 3 to 7, 15 minutes each, 5 min break")
        self.assertEqual(self.model_calls(), ["gemini-3.1-flash-lite"], "five people: the big-batch chain")
        self.assertIn("Nothing is sent yet", reply)
        self.assertEqual(self.events, [])
        self.meet("yes")
        self.assertEqual([e["start"]["dateTime"][11:16] for e in self.events],
                         ["09:30", "09:50", "10:10", "10:30", "10:50"])  # 15:00, 15:20 … IST
        self.assertEqual(len(self.posts()), 5)
        self.assertEqual(len(self.sent_log()), 10)

    def test_allhands_invites_the_channel_and_posts_the_teams_link(self):
        reply = self.meet("allhands 16:00 60m #home: Q3 review")
        self.assertIn("2 invited", reply)
        self.meet("yes")
        self.assertEqual({a["emailAddress"]["address"] for a in self.events[0]["attendees"]},
                         {"priya@co.com", "rahul@co.com"}, "you and bots are not invited")
        post = self.posts()[0]
        self.assertEqual(post["channel"], "CHOME")
        self.assertIn("https://teams.example/j/1", post["text"])

    def test_someone_only_in_outlook_gets_the_invite_and_no_slack_note(self):
        self.http.on("GET", GRAPH + "/users",
                     {"value": [{"displayName": "Kiran Rao", "givenName": "Kiran", "mail": "kiran@client.com"}]})
        self.meet("15:00 30m @kiran: proposal")
        self.assertEqual(self.events[0]["attendees"][0]["emailAddress"]["address"], "kiran@client.com")
        self.assertEqual(self.posts(), [])

    def test_missing_calendar_consent_is_named_and_the_brief_keeps_mail_read(self):
        self.http.on("POST", "https://login.microsoftonline.com/t/oauth2/v2.0/token",
                     lambda c: http_error(400, "AADSTS65001: not consented")(c)
                     if "Calendars" in c.form["scope"] else {"access_token": "a", "refresh_token": "r2"})
        reply = self.meet("15:00 30m @priya: vendor contract")
        self.assertIn("permission not granted", reply)
        self.assertIn("Calendars.ReadWrite", reply)
        self.assertEqual((self.events, self.posts()), ([], []))
        fresh = outlook.refresh(self.http, "ms", "t", {"refresh_token": "r1"})
        self.assertEqual(fresh["access_token"], "a", "the brief's Outlook refresh asks for Mail.Read only")

    def test_the_agent_draft_never_sends(self):
        self.model({"kind": "messages", "people": ["@priya"], "messages": [{"to": "@priya", "text": "Hi Priya."}]})
        reply = chat.draft("tell @priya hi", self.state, self.http, NOW)
        self.assertIn("/slack yes", reply)
        self.assertEqual(self.posts(), [])
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()
