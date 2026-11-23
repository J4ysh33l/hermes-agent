"""My day against a fake Microsoft To Do, calendar and Telegram (no network, no model).

Run: python3 orchestrator/myday/tests/test_myday.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
import urllib.parse
from datetime import date, datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from orchestrator import commands
from orchestrator.brief.net import HttpError, Response
from orchestrator.myday import billmail, bills, card, chat, dates, game
from orchestrator.myday.session import Session

IST = ZoneInfo("Asia/Kolkata")
GRAPH = "https://graph.microsoft.com/v1.0"


def at(day: int, hour: int, minute: int = 0, month: int = 11) -> float:
    return datetime(2026, month, day, hour, minute, tzinfo=IST).timestamp()


class FakeMicrosoft:
    """Token refresh, To Do lists/tasks/steps, calendarView and Telegram sendAnimation, in memory."""

    def __init__(self) -> None:
        self.lists = [{"id": "L0", "displayName": "Tasks", "wellknownListName": "defaultList"}]
        self.tasks: dict[str, dict[str, dict]] = {"L0": {}}
        self.steps: dict[str, list[dict]] = {}
        self.events: list[dict] = []
        self.calendar_fails = False
        self.animations: list[dict] = []
        self.mails: list[dict] = []  # Gmail: {"id", "subject", "from", "html"}
        self.mail_reads: list[str] = []
        self.todo_add_fails = False
        self.n = 0

    def _id(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}{self.n}"

    def add(self, title: str, due: date | None, list_id: str = "L0", done: bool = False) -> str:
        task_id = self._id("T")
        row = {"id": task_id, "title": title, "status": "completed" if done else "notStarted", "importance": "normal"}
        if due:
            row["dueDateTime"] = {"dateTime": f"{due.isoformat()}T00:00:00.0000000", "timeZone": "UTC"}
        self.tasks[list_id][task_id] = row
        return task_id

    def complete_in_app(self, task_id: str) -> None:
        for rows in self.tasks.values():
            if task_id in rows:
                rows[task_id]["status"] = "completed"

    def open_titles(self, list_name: str = "Tasks") -> list[str]:
        list_id = next(x["id"] for x in self.lists if x["displayName"] == list_name)
        return [t["title"] for t in self.tasks[list_id].values() if t["status"] != "completed"]

    def request(self, method, url, *, params=None, headers=None, form=None, json_body=None, data=None):
        path = urllib.parse.urlsplit(url).path
        if url.startswith("https://oauth2.googleapis.com/"):
            return self._json({"access_token": "GAT"})
        if url.startswith("https://gmail.googleapis.com/"):
            return self._json(self._gmail(path))
        if url.startswith("https://login.microsoftonline.com/"):
            return self._json({"access_token": "AT", "refresh_token": "RT2"})
        if "api.telegram.org" in url:
            self.animations.append({"url": url, "size": len(data or b""), "body": data})
            return self._json({"ok": True})
        if path.endswith("/me/calendarView"):
            if self.calendar_fails:
                raise HttpError(500, url)
            return self._json({"value": self.events})
        return self._json(self._todo(method, path.removeprefix("/v1.0/me/todo/"), params or {}, json_body))

    def _gmail(self, path: str) -> dict:
        if path.endswith("/messages"):
            return {"messages": [{"id": m["id"]} for m in self.mails]}
        mail = next(m for m in self.mails if m["id"] == path.rsplit("/", 1)[1])
        self.mail_reads.append(mail["id"])
        body = base64.urlsafe_b64encode(mail["html"].encode()).decode().rstrip("=")
        return {"id": mail["id"], "payload": {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "Subject", "value": mail["subject"]}, {"name": "From", "value": mail["from"]}],
            "parts": [{"mimeType": "text/html", "body": {"data": body}}]}}

    @staticmethod
    def _json(body) -> Response:
        return Response(200, json.dumps(body).encode())

    def _todo(self, method: str, path: str, params: dict, body):
        parts = path.split("/")
        if parts == ["lists"]:
            if method == "POST":
                row = {"id": self._id("L"), "displayName": body["displayName"]}
                self.lists.append(row)
                self.tasks[row["id"]] = {}
                return row
            return {"value": self.lists}
        list_id = parts[1]
        rows = self.tasks[list_id]
        if len(parts) == 3:  # lists/{id}/tasks
            if method == "POST" and self.todo_add_fails:
                raise HttpError(503, GRAPH)
            if method == "POST":
                row = {"id": self._id("T"), "status": "notStarted", **body}
                rows[row["id"]] = row
                return row
            keep = [r for r in rows.values() if "ne 'completed'" not in params.get("$filter", "")
                    or r["status"] != "completed"]
            return {"value": keep}
        task_id = parts[3]
        if len(parts) == 4:
            if task_id not in rows:
                raise HttpError(404, GRAPH)
            if method == "PATCH":
                rows[task_id].update({k: v for k, v in body.items() if v is not None})
                if body.get("dueDateTime", 0) is None:
                    rows[task_id].pop("dueDateTime", None)
            return rows[task_id]
        steps = self.steps.setdefault(task_id, [])
        if len(parts) == 5:  # checklistItems
            if method == "POST":
                step = {"id": self._id("S"), "displayName": body["displayName"], "isChecked": False}
                steps.append(step)
                return step
            return {"value": steps}
        step = next(s for s in steps if s["id"] == parts[5])
        step.update(body)
        return step


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / ".env").write_text("MS_CLIENT_ID=c\nMS_TENANT_ID=t\nTELEGRAM_BOT_TOKEN=123:abc\n"
                                        "TELEGRAM_ALLOWED_USERS=42\n", encoding="utf-8")
        tokens = self.home / "brief" / "tokens"
        tokens.mkdir(parents=True)
        (tokens / "microsoft.json").write_text(json.dumps({"refresh_token": "RT"}), encoding="utf-8")
        self.dir = self.home / "myday"
        self.fake = FakeMicrosoft()
        self.env = mock.patch.dict("os.environ", {"HERMES_HOME": str(self.home)}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def session(self, now: float) -> Session:
        return Session(self.dir, self.fake, now)

    def cmd(self, table, args: str, now: float) -> str:
        return chat.run(table, "help", args, session=self.session(now))

    def state(self) -> dict:
        return json.loads((self.dir / "state.json").read_text(encoding="utf-8"))


class Dates(unittest.TestCase):
    MON = date(2026, 11, 23)

    def test_words(self):
        cases = {"today": self.MON, "tomorrow": date(2026, 11, 24), "fri": date(2026, 11, 27),
                 "monday": self.MON, "25 nov": date(2026, 11, 25), "5 jan": date(2027, 1, 5),
                 "25/11": date(2026, 11, 25), "+3": date(2026, 11, 26), "3d": date(2026, 11, 26),
                 "next week": date(2026, 11, 30), "2026-12-31": date(2026, 12, 31), "someday": None}
        for words, want in cases.items():
            with self.subTest(words=words):
                self.assertEqual(dates.parse(words, self.MON), want)
        with self.assertRaises(dates.NoDate):
            dates.parse("month", self.MON)

    def test_trailing_date_is_split_from_the_title(self):
        self.assertEqual(dates.split_trailing("Call Apollo by fri", self.MON, self.MON), ("Call Apollo", date(2026, 11, 27)))
        self.assertEqual(dates.split_trailing("Read 3 papers", self.MON, self.MON), ("Read 3 papers", self.MON))
        self.assertEqual(dates.split_trailing("Pitch deck 25 nov", self.MON, None), ("Pitch deck", date(2026, 11, 25)))


class Levels(unittest.TestCase):
    def test_thresholds(self):
        names = ("A", "B", "C")
        self.assertEqual(game.level_for(0, names).number, 1)
        self.assertEqual(game.level_for(99, names).number, 1)
        self.assertEqual((game.level_for(100, names).number, game.level_for(100, names).next_at), (2, 300))
        self.assertEqual(game.level_for(600, names).name, "C 2")


class Streak(Base):
    def test_finishing_everything_due_grows_the_streak_once_and_sends_the_animation(self):
        self.fake.add("Call Apollo", date(2026, 11, 23))
        self.fake.add("Send deck", date(2026, 11, 22))  # overdue counts as due now
        self.fake.add("Someday idea", None)
        board = self.cmd(chat.DAY, "now", at(23, 8))
        self.assertIn("1.", board)
        self.assertIn("Send deck (yesterday)", board)
        self.assertIn("1 in later", board)
        self.cmd(chat.DAY, "top 1", at(23, 8, 5))
        first = self.cmd(chat.DAY, "done 1", at(23, 9))
        self.assertIn("+20", first)
        self.assertEqual(self.fake.animations, [])
        second = self.cmd(chat.DAY, "done 1", at(23, 10))  # the list is unchanged: 1 is still "Call Apollo"
        self.assertIn("already done", second)
        self.cmd(chat.DAY, "now", at(23, 10, 1))
        last = self.cmd(chat.DAY, "done 1", at(23, 10, 2))
        self.assertIn("All clear", last)
        state = self.state()
        self.assertEqual((state["streak"], state["best"]), (1, 1))
        self.assertEqual(state["points"], 20 + 10 + 50)
        self.assertEqual(len(self.fake.animations), 1)
        self.assertIn("/bot123:abc/sendAnimation", self.fake.animations[0]["url"])
        self.assertIn(b'name="chat_id"\r\n\r\n42', self.fake.animations[0]["body"])
        body = self.fake.animations[0]["body"]
        self.assertTrue(b"ftypisom" in body or b"GIF89a" in body)  # MP4 with ffmpeg, else GIF

    def test_a_task_ticked_in_the_to_do_app_scores_on_the_next_tick(self):
        task = self.fake.add("Review contract", date(2026, 11, 23))
        first = self.session(at(23, 9))
        card.tick(first)
        first.save()
        self.fake.complete_in_app(task)
        session = self.session(at(23, 9, 15))
        reply = card.tick(session)
        session.save()
        self.assertEqual([e.kind for e in reply.events], ["clear"])
        self.assertEqual(self.state()["points"], 10 + 50)

    def test_a_day_left_open_breaks_the_streak_at_the_next_morning_card_not_at_midnight(self):
        self.fake.add("Old task", date(2026, 11, 22))
        state = game.State.load(self.dir)
        state.data["streak"] = 4
        state.save()
        session = self.session(at(22, 20))
        card.tick(session)
        session.save()
        night = self.session(at(23, 0, 15))
        self.assertEqual(card.tick(night).events, ())
        night.save()
        self.assertEqual(self.state()["streak"], 4)
        morning = self.session(at(23, 7, 30))
        reply = card.morning(morning)
        morning.save()
        self.assertEqual([(e.kind, e.streak) for e in reply.events], [("broken", 4)])
        self.assertIn("streak reset", reply.text)
        self.assertEqual(self.state()["streak"], 0)

    def test_a_day_with_nothing_due_neither_grows_nor_breaks_the_streak(self):
        state = game.State.load(self.dir)
        state.data["streak"] = 2
        state.save()
        for day in (22, 23):
            session = self.session(at(day, 7, 30))
            card.morning(session)
            session.save()
        self.assertEqual(self.state()["streak"], 2)

    def test_snooze_moves_the_task_and_costs_points(self):
        self.fake.add("Write blog", date(2026, 11, 23))
        self.fake.add("Call bank", date(2026, 11, 23))
        self.cmd(chat.DAY, "now", at(23, 8))
        self.cmd(chat.DAY, "done 1", at(23, 8, 1))  # Call bank (the list is sorted by title)
        reply = self.cmd(chat.DAY, "snooze 2 fri", at(23, 9))
        self.assertIn("Write blog → Fri", reply)
        self.assertEqual(self.state()["points"], 10 - 5 + 50)  # snoozing the last one clears the day
        self.assertEqual(self.fake.open_titles(), ["Write blog"])

    def test_add_reads_the_date_and_bang_makes_a_top_pick(self):
        reply = self.cmd(chat.DAY, "add Call Apollo about the pilot !", at(23, 8))
        self.assertIn("Call Apollo about the pilot — today ★ top", reply)
        self.cmd(chat.DAY, "add Prepare board pack by fri", at(23, 8))
        due = [t.get("dueDateTime", {}).get("dateTime", "")[:10] for t in self.fake.tasks["L0"].values()]
        self.assertEqual(due, ["2026-11-23", "2026-11-27"])

    def test_a_bad_number_or_date_is_answered_not_raised(self):
        self.fake.add("Task", date(2026, 11, 23))
        self.cmd(chat.DAY, "now", at(23, 8))
        self.assertIn("No item 5", self.cmd(chat.DAY, "done 5", at(23, 8)))
        self.assertIn("not a date", self.cmd(chat.DAY, "snooze 1 blorp", at(23, 8)))


class Bills(Base):
    def test_cycle_across_months_and_month_ends(self):
        late = bills.Bill("x", "X", 20, 10)
        self.assertEqual(bills.cycle(late, 2026, 11), bills.Cycle(late, date(2026, 11, 20), date(2026, 12, 10)))
        end = bills.Bill("y", "Y", 31, 31)
        self.assertEqual(bills.cycle(end, 2027, 2).due, date(2027, 2, 28))

    def test_generation_day_creates_one_to_do_task_and_reminders_follow_the_due_date(self):
        self.cmd(chat.BILLS, "add HDFC card 20 10 4500", at(18, 10))
        self.assertEqual(self.fake.open_titles("Bills") if any(x["displayName"] == "Bills" for x in self.fake.lists)
                         else [], [])
        on_gen = self.session(at(20, 9, 0))
        lines = bills.reminders(on_gen)
        on_gen.save()
        self.assertEqual(lines, ["📄 HDFC card bill generated today, due 10 Dec ₹4,500"])
        self.assertEqual(self.fake.open_titles("Bills"), ["💳 Pay HDFC card ₹4,500"])
        task = next(iter(self.fake.tasks["L1"].values()))
        self.assertEqual(task["dueDateTime"]["dateTime"], "2026-12-10T00:00:00")
        self.assertEqual(task["reminderDateTime"]["dateTime"], "2026-12-07T04:30:00")  # 3 days before, 10:00 IST
        again = self.session(at(20, 9, 15))
        self.assertEqual(bills.reminders(again), [])
        again.save()
        three_before = self.session(at(7, 10, month=12))
        self.assertEqual(bills.reminders(three_before), ["💳 HDFC card ₹4,500 due in 3 days (10 Dec) · /bills to mark it paid"])
        three_before.save()
        self.assertEqual(len(self.fake.open_titles("Bills")), 1)

    def test_paying_in_to_do_counts_and_the_timeline_moves_on(self):
        self.cmd(chat.BILLS, "add Airtel 1 15 999", at(1, 9))
        session = self.session(at(2, 9))
        bills.reminders(session)
        session.save()
        task_id = next(iter(self.fake.tasks["L1"]))
        self.cmd(chat.DAY, "now", at(15, 8))
        self.fake.complete_in_app(task_id)
        tick = self.session(at(15, 8, 15))
        card.tick(tick)
        tick.save()
        self.assertEqual(self.state()["points"], 15 + 50)  # on time, and it was all that was due
        timeline = self.cmd(chat.BILLS, "show", at(15, 9))
        self.assertIn("Airtel ₹999 — gen 1 Dec → due 15 Dec · 📄 generates 1 Dec", timeline)

    def test_paid_command_late_scores_less(self):
        self.cmd(chat.BILLS, "add Rent 1 5 30000", at(1, 9))
        self.cmd(chat.BILLS, "show", at(7, 9))
        reply = self.cmd(chat.BILLS, "paid 1", at(7, 9, 1))
        self.assertIn("late) +5", reply)
        self.assertEqual(self.fake.open_titles("Bills"), [])


class Goals(Base):
    def test_goals_with_milestones_show_progress(self):
        self.cmd(chat.GOALS, "add work Sign 3 hospitals by 31 dec", at(23, 9))
        self.cmd(chat.GOALS, "add personal Run 10k", at(23, 9))
        listing = self.cmd(chat.GOALS, "show", at(23, 9))
        self.assertIn("**💼 Work**\n1. Sign 3 hospitals — 31 Dec (no steps yet)", listing)
        self.assertIn("**🌱 Personal**\n2. Run 10k — someday", listing)
        self.cmd(chat.GOALS, "step 1 Apollo", at(23, 9))
        self.cmd(chat.GOALS, "step 1 Fortis", at(23, 9))
        reply = self.cmd(chat.GOALS, "tick 1.2", at(23, 9))
        self.assertIn("✅ Fortis +25", reply)
        self.assertIn("▰▰▰▰▱▱▱▱ 1/2", reply)
        self.assertIn("🏆 Goal reached: Run 10k +100", self.cmd(chat.GOALS, "done 2", at(23, 9)))


class Card(Base):
    def test_morning_card_survives_a_calendar_failure(self):
        self.fake.add("Call Apollo", date(2026, 11, 23))
        self.fake.calendar_fails = True
        reply = card.morning(self.session(at(23, 7, 30)))
        self.assertIn("1. ▫️ Call Apollo", reply.text)
        self.assertIn("⚠️ calendar: calendar: HTTP 500", reply.text)
        self.assertIn("Pick your top 3", reply.text)

    def test_wrap_up_once_at_its_time_with_what_is_left(self):
        self.fake.add("Call Apollo", date(2026, 11, 23))
        early = self.session(at(23, 21, 0))
        self.assertNotIn("Wrap-up", card.tick(early).text)
        session = self.session(at(23, 21, 30))
        text = card.tick(session).text
        session.save()
        self.assertIn("🌙 Wrap-up: +0 pts today. 1 still open:\n· Call Apollo", text)
        self.assertNotIn("Wrap-up", card.tick(self.session(at(23, 21, 45))).text)


STATEMENT_MAIL = ("Your Example Bank Rewards credit card statement for November, 2026", "Example Bank <cards@bank.example>",
          "<p>Due Date: 09 Dec 2026</p><td>Total Amount Due</td><td>&#8377;123,456.78</td>"
          "<td>Minimum Amount Due</td><td>&#8377;6,172.84</td>")
CRED = ("Important : New bill for your Example Bank card XXXX-1234 is here", "CRED <protect@cred.club>",
        "bill summary total amount due ₹1,23,456.78 minimum due ₹6,172.84 due date December 09, 2026")
NOTHING_DUE = ("Your Other Bank Classic Credit Card Statement ending XX00 - November 2026",
                    "statements@other.example",
                    "Total Amount Due INR Minimum Amount Due (INR) Payment Due Date (DD-MM-YYYY) 0 0 10/12/2026")
POWER = ("CITYPOWER City Power Distribution Limited Bill of INR 450.00",
         "Other Bank Alerts <alerts@other.example>",
         "Bill Amount: INR 450.00 Biller Name: CITYPOWER City Power Distribution Due on: 10-12-2026")


class BillMail(Base):
    def setUp(self):
        super().setUp()
        with (self.home / ".env").open("a", encoding="utf-8") as fh:
            fh.write("GOOGLE_CLIENT_ID=g\nGOOGLE_CLIENT_SECRET=s\n")
        (self.home / "brief" / "tokens" / "google.json").write_text(json.dumps({"refresh_token": "GRT"}),
                                                                     encoding="utf-8")

    def mail(self, subject: str, sender: str, html: str) -> None:
        self.fake.mails.append({"id": f"m{len(self.fake.mails) + 1}", "subject": subject, "from": sender, "html": html})

    @staticmethod
    def parse(subject: str, sender: str, html: str, today: date):
        text = billmail.message_text({"mimeType": "text/html",
                                      "body": {"data": base64.urlsafe_b64encode(html.encode()).decode()}})
        return billmail.parse(subject, sender, text, today)

    def test_reads_amount_due_and_due_date_from_statement_and_bill_mails(self):
        today, parse = date(2026, 11, 23), self.parse
        self.assertEqual(parse(*STATEMENT_MAIL, today), billmail.Found("Example Bank Rewards card", 123456.78, date(2026, 12, 9)))
        self.assertEqual(parse(*CRED, today), billmail.Found("Example Bank card XXXX-1234", 123456.78, date(2026, 12, 9)))
        self.assertEqual(parse(*POWER, today), billmail.Found("CITYPOWER bill", 450.0, date(2026, 12, 10)))
        self.assertIsNone(parse(*NOTHING_DUE, today))  # ₹0 due
        self.assertIsNone(parse(*STATEMENT_MAIL, date(2026, 12, 10)))  # already past its due date

    def morning(self, now: float) -> str:
        session = self.session(now)
        text = card.morning(session).text
        session.save()
        return text

    def test_one_bill_mailed_twice_becomes_one_to_do_task_with_reminders_and_points(self):
        for mail in (STATEMENT_MAIL, CRED, NOTHING_DUE):
            self.mail(*mail)
        text = self.morning(at(23, 7, 30))
        self.assertEqual(text.count("📬 New bill in Gmail"), 1)
        self.assertIn("Example Bank Rewards card ₹123,456.78 due 9 Dec", text)
        self.assertEqual(self.fake.open_titles("Bills"), ["💳 Pay Example Bank Rewards card ₹123,456.78"])
        task = next(iter(self.fake.tasks["L1"].values()))
        self.assertEqual(task["reminderDateTime"]["dateTime"], "2026-12-06T04:30:00")  # 3 days before, 10:00 IST

        self.mail(*POWER)
        reads = len(self.fake.mail_reads)
        self.assertNotIn("📬", self.morning(at(23, 9)))  # Gmail is asked once a day
        self.assertNotIn("📬", card.tick(self.session(at(23, 10))).text)
        self.assertEqual(len(self.fake.mail_reads), reads)
        self.assertIn("📬 New bill in Gmail: CITYPOWER bill ₹450 due 10 Dec", self.morning(at(24, 7, 30)))
        self.assertEqual(len(self.fake.mail_reads), reads + 1)  # each mail is read once

        three_before = self.session(at(6, 9, month=12))
        self.assertIn("💳 Example Bank Rewards card ₹123,456.78 due in 3 days (9 Dec)", "\n".join(bills.reminders(three_before)))
        three_before.save()
        listing = self.cmd(chat.BILLS, "show", at(6, 9, 5, month=12))
        self.assertIn("1. 📬 Example Bank Rewards card ₹123,456.78 — due 9 Dec · ⏳ due in 3d", listing)
        self.assertIn("✅ Example Bank Rewards card paid (on time) +15", self.cmd(chat.BILLS, "paid 1", at(6, 9, 6, month=12)))
        self.assertEqual(self.fake.open_titles("Bills"), ["💳 Pay CITYPOWER bill ₹450"])
        self.assertNotIn("Example Bank", self.cmd(chat.BILLS, "show", at(6, 9, 7, month=12)))

    def test_a_bill_is_not_lost_when_to_do_fails_it_is_added_the_next_morning(self):
        self.mail(*POWER)
        self.fake.todo_add_fails = True
        self.assertIn("⚠️ bills from Gmail", self.morning(at(23, 7, 30)))
        self.fake.todo_add_fails = False
        self.assertIn("📬 New bill in Gmail: CITYPOWER bill ₹450", self.morning(at(24, 7, 30)))
        self.assertEqual(self.fake.open_titles("Bills"), ["💳 Pay CITYPOWER bill ₹450"])

class GoalsReview(Base):
    def test_goals_come_weekly_with_the_sunday_wrap_up_not_on_the_daily_card(self):
        self.cmd(chat.GOALS, "add work Sign 3 hospitals by 31 dec", at(23, 9))
        self.assertNotIn("Sign 3 hospitals", card.morning(self.session(at(24, 7, 30))).text)
        self.assertNotIn("goals review", card.tick(self.session(at(28, 21, 30))).text)  # Saturday
        sunday = self.session(at(29, 21, 30))
        text = card.tick(sunday).text
        sunday.save()
        self.assertIn("🎯 **Weekly goals review**", text)
        self.assertIn("1. Sign 3 hospitals — ", text)
        self.assertNotIn("goals review", card.tick(self.session(at(29, 21, 45))).text)


class Badge(Base):
    def test_badge_follows_replies_but_not_help(self):
        self.assertEqual(game.badge(self.dir), "")
        self.fake.add("Task", date(2026, 11, 23))
        with mock.patch("orchestrator.myday.chat.Session", lambda d: self.session(at(23, 8))):
            reply = commands.dispatch("day", "now")
        self.assertTrue(reply.endswith("🧊 0 · Lv 1 Starter · 0 pts"), reply)
        self.assertEqual(commands.dispatch("day", "help"), chat.DAY_HELP)

    def test_plugin_adds_the_badge_to_telegram_replies_only(self):
        sys.path.insert(0, str(ROOT / "orchestrator"))
        import plugin

        game.State.load(self.dir).save()
        self.assertTrue(plugin.on_llm_output(response_text="Hi", platform="telegram").endswith("🧊 0 · Lv 1 Starter · 0 pts"))
        self.assertIsNone(plugin.on_llm_output(response_text="Hi", platform="cli"))


if __name__ == "__main__":
    unittest.main()
