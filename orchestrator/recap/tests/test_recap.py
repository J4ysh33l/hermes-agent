"""The deadline recap against a fake To Do, calendar and the other workflows' files (no network, no model).

Run: python3 orchestrator/recap/tests/test_recap.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator/myday/tests"))

from test_myday import FakeMicrosoft, at

from orchestrator.myday.session import Session
from orchestrator.outreach import plan
from orchestrator.recap import cli

MON_8PM = at(23, 20)  # Mon 23 Nov 2026, 20:00 IST


class Recap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / ".env").write_text("MS_CLIENT_ID=c\nMS_TENANT_ID=t\n", encoding="utf-8")
        (self.home / "brief/tokens").mkdir(parents=True)
        (self.home / "brief/tokens/microsoft.json").write_text('{"refresh_token": "RT"}', encoding="utf-8")
        (self.home / "hr").mkdir()
        (self.home / "brief/outreach").mkdir()
        self.fake = FakeMicrosoft()

    def tearDown(self):
        self.tmp.cleanup()

    def recap(self, now: float = MON_8PM) -> str:
        return cli.recap(Session(self.home / "myday", self.fake, now), self.home)

    def pending(self, path: str, created: float) -> None:
        (self.home / path).write_text(json.dumps({"created": created}), encoding="utf-8")

    def test_one_message_waiting_first_then_overdue_then_coming_up(self):
        self.pending("hr/pending.json", MON_8PM - 10 * 60)  # payslips: 120 min to approve
        self.pending("brief/outreach/pending-slack.json", at(23, 15))  # 30 min: missed today
        self.pending("brief/outreach/pending-meet.expired.json", at(21, 15))  # expired days ago: still reminded
        (self.home / "hr/inbox.json").write_text(json.dumps({"items": {
            "m1": {"cat": "people", "subject": "Formal resignation", "name": "Dev", "from": "dev@co.com",
                   "received": "2026-11-18T05:00:00", "conv": "c1"},
            "m2": {"cat": "urgent", "subject": "Legal notice", "name": "Firm", "from": "x@firm.com",
                   "received": "2026-11-20T05:00:00", "conv": "c2"},
            "m3": {"cat": "applications", "subject": "Application", "name": "A", "from": "a@x.com",
                   "received": "2026-11-20T05:00:00", "conv": "c3"}}}), encoding="utf-8")
        self.fake.add("Send deck", date(2026, 11, 20))
        self.fake.add("Call Apollo", date(2026, 11, 25))
        self.fake.add("Far away", date(2026, 11, 28))  # beyond 3 days
        self.fake.events = [
            {"subject": "Grant submission deadline", "start": {"dateTime": "2026-11-27T17:30:00"}, "isAllDay": False},
            {"subject": "Team lunch", "start": {"dateTime": "2026-11-24T13:00:00"}, "isAllDay": False}]
        text = self.recap()
        self.assertTrue(text.startswith("⏰ **Deadline recap** — Mon 23 Nov"), text)
        waiting = text.index("**Waiting on you**")
        self.assertLess(waiting, text.index("**Overdue**"))
        self.assertLess(text.index("**Overdue**"), text.index("**Coming up**"))
        self.assertIn("✍️ Payslip batch: waiting for your yes until 21:50 · /hr payslip show", text)
        self.assertIn("⌛ Slack messages: expired 23 Nov 15:30 without your yes · make it again, or /slack no "
                      "to drop it", text)
        self.assertIn("⌛ Meetings: expired 21 Nov 15:30", text)
        self.assertLess(text.index("Legal notice"), text.index("Formal resignation"))  # urgent first
        self.assertNotIn("Application", text)  # counts-only mail never waits
        self.assertIn("▫️ Send deck — 3d overdue", text)
        self.assertIn("▫️ Call Apollo — Wed", text)
        self.assertNotIn("Far away", text)
        self.assertIn("🗓 Grant submission deadline — Fri 17:30", text)
        self.assertNotIn("Team lunch", text)

    def test_an_expired_plan_is_reminded_until_made_again_or_dropped(self):
        store = plan.Store(self.home / "brief")
        draft = plan.Plan("slack", "Slack", (plan.Line("Priya — hi", ()),), at(23, 10))
        store.save(draft)
        self.assertIsNone(store.waiting("slack", at(23, 11), 30))  # expired unapproved
        self.assertIn("⌛ Slack messages: expired 23 Nov 10:30", self.recap())
        self.assertIn("⌛ Slack messages: expired 23 Nov 10:30", self.recap(at(25, 20)))  # days later too
        store.save(plan.Plan("slack", "Slack", draft.lines, at(25, 19, 50)))  # made again
        again = self.recap(at(25, 20))
        self.assertNotIn("expired", again)
        self.assertIn("✍️ Slack messages: waiting for your yes until 20:20", again)
        store.waiting("slack", at(25, 21), 30)
        self.assertTrue(store.forget_expired("slack"))  # what /slack no does when nothing is live
        self.assertEqual(self.recap(at(25, 21)), "")

    def test_nothing_waiting_sends_nothing(self):
        self.assertEqual(self.recap(), "")

    def test_a_part_that_fails_is_named_and_the_rest_still_arrives(self):
        self.fake.add("Send deck", date(2026, 11, 20))
        self.fake.calendar_fails = True
        text = self.recap()
        self.assertIn("▫️ Send deck", text)
        self.assertIn("⚠️ calendar: HTTP 500", text)


if __name__ == "__main__":
    unittest.main()
