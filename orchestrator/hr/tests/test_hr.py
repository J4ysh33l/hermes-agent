"""Payslips against a generated Word template, real LibreOffice, and a fake Microsoft Graph.

Run: python3 orchestrator/hr/tests/test_hr.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import docx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator/brief/tests"))

from fakes import FakeHttp, query

from hermes_platform.resolver import locate_command
from orchestrator.hr import chat, docfill, inbox, payroll
from orchestrator.hr.settings import Settings

NOW = 1_795_000_000.0
GRAPH = "https://graph.microsoft.com/v1.0"
HEADER = "Employee Name,Position,Employment Type,DOJ,IFSC Code,Bank Account,Compensation,Basic,HRA,LOP Days,Email\n"
GOOD = HEADER + ("Asha Verma,Implementation Manager,IN,17/08/2026,TEST0000001,11112222333,20000,15000,5000,2,"
                 "asha@example.com\n"
                 "Rohan Kumar Das,Data Analyst ,IN,1/6/2026,TEST0000002,44445555666,25000,20000,5000,,"
                 "rohan@example.com\n"
                 "Kabir,0,C,21/08/2026,0,0,0,0,0,,\n")
NOV = payroll.Period(date(2026, 11, 1), date(2026, 11, 30), date(2026, 12, 2))
HAS_SOFFICE = locate_command("soffice").found


def template(path: Path) -> None:
    """A small payslip with one placeholder split over three runs, the way Word saves them."""
    d = docx.Document()
    d.add_paragraph("Payslip for {{month}}")
    split = d.add_paragraph()
    for part in ("Net: {{ne", "t_p", "ay}}"):
        split.add_run(part)
    table = d.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "{{name}} ({{designation}})"
    table.cell(0, 1).text = "LOP {{lop_days}} = {{lop_amount}}"
    d.save(str(path))


class Rules(unittest.TestCase):
    def rows(self, text: str) -> list[dict[str, str]]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.csv"
            path.write_text(text, encoding="utf-8")
            from orchestrator.hr import sheet

            return sheet.read(path)[0]

    def test_lop_is_per_working_day_with_sundays_off(self):
        self.assertEqual(payroll.working_days(NOV, Settings()), 25)
        batch = payroll.build(self.rows(GOOD), NOV, Settings())
        asha = batch.slips[0]
        self.assertEqual((asha.lop_amount, asha.net, asha.paid_days), (1600, 18400, 23))
        self.assertEqual(batch.skipped, ("Row 4 (Kabir): compensation is 0, no slip",))

    def test_without_an_hra_column_hra_is_the_rest_of_compensation(self):
        rows = self.rows("Employee Name,Position,Email,DOJ,Compensation,Basic\n"
                         "Asha,SWE,asha@example.com,1/1/2026,20000,15000\n"
                         "Ravi,SWE,ravi@example.com,1/1/2026,20000,25000\n")
        batch = payroll.build(rows, NOV, Settings())
        self.assertEqual((batch.slips[0].basic, batch.slips[0].hra, batch.slips[0].gross), (15000, 5000, 20000))
        self.assertIn("Row 3 (Ravi): Basic 25000 must be between 0 and Compensation (20000)", batch.problems)

    def test_every_bad_row_is_listed_and_stops_the_run(self):
        bad = HEADER + ("Meera,0,C,17/08/2026,0,0,17000,12000,5000,,\n"
                        "Ravi,SWE,FT,1/1/2026,0,0,30000,20000,5000,,ravi@example.com\n"
                        "Dup,SWE,FT,1/1/2026,0,0,10000,10000,0,,ravi@example.com\n")
        batch = payroll.build(self.rows(bad), NOV, Settings())
        text = " ".join(batch.problems)
        self.assertIn("Meera): designation is missing", text)
        self.assertIn("Meera): email is missing", text)
        self.assertIn("Basic + HRA (25000) is not Compensation (30000)", text)
        self.assertNotIn("is on two rows", text, "the bad Ravi row is already stopped")

    def test_split_placeholders_are_filled_and_a_missing_value_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "t.docx", Path(tmp) / "o.docx"
            template(src)
            values = {"month": "November 2026", "net_pay": "₹18,400", "name": "Asha", "designation": "PM",
                      "lop_days": "2", "lop_amount": "₹1,600"}
            docfill.fill(src, values, out)
            text = "\n".join(p.text for p in docx.Document(str(out)).paragraphs)
            self.assertIn("Net: ₹18,400", text)
            with self.assertRaisesRegex(docfill.TemplateError, "net_pay"):
                docfill.fill(src, {k: v for k, v in values.items() if k != "net_pay"}, out)


@unittest.skipUnless(HAS_SOFFICE, "LibreOffice is not installed")
class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.state = home / "brief"
        (self.state / "tokens").mkdir(parents=True)
        (home / "hr/templates").mkdir(parents=True)
        template(home / "hr/templates/payslip.docx")
        (home / ".env").write_text("MS_CLIENT_ID=ms\nMS_TENANT_ID=t\n", encoding="utf-8")
        (self.state / "tokens/microsoft.json").write_text('{"refresh_token": "r0"}', encoding="utf-8")
        self.sheet = home / "nov.csv"
        self.sheet.write_text(GOOD, encoding="utf-8")
        self.mails: list[dict] = []
        self.http = FakeHttp()
        self.http.on("POST", "https://login.microsoftonline.com/t/oauth2/v2.0/token",
                     {"access_token": "a", "refresh_token": "r1"})
        self.http.on("GET", GRAPH + "/me", {"mail": "jay@co.com"})
        self.http.on("POST", GRAPH + "/me/sendMail", lambda c: self.mails.append(c.json_body["message"]) or {})
        self.home = home

    def tearDown(self):
        self.tmp.cleanup()

    def hr(self, words: str, at: float = NOW) -> str:
        return chat.handle(words, self.state, self.http, at)

    def test_prepare_makes_pdfs_and_its_reply_carries_no_pay(self):
        reply = self.hr(f"payslip {self.sheet} 01/11/2026 30/11/2026 02/12/2026")
        self.assertIn("2 payslips for November 2026 are ready", reply)
        self.assertNotIn("₹", reply, "the agent's model must not see salary figures")
        self.assertNotIn("18400", reply.replace(",", ""))
        self.assertEqual(len(list((self.home / "hr/payslips/2026-11").glob("*.pdf"))), 2)
        self.assertIn("₹18,400", self.hr("payslip show"))
        self.assertEqual(self.mails, [])

    def test_test_mails_only_you_and_yes_mails_each_person_their_own_slip(self):
        self.hr(f"payslip {self.sheet} 01/11/2026 30/11/2026 02/12/2026")
        self.hr("payslip test")
        self.assertEqual({m["toRecipients"][0]["emailAddress"]["address"] for m in self.mails}, {"jay@co.com"})
        self.mails.clear()
        self.assertIn("Emailed 2 of 2", self.hr("payslip yes"))
        sent = {m["toRecipients"][0]["emailAddress"]["address"]: m["attachments"][0] for m in self.mails}
        self.assertEqual(sent["asha@example.com"]["name"], "Payslip_Nov-2026_Asha_Verma.pdf")
        self.assertTrue(base64.b64decode(sent["asha@example.com"]["contentBytes"]).startswith(b"%PDF"))
        log = (self.home / "hr/sent.jsonl").read_text()
        self.assertNotIn("18400", log.replace(",", ""))
        self.assertNotIn("11112222333", log, "bank details are never copied")
        self.assertIn("No payslips are waiting", self.hr("payslip yes"))

    def test_slips_go_out_from_the_hr_mailbox(self):
        (self.state / "brief.yaml").write_text("hr:\n  mailbox: hr@co.com\n", encoding="utf-8")
        self.hr(f"payslip {self.sheet} 01/11/2026 30/11/2026 02/12/2026")
        self.assertIn("from hr@co.com to jay@co.com", self.hr("payslip test"))
        self.hr("payslip yes")
        self.assertEqual({m["from"]["emailAddress"]["address"] for m in self.mails}, {"hr@co.com"})
        self.assertEqual(len(self.mails), 4)

    def test_a_batch_expires(self):
        self.hr(f"payslip {self.sheet} 01/11/2026 30/11/2026 02/12/2026")
        self.assertIn("No payslips are waiting", self.hr("payslip yes", at=NOW + 3 * 3600))
        self.assertEqual(self.mails, [])

    def test_a_bad_sheet_makes_nothing(self):
        self.sheet.write_text(HEADER + "Meera,0,C,17/08/2026,0,0,17000,12000,5000,,\n", encoding="utf-8")
        reply = self.hr(f"payslip {self.sheet} 01/11/2026 30/11/2026 02/12/2026")
        self.assertIn("Nothing was made", reply)
        self.assertFalse((self.home / "hr/payslips").exists())
        self.assertFalse((self.home / "hr/pending.json").exists())

    def with_bad_rows(self) -> None:
        self.sheet.write_text(GOOD + "Meera,0,C,17/08/2026,0,0,17000,12000,5000,,0\n"
                              "Dup One,SWE,IN,1/1/2026,T1,1,30000,25000,5000,,asha@example.com\n", encoding="utf-8")

    def test_skip_makes_only_the_good_rows_and_keeps_the_left_out_names_in_view(self):
        self.with_bad_rows()
        reply = self.hr(f"payslip {self.sheet} 01/11/2026 30/11/2026 02/12/2026")
        self.assertIn("Nothing was made", reply)
        self.assertIn("Row 5 (Meera): designation is missing; email is missing", reply, "one line per employee")
        self.assertIn("Leave out 3 (Meera, Asha Verma, Dup One) and make the other 1 slips? /hr payslip skip", reply)
        self.assertFalse((self.home / "hr/payslips").exists())
        reply = self.hr("payslip skip")
        self.assertIn("1 payslips for November 2026 are ready", reply)
        self.assertEqual([p.name for p in (self.home / "hr/payslips/2026-11").glob("*.pdf")],
                         ["Payslip_Nov-2026_Rohan_Kumar_Das.pdf"], "a shared email leaves out both rows")
        self.assertIn("Left out, no slip until fixed (3):", self.hr("payslip show"))
        self.assertIn("Nothing to skip", self.hr("payslip skip"))

    def test_skip_after_the_sheet_changed_makes_nothing_and_offers_the_new_list(self):
        self.with_bad_rows()
        self.hr(f"payslip {self.sheet} 01/11/2026 30/11/2026 02/12/2026")
        self.sheet.write_text(GOOD.replace("Data Analyst ", "0"), encoding="utf-8")
        reply = self.hr("payslip skip")
        self.assertIn("The sheet changed since you said skip", reply)
        self.assertIn("Leave out 1 (Rohan Kumar Das) and make the other 1 slips? /hr payslip skip", reply)
        self.assertFalse((self.home / "hr/pending.json").exists())

    def test_a_missing_column_is_never_offered_as_skippable(self):
        self.sheet.write_text(GOOD.replace(",Email\n", ",Mailbox\n"), encoding="utf-8")
        reply = self.hr(f"payslip {self.sheet} 01/11/2026 30/11/2026 02/12/2026")
        self.assertIn("Add these columns: Email", reply)
        self.assertNotIn("skip", reply)
        self.assertIn("Nothing to skip", self.hr("payslip skip"))

    def test_the_agent_entry_only_makes_slips_and_cannot_skip_or_send(self):
        self.with_bad_rows()
        self.hr(f"payslip {self.sheet} 01/11/2026 30/11/2026 02/12/2026")
        for words in (["skip"], ["yes"], ["test"], ["skip", "a", "b", "c"]):
            chat.agent_make(words, self.state)
        self.assertFalse((self.home / "hr/payslips").exists(), "the agent could not take up the skip offer")
        self.assertEqual(self.mails, [])

    def test_a_pasted_table_with_a_month_name_makes_slips_and_hra_defaults_to_the_rest(self):
        table = ("Employee Name\tPosition\tEmail\tDOJ\tCompensation\tBasic\n"
                 "Asha Verma\tDirector, Operations\tasha@example.com\t17/08/2026\t20000\t15000\n")
        reply = self.hr("payslip Nov 02/12/2026\n" + table)
        self.assertIn("1 payslips for November 2026 are ready", reply)
        pasted = list((self.home / "hr/inbox").glob("pasted-*.tsv"))
        self.assertEqual(len(pasted), 1)
        self.assertEqual(oct(pasted[0].stat().st_mode & 0o777), "0o600", "salary data stays private")
        self.hr("payslip Nov 02/12/2026\n" + table)
        self.assertEqual(len(list((self.home / "hr/inbox").glob("pasted-*.tsv"))), 1, "only the latest paste is kept")

    def test_a_paste_that_lost_its_tabs_or_a_bad_month_is_refused_with_what_to_send(self):
        self.assertIn("lost its columns", self.hr("payslip November 02/12/2026\nAsha Verma SWE asha@example.com"))
        self.assertIn("'Novembr' is not a month", self.hr("payslip Novembr 02/12/2026\nA\tB"))
        self.assertIn("Put the month and pay date on the first line", self.hr("payslip\nA\tB"))
        self.assertIn("Add the pay date", self.hr("payslip November\nA\tB"))
        self.assertFalse((self.home / "hr/payslips").exists())

    def test_hr_is_a_menu_and_payslip_steps_live_under_it(self):
        self.assertIn("/hr payslip", self.hr("show"))
        self.assertNotIn("No payslips are waiting", self.hr("show"))
        self.assertIn("No payslips are waiting", self.hr("payslip show"))
        self.assertIn("/hr payslip check", self.hr("payslip help"))

    def test_check_lists_missing_columns_and_every_row_problem_in_one_pass(self):
        self.sheet.write_text("Employee Name,Position,DOJ,IFSC Code,Bank Account,Compensation,LOP Days\n"
                              "Meera,0,17/08/2026,0,0,17000,\n"
                              "Ravi,SWE,1/1/2026,TEST0000003,123,30000,abc\n"
                              "Kabir,SWE,1/1/2026,TEST0000004,456,0,\n", encoding="utf-8")
        reply = self.hr(f"payslip check {self.sheet} 01/11/2026 30/11/2026")
        self.assertIn("Add these columns: Email, Basic\n", reply)
        self.assertIn("Meera): designation is missing", reply)
        self.assertIn("Ravi): LOP Days 'abc' is not a number", reply)
        self.assertIn("Meera): bank details are blank or 0", reply)
        self.assertIn("Kabir): compensation is 0", reply)
        self.assertNotIn("email is missing", reply, "a missing column is named once, not on every row")
        self.assertFalse((self.home / "hr/payslips").exists())

    def test_common_header_names_are_accepted_and_a_0_email_is_one_problem(self):
        self.sheet.write_text("Employee Name,Position,Email,DOJ,Compensation,Basic Pay,HRA,LOP Days\n"
                              "Asha,SWE,asha@example.com,1/1/2026,30000,25000,5000,0\n"
                              "Ravi,SWE,0,1/1/2026,30000,25000,5000,0\n", encoding="utf-8")
        reply = self.hr(f"payslip check {self.sheet} 01/11/2026 30/11/2026")
        self.assertNotIn("Add these columns", reply)
        self.assertIn("Ravi): email is missing", reply)
        self.assertNotIn("is not an email address", reply)

    def test_check_passes_a_good_sheet_and_still_makes_nothing(self):
        self.assertIn("The sheet is ready: 2 payslips", self.hr(f"payslip check {self.sheet} 01/11/2026 30/11/2026"))
        self.assertFalse((self.home / "hr/pending.json").exists())


INTERVIEWS = """Date: 19/11/2026
Panel: rishabh@co.com, nidhi@co.com
Rohan Das, Data Analyst, 11:45, 12:15, rohan@example.com
Asha Verma, Director, Operations, 11:00, 11:30, Asha@example.com"""


class Interviews(unittest.TestCase):
    """NOW is Wed 18 Nov 2026, 16:36 IST; the interviews are the next day."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.state = home / "brief"
        (self.state / "tokens").mkdir(parents=True)
        (home / ".env").write_text("MS_CLIENT_ID=ms\nMS_TENANT_ID=t\n", encoding="utf-8")
        (self.state / "tokens/microsoft.json").write_text('{"refresh_token": "r0"}', encoding="utf-8")
        self.events: list[dict] = []
        self.busy: list[dict] = []
        self.http = FakeHttp()
        self.http.on("POST", "https://login.microsoftonline.com/t/oauth2/v2.0/token",
                     {"access_token": "a", "refresh_token": "r1"})
        self.http.on("GET", GRAPH + "/me/calendarView", lambda _c: {"value": self.busy})
        self.http.on("POST", GRAPH + "/me/events", self._event)
        self.mails: list[dict] = []
        self.http.on("POST", GRAPH + "/me/sendMail", lambda c: self.mails.append(c.json_body["message"]) or {})
        (self.state / "brief.yaml").write_text("hr: {}\n", encoding="utf-8")  # no hr.mailbox
        self.home = home

    def tearDown(self):
        self.tmp.cleanup()

    def _event(self, call):
        self.events.append(call.json_body)
        teams = call.json_body.get("isOnlineMeeting")
        return {"id": f"E{len(self.events)}", "onlineMeeting": {"joinUrl": "https://teams.example/j/1"} if teams else None}

    def hr(self, words: str) -> str:
        return chat.handle(words, self.state, self.http, NOW)

    def test_one_link_and_each_candidate_gets_only_their_own_slot(self):
        preview = self.hr("interview\n" + INTERVIEWS)
        self.assertIn("1. 11:00–11:30 Asha Verma, Director, Operations, asha@example.com", preview,
                      "sorted by time; a position may contain commas")
        self.assertIn("Nothing is sent yet", preview)
        self.assertEqual(self.events, [])
        self.assertIn("Invited 2 of 2", self.hr("interview yes"))
        panel, *candidates = self.events
        self.assertTrue(panel["isOnlineMeeting"])
        self.assertEqual([a["emailAddress"]["address"] for a in panel["attendees"]], ["rishabh@co.com", "nidhi@co.com"])
        self.assertIn("11:45–12:15 Rohan Das", panel["body"]["content"])
        self.assertEqual(panel["start"]["dateTime"], "2026-11-19T05:30:00", "the block starts at the first slot (UTC)")
        self.assertEqual(panel["end"]["dateTime"], "2026-11-19T06:45:00")
        for event, email, start in zip(candidates, ["asha@example.com", "rohan@example.com"], ["05:30", "06:15"]):
            self.assertEqual([a["emailAddress"]["address"] for a in event["attendees"]], [email], "no one else's email")
            self.assertNotIn("isOnlineMeeting", event, "a candidate's event makes no second link")
            self.assertIn("https://teams.example/j/1", event["body"]["content"])
            self.assertEqual(event["start"]["dateTime"], f"2026-11-19T{start}:00")
        self.assertNotIn("Rohan", candidates[0]["body"]["content"])
        self.assertIn("No interviews are waiting", self.hr("interview yes"), "a second yes invites nobody")

    def test_with_an_hr_mailbox_the_slot_stays_yours_and_the_candidate_is_mailed_from_it(self):
        (self.state / "brief.yaml").write_text("hr:\n  mailbox: hr@co.com\n", encoding="utf-8")
        self.hr("interview\n" + INTERVIEWS)
        self.assertIn("Invited 2 of 2 candidates to their slot, by mail from hr@co.com", self.hr("interview yes"))
        panel, *slots = self.events
        self.assertEqual(len(panel["attendees"]), 2, "the panel meeting is still yours, with the panel invited")
        self.assertEqual([s["attendees"] for s in slots], [[], []], "your calendar sends the candidates nothing")
        self.assertEqual([m["from"]["emailAddress"]["address"] for m in self.mails], ["hr@co.com"] * 2)
        asha = self.mails[0]
        self.assertEqual([r["emailAddress"]["address"] for r in asha["toRecipients"]], ["asha@example.com"])
        self.assertIn("https://teams.example/j/1", asha["body"]["content"])
        self.assertNotIn("Rohan", asha["body"]["content"])
        cal = asha["attachments"][0]
        self.assertEqual((cal["name"], cal["contentType"]), ("interview.ics", "text/calendar"))
        ics = base64.b64decode(cal["contentBytes"]).decode()
        self.assertIn("DTSTART:20261119T053000Z\r\nDTEND:20261119T060000Z", ics)
        self.assertNotIn("ORGANIZER", ics, "no RSVP goes anywhere")
        self.assertTrue(all(len(line.encode()) <= 75 for line in ics.split("\r\n")))

    def test_overlaps_past_times_and_bad_rows_are_all_listed_and_nothing_is_saved(self):
        reply = self.hr("interview Date: 19/11/2026; Asha, SWE, 11:00, 11:30, asha@example.com;"
                        " Ravi, SWE, 11:15, 11:45, ravi@example.com; Meera, SWE, 25:00, 11:00, meera;"
                        " Kabir, SWE, 11:00")
        self.assertIn("Asha (11:00–11:30) overlaps Ravi (11:15–11:45)", reply)
        self.assertIn("Meera): start '25:00' is not a time", reply)
        self.assertIn("Meera): 'meera' is not an email address", reply)
        self.assertIn("Line 5: needs Name, Position, Start, End, Email", reply)
        self.assertIn("Nothing was saved", self.hr("interview Date: 18/11/2026; Asha, SWE, 09:00, 09:30, a@example.com"))
        self.assertIn("Add a line 'Date: dd/mm/yyyy'", self.hr("interview Asha, SWE, 11:00, 11:30, a@example.com"))
        self.assertIn("No interviews are waiting", self.hr("interview show"))

    def test_a_pasted_table_with_a_date_column_and_no_end_uses_the_default_length(self):
        table = ("Panel: rishabh@co.com\n"
                 "Name\tPosition\tEmail\tDate\tStart\n"
                 "Asha Verma\tDirector, Operations\tasha@example.com\t19/11/2026\t11:00\n"
                 "Rohan Das\tData Analyst\trohan@example.com\t19/11/2026\t11:30\n")
        preview = self.hr("interview\n" + table)
        self.assertIn("1. 11:00–11:30 Asha Verma, Director, Operations, asha@example.com", preview)
        self.assertIn("2. 11:30–12:00 Rohan Das", preview)
        self.assertIn("Panel: rishabh@co.com", preview)

    def test_a_comma_line_without_an_end_and_a_two_day_table_are_handled(self):
        self.assertIn("1. 11:00–11:30 Asha, SWE", self.hr("interview Date: 19/11/2026; Asha, SWE, 11:00, asha@example.com"))
        reply = self.hr("interview\nName\tPosition\tEmail\tDate\tStart\n"
                        "Asha\tSWE\tasha@example.com\t19/11/2026\t11:00\n"
                        "Ravi\tSWE\travi@example.com\t20/11/2026\t11:00\n")
        self.assertIn("One day per batch (one Teams link): found 19/11, 20/11", reply)

    def test_your_busy_time_is_a_warning_and_no_cancels(self):
        self.busy = [{"start": {"dateTime": "2026-11-19T05:45:00.0000000"}, "end": {"dateTime": "2026-11-19T06:00:00.0000000"},
                      "showAs": "busy"}]
        self.assertIn("⚠️ Asha Verma 11:00–11:30: you have something else then", self.hr("interview\n" + INTERVIEWS))
        self.assertIn("Nobody was invited", self.hr("interview no"))
        self.assertEqual(self.events, [])


class InboxRules(unittest.TestCase):
    def test_first_matching_rule_sorts_each_mail(self):
        cases = {
            ("Urgent: Pending Salary and Full & Final Settlement", "x@gmail.com"): "urgent",
            ("Case status update", "noreply@court.nic.in"): "urgent",
            ("Re: FORMAL LEGAL NOTICE & STATUTORY DEMAND", "someone@co.com"): "urgent",
            ("Formal resignation", "dev@co.com"): "people",
            ("Request for Internship Completion and Experience Certificate", "x@gmail.com"): "people",
            ("Lunch plan", "ops@co.com"): "people",  # anyone at your domain
            ("Campus Hiring Invitation – 2027 Graduating Batch", "tpo@college.ac.in"): "campus",
            ("Application for Backend Developer at Medoc Health", "x@gmail.com"): "applications",
            ("Exploring AI engineering opportunities", "x@iiit.ac.in"): "applications",
            ("Undangan Webinar: Will AI Replace HR?", "news@vendor.com"): "other",
        }
        for (subject, sender), want in cases.items():
            with self.subTest(subject=subject):
                self.assertEqual(inbox.classify(subject, sender, "co.com"), want)


class InboxSweep(unittest.TestCase):
    """/hr inbox against a fake Outlook: one search per sweep, thread lookups for waiting mail."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.state = home / "brief"
        (self.state / "tokens").mkdir(parents=True)
        (home / ".env").write_text("MS_CLIENT_ID=ms\nMS_TENANT_ID=t\n", encoding="utf-8")
        (self.state / "tokens/microsoft.json").write_text('{"refresh_token": "r0"}', encoding="utf-8")
        (self.state / "brief.yaml").write_text("hr:\n  mailbox: hr@co.com\n", encoding="utf-8")
        self.mails: list[dict] = []
        self.http = FakeHttp()
        self.http.on("POST", "https://login.microsoftonline.com/t/oauth2/v2.0/token",
                     {"access_token": "a", "refresh_token": "r1"})
        self.http.on("GET", GRAPH + "/me/mailFolders/sentitems", {"id": "SENT"})
        self.http.on("GET", GRAPH + "/me/messages", self._messages)
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def _messages(self, call):
        q = query(call)
        if "$filter" in q:
            conv = q["$filter"][0].split("'")[1]
            return {"value": [m for m in self.mails if m["conversationId"] == conv]}
        return {"value": [m for m in self.mails if m["to_hr"]]}

    def mail(self, subject: str, sender: str, when: str, *, conv: str = "", to_hr: bool = True,
             folder: str = "INBOX") -> None:
        self.n += 1
        self.mails.append({"id": f"m{self.n}", "subject": subject, "receivedDateTime": when + "Z",
                           "from": {"emailAddress": {"name": sender.split("@")[0], "address": sender}},
                           "conversationId": conv or f"c{self.n}", "webLink": "", "parentFolderId": folder,
                           "to_hr": to_hr})

    def hr(self, words: str, at: float = NOW) -> str:
        return chat.handle(words, self.state, self.http, at)

    def test_sorted_and_waiting_mail_clears_only_when_someone_else_answers(self):
        self.mail("Formal resignation", "dev@co.com", "2026-11-18T05:00:00", conv="R")
        self.mail("Pending salary dues", "ex@gmail.com", "2026-11-18T06:00:00", conv="S")
        self.mail("Application for SDE role", "a@gmail.com", "2026-11-19T06:00:00")
        self.mail("Campus placement drive", "tpo@uni.ac.in", "2026-11-19T07:00:00")
        self.mail("Re: Formal resignation", "boss@co.com", "2026-11-18T05:30:00", conv="R")  # a colleague's reply
        self.mail("Cc to HR from me", "me@co.com", "2026-11-19T08:00:00", folder="SENT")  # your own sent mail
        shown = self.hr("inbox show")
        self.assertIn("📥 **HR inbox** — 5 new", shown)
        self.assertIn("🚨 Urgent 1 · 👥 People 2 · 🎓 Campus 1 · 📄 Applications 1", shown)
        self.assertNotIn("Cc to HR from me", shown)
        self.assertIn("**Waiting for a reply (1)**\n1. 🚨 ex — Pending salary dues", shown)  # resignation answered

        self.mail("Re: Pending salary dues", "ex@gmail.com", "2026-11-19T09:00:00", conv="S", to_hr=False)
        self.assertIn("Waiting for a reply (1)", self.hr("inbox show"))  # the sender's own follow-up
        self.mail("Re: Pending salary dues", "hr@co.com", "2026-11-19T10:00:00", conv="S", to_hr=False)
        self.assertIn("1 answered", self.hr("inbox show"))

    def test_quiet_sweep_says_nothing_but_reminds_of_urgent_mail_once_a_day(self):
        self.mail("Legal notice", "lawyer@firm.com", "2026-11-18T05:00:00")
        self.assertIn("Legal notice", self.hr("inbox sweep", NOW))
        self.assertEqual(self.hr("inbox sweep", NOW + 7 * 3600), "")  # same day, nothing new
        next_day = self.hr("inbox sweep", NOW + 24 * 3600)
        self.assertIn("1. 🚨 lawyer — Legal notice", next_day)
        self.assertIn("✅ Handled: Legal notice", self.hr("inbox done 1", NOW + 24 * 3600))
        self.assertEqual(self.hr("inbox sweep", NOW + 48 * 3600), "")
        self.assertIn("Legal notice ✓", self.hr("inbox list urgent", NOW + 48 * 3600))
        self.assertEqual(self.http.count(GRAPH + "/me/mailFolders/sentitems"), 1)  # asked once, then kept

    def test_without_a_mailbox_it_says_what_to_set(self):
        (self.state / "brief.yaml").write_text("hr: {}\n", encoding="utf-8")
        self.assertIn("Set hr.mailbox", self.hr("inbox show"))


if __name__ == "__main__":
    unittest.main()
