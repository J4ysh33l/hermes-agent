"""/hr offer and /hr duties against a generated Word template, a fake Gemini and a fake Outlook.

The promises tested: every bracket field of the template is filled (a field Word split over runs too,
the bold name stays bold); the duties paragraph becomes one bullet per duty; an unknown field stops
the letter; the model hears only the position, never the person; a position seen before costs no
call; Gemma → Gemma → Flash-Lite are tried in order only on failure; the letter goes out once, only
after yes.

Run: python3 orchestrator/hr/tests/test_offer.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import docx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator/brief/tests"))

from fakes import FakeHttp, http_error

from orchestrator.brief.settings import ModelChoice
from orchestrator.hr import chat, duties, offer
from orchestrator.hr.docfill import TemplateError

NOW = 1_795_000_000.0  # 2026-11-19
GRAPH = "https://graph.microsoft.com/v1.0"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/"
FIVE = ["Assist the marketing team in planning and running social media campaigns across channels.",
        "Prepare weekly reports on campaign reach, engagement and leads for the marketing lead.",
        "Research competitors and healthcare trends to suggest ideas for content and outreach.",
        "Coordinate with design and product teams to produce brochures, posts and newsletters.",
        "Support events, webinars and hospital outreach with materials and follow-ups."]
ASHA = "Name: Asha Verma\nPosition: Marketing Intern\nStart: 01/12/2026\nMonths: 3\nStipend: 15,000\nEmail: asha@example.com"


def template(path: Path, extra: str = "") -> None:
    """Like the real letter: a bold [Name] run, a field Word split over runs, a bulleted duties line,
    and the stipend in a table."""
    d = docx.Document()
    p = d.add_paragraph("Dear ")
    p.add_run("[Name]").bold = True
    p.add_run(",")
    p = d.add_paragraph("We offer you the position of ")
    p.add_run("[Position] ").bold = True
    p.add_run("starting on [Start date].")
    d.add_paragraph("Your primary duties and responsibilities include:")
    d.add_paragraph("[4-5 duties and responsibilities]", style="List Bullet")
    p = d.add_paragraph("A fixed duration of [duration spelled] ([dura")
    p.add_run("tion number]) months, commencing on [start date] and concluding on [end date].")
    t = d.add_table(rows=2, cols=3)
    for cell, text in zip(t.rows[1].cells, ("Stipend", "[Monthly]", "[Annual]"), strict=True):
        cell.text = text
    if extra:
        d.add_paragraph(extra)
    d.save(str(path))


def text_of(path: Path) -> tuple[list, str]:
    d = docx.Document(str(path))
    cells = " ".join(c.text for c in d.tables[0].rows[1].cells)
    return d.paragraphs, "\n".join(p.text for p in d.paragraphs) + "\n" + cells


class Parse(unittest.TestCase):
    def test_keyed_lines_and_one_line_give_the_same_offer(self):
        a, _ = offer.parse(ASHA)
        b, _ = offer.parse("Asha Verma, Marketing Intern, 1 Dec, 2026, 3 months, Rs 15000/-, asha@example.com")
        self.assertEqual(a, b)
        self.assertEqual(a, offer.Offer("Asha Verma", "Marketing Intern", date(2026, 12, 1), 3, 15000,
                                        "asha@example.com"))

    def test_every_problem_is_named_at_once(self):
        made, problems = offer.parse("Name: Asha\nPosition: Intern\nStart: 31/02/2026\nMonths: forty\n"
                                     "Stipend: lots\nEmail: asha@")
        self.assertIsNone(made)
        self.assertEqual(len(problems), 4, problems)
        _, missing = offer.parse("Name: Asha")
        self.assertIn("Position is missing", missing)

    def test_values_dates_and_money(self):
        v = offer.Offer("Asha Verma", "Intern", date(2026, 12, 1), 3, 15000).values()
        self.assertEqual((v["start_date"], v["end_date"]), ("1 December 2026", "28 February 2027"))
        self.assertEqual((v["duration_words"], v["duration_number"]), ("three", "3"))
        self.assertEqual((v["monthly"], v["annual"]), ("₹15,000", "₹1,80,000"))
        self.assertEqual(offer.Offer("A", "I", date(2027, 1, 31), 1, 1).end, date(2027, 2, 28))


class Letter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.offer, _ = offer.parse(ASHA)

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_field_is_filled_and_duties_become_bullets(self):
        template(self.dir / "t.docx")
        offer.make(self.dir / "t.docx", self.offer, tuple(FIVE), self.dir / "out.docx")
        paragraphs, text = text_of(self.dir / "out.docx")
        self.assertNotIn("[", text)
        for bit in ("Dear Asha Verma,", "position of Marketing Intern starting on 1 December 2026.",
                    "three (3) months, commencing on 1 December 2026 and concluding on 28 February 2027.",
                    "₹15,000", "₹1,80,000"):
            self.assertIn(bit, text)
        bullets = [p for p in paragraphs if p.style.name == "List Bullet"]
        self.assertEqual([p.text for p in bullets], FIVE)
        name_run = next(r for r in paragraphs[0].runs if "Asha" in r.text)
        self.assertTrue(name_run.bold)

    def test_an_unknown_field_or_a_duties_field_inside_a_sentence_stops_the_letter(self):
        template(self.dir / "t.docx", extra="Report to [Manager name].")
        with self.assertRaisesRegex(TemplateError, r"\[Manager name\]"):
            offer.make(self.dir / "t.docx", self.offer, tuple(FIVE), self.dir / "out.docx")
        template(self.dir / "t2.docx", extra="You will do [duties] daily.")
        with self.assertRaisesRegex(TemplateError, "paragraph of its own"):
            offer.make(self.dir / "t2.docx", self.offer, tuple(FIVE), self.dir / "out.docx")
        self.assertFalse((self.dir / "out.docx").exists())


class Duties(unittest.TestCase):
    MODELS = (ModelChoice("gemma-4-31b-it", False), ModelChoice("gemma-4-26b-a4b-it", False),
              ModelChoice("gemini-3.1-flash-lite"))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.table = duties.Table(Path(self.tmp.name))
        self.http = FakeHttp()

    def tearDown(self):
        self.tmp.cleanup()

    def answer(self, text):
        return lambda _c: {"candidates": [{"content": {"parts": [{"text": text}]}}], "usageMetadata": {}}

    def run_it(self, position="Marketing Intern"):
        return duties.find_or_write(self.table, self.http, "g", self.MODELS, position, "Medoc Health",
                                    "a healthcare technology company in India", date(2026, 11, 19))

    def test_one_call_for_a_new_position_then_none(self):
        self.http.on("POST", GEMINI + "gemma-4-31b-it", self.answer(json.dumps({"duties": FIVE})))
        first = self.run_it()
        self.assertEqual((first.items, first.by, first.saved), (tuple(FIVE), "gemma-4-31b-it", False))
        again = duties.find_or_write(duties.Table(Path(self.tmp.name)), self.http, "g", self.MODELS,
                                     " marketing  intern.", "Medoc Health", "x", date(2026, 11, 20))
        self.assertTrue(again.saved)
        self.assertEqual(self.http.count(GEMINI), 1)
        sent = json.dumps(self.http.calls[0].json_body)
        self.assertIn("Marketing Intern", sent)
        self.assertNotIn("responseMimeType", sent)  # Gemma takes no JSON mode

    def test_a_failed_or_bad_answer_moves_to_the_next_model(self):
        self.http.on("POST", GEMINI + "gemma-4-31b-it", http_error(503))
        self.http.on("POST", GEMINI + "gemma-4-26b-a4b-it", self.answer('{"duties": ["Too few.", "Two."]}'))
        bullets = "Sure! Here they are:\n" + "\n".join(f"{n}. {d}" for n, d in enumerate(FIVE, 1))
        self.http.on("POST", GEMINI + "gemini-3.1-flash-lite", self.answer(bullets))
        made = self.run_it()
        self.assertEqual((made.items, made.by), (tuple(FIVE), "gemini-3.1-flash-lite"))
        self.assertEqual(self.http.count(GEMINI), 3)

    def test_nothing_passes_or_no_key_says_how_to_set_them_yourself(self):
        for m in self.MODELS:
            self.http.on("POST", GEMINI + m.id, http_error(429))
        with self.assertRaisesRegex(duties.DutiesError, "/hr duties Marketing Intern ="):
            self.run_it()
        with self.assertRaisesRegex(duties.DutiesError, "GEMINI_API_KEY"):
            duties.find_or_write(self.table, self.http, "", self.MODELS, "Designer", "M", "x", date(2026, 11, 19))
        self.assertEqual(self.table.rows, {})


class Chat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = mock.patch.dict("os.environ", {"HERMES_HOME": str(self.home)})
        self.env.start()
        self.state = self.home / "brief"
        (self.state / "tokens").mkdir(parents=True)
        (self.home / ".env").write_text("MS_CLIENT_ID=ms\nMS_TENANT_ID=t\nGEMINI_API_KEY=g\n", encoding="utf-8")
        (self.state / "tokens/microsoft.json").write_text('{"refresh_token": "r0"}', encoding="utf-8")
        (self.state / "brief.yaml").write_text("hr:\n  mailbox: hr@co.com\n  sender_name: Medoc HR\n",
                                               encoding="utf-8")
        (self.home / "hr/templates").mkdir(parents=True)
        template(self.home / "hr/templates/offer_intern.docx")
        self.mails: list[dict] = []
        self.http = FakeHttp()
        self.http.on("POST", "https://login.microsoftonline.com/t/oauth2/v2.0/token",
                     {"access_token": "a", "refresh_token": "r1"})
        self.http.on("POST", GRAPH + "/me/sendMail", lambda c: self.mails.append(c.json_body["message"]) or {})
        self.http.on("POST", GEMINI, lambda _c: {"candidates": [{"content": {"parts": [
            {"text": json.dumps({"duties": FIVE})}]}}], "usageMetadata": {}})
        self.pdf = mock.patch.object(chat, "convert", side_effect=self._pdf)  # LibreOffice is tested in test_hr
        self.pdf.start()

    def tearDown(self):
        self.pdf.stop()
        self.env.stop()
        self.tmp.cleanup()

    @staticmethod
    def _pdf(docs, folder):
        out = folder / (docs[0].stem + ".pdf")
        out.write_bytes(b"%PDF-1.4 letter")
        return [out]

    def hr(self, words: str, at: float = NOW) -> str:
        return chat.handle(words, self.state, self.http, at)

    def test_offer_then_yes_sends_once_and_the_next_intern_costs_no_call(self):
        shown = self.hr("offer " + ASHA)
        self.assertIn("Offer letter: Asha Verma", shown)
        self.assertIn("written by gemma-4-31b-it", shown)
        prompt = json.dumps(self.http.calls[0].json_body)
        for private in ("Asha", "Verma", "15,000", "15000", "asha@example.com", "2026", "December"):
            self.assertNotIn(private, prompt)
        self.assertEqual(self.mails, [])
        self.assertIn("sent to Asha Verma", self.hr("offer yes"))
        self.assertEqual(len(self.mails), 1)
        mail = self.mails[0]
        self.assertEqual(mail["from"]["emailAddress"]["address"], "hr@co.com")
        self.assertEqual(mail["attachments"][0]["name"], "Offer Letter - Asha Verma.pdf")
        self.assertIn("No offer letter is waiting", self.hr("offer yes"))
        shown = self.hr("offer Rohan Das, Marketing intern, 05/01/2027, 6, 12000")
        self.assertIn("saved for this position, no model call", shown)
        self.assertEqual(self.http.count(GEMINI), 1)
        self.assertIn("no email", shown)

    def test_duties_set_by_you_are_used_and_listed(self):
        said = self.hr("duties Data Analyst Intern = Clean and check datasets from hospital systems for reports; "
                       "Build weekly dashboards on patient flow for the operations team; "
                       "Write short notes explaining trends to managers and clinicians; "
                       "Help automate recurring reports with spreadsheets and simple scripts")
        self.assertIn("Saved 4 duties", said)
        self.assertIn("set by you", self.hr("offer Meera, Data Analyst Intern, 01/12/2026, 2, 10000"))
        self.assertEqual(self.http.count(GEMINI), 0)
        self.assertIn("Data Analyst Intern: 4 duties, you", self.hr("duties list"))
        self.assertIn("Forgot", self.hr("duties forget data analyst intern"))

    def test_a_bad_request_or_a_missing_template_makes_nothing(self):
        self.assertIn("Stipend is missing", self.hr("offer Name: Asha\nPosition: Intern\nStart: 01/12/2026\nMonths: 3"))
        (self.home / "hr/templates/offer_intern.docx").unlink()
        self.assertIn("No offer template", self.hr("offer " + ASHA))
        self.assertEqual(self.http.count(GEMINI), 0)
        self.assertIn("Nothing was waiting", self.hr("offer no"))


if __name__ == "__main__":
    unittest.main()
