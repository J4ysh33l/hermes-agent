"""/hr certificate: reading the people, the wording for tech and other positions, the Ref.No counter,
numbers given back on drop, the mail (PDF, cc). Chrome is replaced by a fake PDF here.

Run: python3 orchestrator/hr/tests/test_certificate.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator/brief/tests"))

from fakes import FakeHttp

from orchestrator.hr import certificate, chat

TODAY = date(2026, 11, 19)
NOW = 1_795_000_000.0  # 2026-11-19
GRAPH = "https://graph.microsoft.com/v1.0"
SVG = '<svg><text>{{ref}}</text><div style="font-size:{{name_size}}px">{{name}}</div><div>{{paragraph}}</div></svg>'
TWO = ("Name: Kushagra\nPosition: SDE Intern\nStart: 01/08/2025\nEnd: 31/08/2026\nPronoun: he\n"
       "Email: k@example.com\n\nName: priya sharma\nPosition: HR Executive\nStart: 01/02/2026\nEnd: 31/10/2026")


class Rules(unittest.TestCase):
    def test_two_people_and_a_pronoun_or_email_is_never_shared(self):
        people, problems = certificate.parse(TWO, TODAY)
        self.assertEqual(problems, [])
        self.assertEqual([p.name for p in people], ["Kushagra", "Priya Sharma"])
        self.assertEqual([p.pronoun for p in people], ["he", "they"])
        self.assertEqual([p.email for p in people], ["k@example.com", ""])

    def test_tech_or_general_wording_and_the_article(self):
        k, p = certificate.parse(TWO, TODAY)[0]
        tech, general = certificate.paragraph(k, "Medoc Health"), certificate.paragraph(p, "Medoc Health")
        self.assertIn("as an SDE Intern from 1 August 2025 to 31 August 2026", tech)
        self.assertIn("software development", tech)
        self.assertIn("He demonstrated", tech)
        self.assertNotIn("software", general)
        self.assertIn("as an HR Executive", general)
        self.assertIn("They demonstrated", general)
        self.assertEqual(certificate.article("Marketing Intern"), "a Marketing Intern")
        self.assertEqual(certificate.article("UX Designer"), "a UX Designer")
        self.assertFalse(certificate.is_tech("Sales Executive"))
        self.assertTrue(certificate.is_tech("Data Analyst Intern"))

    def test_every_problem_is_named(self):
        _, problems = certificate.parse("Name: A\nPosition: Intern\nStart: 01/08/2026\nEnd: 01/07/2026", TODAY)
        self.assertIn("before the start", problems[0])
        _, problems = certificate.parse("Name: A\nStart: 01/08/2026\nEnd: 31/12/2026", TODAY)
        self.assertEqual(problems, ["Position is missing"])
        _, problems = certificate.parse("Name: A\nPosition: Intern\nStart: 01/08/2026\nEnd: 31/12/2026", TODAY)
        self.assertIn("has not come yet", problems[0])

    def test_numbers_count_up_and_only_the_newest_come_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = certificate.Register(Path(tmp))
            reg.set_next(160)
            k, p = certificate.parse(TWO, TODAY)[0]
            self.assertEqual(reg.take(k, TODAY), "HR/2026/11/0160")
            self.assertEqual(reg.take(p, date(2027, 1, 3)), "HR/2027/1/0161")
            self.assertEqual(reg.give_back(["HR/2026/11/0160"]), [])  # 0161 came after it
            self.assertEqual(reg.give_back(["HR/2027/1/0161", "HR/2026/11/0160"]),
                             ["HR/2027/1/0161", "HR/2026/11/0160"])
            self.assertEqual(reg.last, 159)

    def test_fill_escapes_and_a_template_without_a_field_stops(self):
        out = certificate.fill(SVG, "HR/2026/11/0160", "A & B", "x < y")
        self.assertIn("A &amp; B", out)
        self.assertIn("x &lt; y", out)
        with self.assertRaises(certificate.CertificateError):
            certificate.fill("<svg>{{name}}</svg>", "r", "n", "p")


class Chat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = mock.patch.dict("os.environ", {"HERMES_HOME": str(self.home)})
        self.env.start()
        self.state = self.home / "brief"
        (self.state / "tokens").mkdir(parents=True)
        (self.home / ".env").write_text("MS_CLIENT_ID=ms\nMS_TENANT_ID=t\n", encoding="utf-8")
        (self.state / "tokens/microsoft.json").write_text('{"refresh_token": "r0"}', encoding="utf-8")
        (self.state / "brief.yaml").write_text("hr:\n  mailbox: hr@co.com\n  cc: [boss@co.com]\n", encoding="utf-8")
        (self.home / "hr/templates").mkdir(parents=True)
        (self.home / "hr/templates" / certificate.TEMPLATE).write_text(SVG, encoding="utf-8")
        self.mails: list[dict] = []
        self.http = FakeHttp()
        self.http.on("POST", "https://login.microsoftonline.com/t/oauth2/v2.0/token",
                     {"access_token": "a", "refresh_token": "r1"})
        self.http.on("POST", GRAPH + "/me/sendMail", lambda c: self.mails.append(c.json_body["message"]) or {})
        self.filled: list[str] = []
        self.render = mock.patch.object(certificate, "render", side_effect=self._render)
        self.render.start()

    def tearDown(self):
        self.render.stop()
        self.env.stop()
        self.tmp.cleanup()

    def _render(self, svg, out):
        self.filled.append(svg)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"%PDF-1.4 certificate")
        return out

    def hr(self, words: str) -> str:
        return chat.handle(words, self.state, self.http, NOW)

    def test_make_numbers_send_once_with_cc_and_drop_gives_numbers_back(self):
        self.assertIn("next certificate gets number 0160", self.hr("certificate next 160"))
        shown = self.hr("completion certificate " + TWO)
        self.assertIn("Ref.No HR/2026/11/0160", shown)
        self.assertIn("Ref.No HR/2026/11/0161", shown)
        self.assertIn("HR/2026/11/0160", self.filled[0])
        self.assertIn("Kushagra", self.filled[0])
        self.assertIn("Sent 1 of 1 certificates", self.hr("certificate yes"))
        mail = self.mails[0]
        self.assertEqual(mail["attachments"][0]["name"], "Experience Certificate - Kushagra.pdf")
        self.assertEqual(mail["ccRecipients"], [{"emailAddress": {"address": "boss@co.com"}}])
        self.assertIn("No certificate is waiting", self.hr("certificate yes"))
        self.assertIn("number 0162", self.hr("certificate next"))
        self.hr("certificate " + TWO)
        self.assertIn("Numbers given back: HR/2026/11/0163, HR/2026/11/0162", self.hr("certificate no"))
        self.assertIn("number 0162", self.hr("certificate next"))


if __name__ == "__main__":
    unittest.main()
