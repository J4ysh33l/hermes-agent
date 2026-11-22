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

from fakes import FakeHttp

from hermes_platform.resolver import locate_command
from orchestrator.hr import chat, docfill, payroll
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
        self.assertIn("Add these columns: Email, Basic, HRA", reply)
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


if __name__ == "__main__":
    unittest.main()
