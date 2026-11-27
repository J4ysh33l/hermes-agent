"""/hr reply and /hr list against a fake Outlook and a fake Gemini.

The promises tested: Gemini never sees a real name, email, phone number, amount or ID; a draft whose
placeholders come back changed is fixed, one with an invented placeholder or number is refused and
asked again; the greeting and sign-off are the script's; templates use no model; a reply goes out
once, in its thread, From the HR mailbox.

Run: python3 orchestrator/hr/tests/test_reply.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator/brief/tests"))

from fakes import FakeHttp

from orchestrator.hr import chat, redact

NOW = 1_795_000_000.0  # 2026-11-19 ~13:46 UTC
GRAPH = "https://graph.microsoft.com/v1.0"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/"
SECRET_BITS = ("Asha", "Verma", "asha.v@gmail.com", "98765 43210", "45,000", "ABCDE1234F", "001234567890",
               "Kiran")
BODY = ("Hello HR,\nMy salary of Rs. 45,000 for October is still pending. PAN ABCDE1234F, account "
        "001234567890. Please call me on +91 98765 43210 or write to asha.v@gmail.com. My manager Kiran "
        "Rao knows.\nRegards,\nAsha Verma")


class Redaction(unittest.TestCase):
    def test_every_kind_is_hidden_and_the_same_value_gets_the_same_placeholder(self):
        (subject, body), table = redact.hide(["Pending salary — Asha Verma", BODY], ["Asha Verma", "Kiran Rao"])
        for bit in SECRET_BITS:
            self.assertNotIn(bit, subject + body)
        self.assertEqual(table["[NAME_1]"], "Asha Verma")
        self.assertEqual(body.count("[NAME_1]"), 1)  # the signed name reuses the subject's placeholder
        self.assertIn("[AMOUNT_1]", body)
        self.assertEqual(set(table.values()) >= {"asha.v@gmail.com", "+91 98765 43210", "ABCDE1234F"}, True)

    def test_common_indian_formats_are_hidden_and_dates_and_times_are_kept(self):
        hidden = ("Rs 45000/-", "₹45,000", "INR 1,20,000.50", "12 LPA", "45k", "3.5 lakhs", "98765-43210",
                  "+91-9876543210", "09876543210", "022 2345 6789", "+44 20 7946 0958", "1234 5678 9012",
                  "ABCDE1234F", "SBIN0012345", "UAN 100123456789.", "emp id 4567890,", "x.y+z@mail.co.in",
                  "www.linkedin.com/in/asha", "https://a.b/c?d=1", "asha.v [at] gmail [dot] com",
                  "asha(at)gmail.com")
        for text in hidden:
            (seen,), table = redact.hide([text], [])
            self.assertEqual(len(table), 1, text)
            self.assertNotIn(next(iter(table.values())), seen, text)
        for text in ("on 25/11/2026", "at 10:30", "2026-11-24", "version 3.5", "Room 204", "in 2 days"):
            self.assertEqual(redact.hide([text], [])[0], [text])

    def test_near_miss_placeholders_are_fixed_and_invented_ones_or_numbers_refused(self):
        _, table = redact.hide([BODY], ["Asha Verma"])
        fixed = redact.restore("Your [amount_1] query, {NAME_1}. We'll write to EMAIL_1.", table)
        self.assertEqual(fixed.problems, ())
        self.assertEqual(fixed.text, "Your Rs. 45,000 query, Asha Verma. We'll write to asha.v@gmail.com.")
        self.assertEqual(len(fixed.fixes), 3)
        for bad, why in (("Thanks [NAME_9].", "[NAME_9] is not in the mail"),
                         ("We will pay Rs 50,000.", "amount"), ("Call 9812345678.", "phone"),
                         ("Write to hr2@gmail.com.", "email")):
            back = redact.restore(bad, table)
            self.assertEqual(back.text, "")
            self.assertIn(why, " ".join(back.problems))


class Reply(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.env = mock.patch.dict("os.environ", {"HERMES_HOME": str(home)})
        self.env.start()
        self.state = home / "brief"
        (self.state / "tokens").mkdir(parents=True)
        (home / ".env").write_text("MS_CLIENT_ID=ms\nMS_TENANT_ID=t\nGEMINI_API_KEY=g\n", encoding="utf-8")
        (self.state / "tokens/microsoft.json").write_text('{"refresh_token": "r0"}', encoding="utf-8")
        (self.state / "brief.yaml").write_text("hr:\n  mailbox: hr@co.com\n  sender_name: Medoc HR\n",
                                               encoding="utf-8")
        self.answers: list[dict | str] = []
        self.prompts: list[str] = []
        self.http = FakeHttp()
        self.http.on("POST", "https://login.microsoftonline.com/t/oauth2/v2.0/token",
                     {"access_token": "a", "refresh_token": "r1"})
        self.http.on("GET", GRAPH + "/me/mailFolders/sentitems", {"id": "SENT"})
        self.http.on("GET", GRAPH + "/me/messages", {"value": [
            self.mail("m1", "Pending salary for October", "asha.v@gmail.com", "Asha Verma", "2026-11-18T06:00:00"),
            self.mail("m2", "Application for SDE role", "a1@gmail.com", "Ravi", "2026-11-18T07:00:00"),
            self.mail("m3", "Resume - Data Analyst", "a2@gmail.com", "Meera", "2026-11-18T08:00:00"),
        ]})
        self.http.on("GET", GRAPH + "/me/messages/m1", {
            "subject": "Pending salary for October", "uniqueBody": {"content": BODY},
            "from": {"emailAddress": {"name": "Asha Verma", "address": "asha.v@gmail.com"}},
            "toRecipients": [{"emailAddress": {"name": "HR", "address": "hr@co.com"}}],
            "ccRecipients": [{"emailAddress": {"name": "Kiran Rao", "address": "kiran@co.com"}}]})
        self.http.on("POST", GEMINI, self._gemini)
        for m in ("m1", "m2", "m3"):
            self.http.on("POST", f"{GRAPH}/me/messages/{m}/reply", {})
        self.hr("inbox show")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    @staticmethod
    def mail(mid, subject, sender, name, when):
        return {"id": mid, "subject": subject, "receivedDateTime": when + "Z", "conversationId": "c" + mid,
                "from": {"emailAddress": {"name": name, "address": sender}}, "webLink": "", "parentFolderId": "IN"}

    def _gemini(self, call):
        self.prompts.append(json.dumps(call.json_body))
        answer = self.answers.pop(0)
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return {"candidates": [{"content": {"parts": [{"text": text}]}}], "usageMetadata": {}}

    def hr(self, words: str, at: float = NOW) -> str:
        return chat.handle(words, self.state, self.http, at)

    def replies(self) -> list:
        return [c for c in self.http.calls if c.url.endswith("/reply")]

    def test_gemini_sees_placeholders_only_and_the_reply_has_the_real_details(self):
        self.answers = [{"paragraphs": ["Hi [NAME_2],",  # the model's own greeting is dropped
                                        "Thank you for writing about your [AMOUNT_1] for October. We are checking "
                                        "it with finance and will reply to [EMAIL_1] by Friday.",
                                        "Best regards,\nHR"]}]
        shown = self.hr("reply 1 say we are checking with finance, reply by Friday")
        sent_to_model = self.prompts[0]
        for bit in SECRET_BITS:
            self.assertNotIn(bit, sent_to_model)
        self.assertIn("**Reply to Asha Verma** <asha.v@gmail.com> — Re: Pending salary for October", shown)
        self.assertIn("Hi Asha,\n\nThank you for writing about your Rs. 45,000 for October.", shown)
        self.assertIn("reply to asha.v@gmail.com by Friday.\n\nRegards,\nMedoc HR", shown)
        self.assertIn("Fixed in its answer: dropped its greeting", shown)
        self.assertIn("were hidden from it and put back", shown)
        self.assertEqual(self.replies(), [])  # nothing goes out before yes

        self.assertIn("✅ Sent 1 of 1 replies from hr@co.com", self.hr("reply yes"))
        call = self.replies()[0]
        self.assertTrue(call.url.endswith("/me/messages/m1/reply"))
        self.assertEqual(call.json_body["message"]["from"], {"emailAddress": {"address": "hr@co.com"}})
        self.assertIn("Rs. 45,000", call.json_body["message"]["body"]["content"])
        self.assertIn("No reply is waiting", self.hr("reply yes"))  # a second yes sends nothing
        self.assertEqual(len(self.replies()), 1)
        self.assertNotIn("Pending salary", self.hr("list"))  # answered: no longer waiting

    def test_an_invented_placeholder_is_asked_again_and_a_model_that_keeps_inventing_is_refused(self):
        self.answers = [{"paragraphs": ["We spoke to [NAME_7] about it."]},
                        {"paragraphs": ["We are looking into your [AMOUNT_1] query."]}]
        shown = self.hr("reply 1")
        self.assertIn("We are looking into your Rs. 45,000 query.", shown)
        self.assertIn("refused: [NAME_7] is not in the mail", self.prompts[1])

        bad = {"paragraphs": ["We will pay Rs 50,000 on Monday."]}
        self.answers = [bad] * 8  # two tries on each of the four models
        shown = self.hr("reply 1")
        self.assertIn("No draft passed the checks, so nothing was drafted", shown)
        self.assertIn("amount 'Rs 50,000' is not in the mail", shown)
        self.assertIn("/hr reply 1 ack", shown)
        self.assertIn("Reply to Asha Verma", self.hr("reply show"))  # the earlier good draft is kept

    def test_templates_use_no_model_and_applications_are_answered_in_one_batch(self):
        shown = self.hr("reply 1 salary Friday")
        self.assertIn("We'll get back to you by Friday.", shown)
        self.assertIn("From template salary.", shown)
        self.hr("reply no")
        listed = self.hr("list")
        self.assertIn("📄 2 applications of the last 14 days have no answer", listed)
        batch = self.hr("reply applications ack")
        self.assertIn("**Replies to 2 mails**", batch)
        self.assertIn("1. Ravi <a1@gmail.com> — Re: Application for SDE role", batch)
        self.assertIn("✅ Sent 2 of 2 replies", self.hr("reply yes"))
        self.assertEqual(self.prompts, [])
        self.assertNotIn("applications", self.hr("list"))

    def test_hr_list_shows_waiting_mail_and_approvals_and_an_expired_draft_stays(self):
        self.hr("reply 1 docs")
        listed = self.hr("list")
        self.assertIn("1. 🚨 Asha Verma — Pending salary for October", listed)
        self.assertIn("✍️ HR reply: waiting for your yes", listed)
        later = NOW + 3 * 3600
        self.assertIn("No reply is waiting", self.hr("reply show", later))
        self.assertIn("⌛ HR reply: expired without your yes", self.hr("list", later))
        self.assertIn("Dropped the expired reply", self.hr("reply no", later))

    def test_a_greeting_or_sign_off_inside_a_paragraph_is_cut_and_the_subject_is_the_threads(self):
        self.answers = [{"paragraphs": ["Hi [NAME_3], thank you for writing about your [AMOUNT_1].",
                                        "We wish you the very best. We will reply by Friday.\nWarm regards,\nHR Team\nMedoc"]}]
        shown = self.hr("reply 1")
        self.assertIn("Hi Asha,\n\nThank you for writing about your Rs. 45,000.\n\n"
                      "We wish you the very best. We will reply by Friday.\n\nRegards,\nMedoc HR", shown)
        self.assertEqual(shown.count("Hi Asha"), 1)
        self.assertIn("dropped its greeting 'Hi [NAME_3],'", shown)
        self.assertIn("— Re: Pending salary for October", shown)  # the subject is the thread's, never the model's
        self.hr("reply yes")
        self.assertNotIn("subject", self.replies()[0].json_body["message"])

    def test_edit_replaces_the_words_and_keeps_the_greeting_and_sign_off(self):
        self.hr("reply 1 ack")
        shown = self.hr("reply edit We have paid it today.\n\nPlease check your account.")
        self.assertIn("Hi Asha,\n\nWe have paid it today.\n\nPlease check your account.\n\nRegards,\nMedoc HR", shown)
        self.assertIn("From your words.", shown)

    def test_help_and_a_bad_number(self):
        self.assertIn("/hr reply applications ack", self.hr("reply help"))
        self.assertIn("Pick a mail 1 to 1", self.hr("reply 9"))
        self.assertIn("/hr list", self.hr(""))


if __name__ == "__main__":
    unittest.main()
