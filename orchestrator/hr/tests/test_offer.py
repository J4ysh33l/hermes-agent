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
TODAY = date(2026, 11, 19)
INTERN, FTE = offer.KINDS["internship"], offer.KINDS["fte"]
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
        a, _ = offer.parse(ASHA, INTERN)
        b, _ = offer.parse("Asha Verma, Marketing Intern, 1 Dec, 2026, 3 months, Rs 15000/-, asha@example.com", INTERN)
        self.assertEqual(a, b)
        self.assertEqual(a, offer.Offer(INTERN, "Asha Verma", "Marketing Intern", date(2026, 12, 1), 3, 15000,
                                        "asha@example.com"))

    def test_every_problem_is_named_at_once(self):
        made, problems = offer.parse("Name: Asha\nPosition: Intern\nStart: 31/02/2026\nMonths: forty\n"
                                     "Stipend: lots\nEmail: asha@", INTERN)
        self.assertIsNone(made)
        self.assertEqual(len(problems), 4, problems)
        _, missing = offer.parse("Name: Asha", INTERN)
        self.assertIn("Position is missing", missing)

    def test_values_dates_and_money(self):
        v = offer.Offer(INTERN, "Asha Verma", "Intern", date(2026, 12, 1), 3, 15000).values(date(2026, 11, 19))
        self.assertEqual((v["start date"], v["end date"], v["date"]), ("1 December 2026", "28 February 2027",
                                                                         "19 November 2026"))
        self.assertEqual((v["duration spelled"], v["duration number"]), ("three", "3"))
        self.assertEqual((v["monthly"], v["annual"]), ("₹15,000", "₹1,80,000"))
        self.assertEqual(offer.Offer(INTERN, "A", "I", date(2027, 1, 31), 1, 1).end, date(2027, 2, 28))


class Letter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.offer, _ = offer.parse(ASHA, INTERN)

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_field_is_filled_and_duties_become_bullets(self):
        template(self.dir / "t.docx")
        offer.make(self.dir / "t.docx", self.offer, tuple(FIVE), self.dir / "out.docx", TODAY)
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
            offer.make(self.dir / "t.docx", self.offer, tuple(FIVE), self.dir / "out.docx", TODAY)
        template(self.dir / "t2.docx", extra="You will do [duties] daily.")
        with self.assertRaisesRegex(TemplateError, "paragraph of its own"):
            offer.make(self.dir / "t2.docx", self.offer, tuple(FIVE), self.dir / "out.docx", TODAY)
        self.assertFalse((self.dir / "out.docx").exists())


class FullTime(unittest.TestCase):
    """A full-time offer: no tenure, pay as CTC, and the template's own extra fields filled from your lines."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        d = docx.Document()
        d.add_paragraph("[Date]")
        d.add_paragraph("Dear [Name], you join as [Position] in [Location] on [Start date], CTC [Annual] "
                        "([Monthly] a month).")
        d.add_paragraph("[duties and responsibilities]", style="List Bullet")
        d.save(str(self.dir / "fte.docx"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_ctc_and_your_own_fields_fill_the_letter(self):
        made, problems = offer.parse("Name: Ravi Kumar\nPosition: Backend Engineer\nStart: 01/01/2027\n"
                                     "CTC: 12 LPA\nLocation: Mohali", FTE)
        self.assertEqual(problems, [])
        self.assertEqual((made.months, made.monthly, made.annual), (0, 100000, 1200000))
        offer.make(self.dir / "fte.docx", made, tuple(FIVE[:4]), self.dir / "out.docx", TODAY)
        _paragraphs, text = text_of_plain(self.dir / "out.docx")
        self.assertIn("19 November 2026", text)
        self.assertIn("Backend Engineer in Mohali on 1 January 2027, CTC ₹12,00,000 (₹1,00,000 a month).", text)

    def test_a_field_with_no_value_is_named(self):
        made, _ = offer.parse("Ravi, Backend Engineer, 01/01/2027, 90000", FTE)
        self.assertEqual(made.monthly, 90000)
        with self.assertRaisesRegex(TemplateError, r"\[Location\]"):
            offer.make(self.dir / "fte.docx", made, tuple(FIVE), self.dir / "out.docx", TODAY)
        _, problems = offer.parse("Ravi, Consultant, 01/01/2027", offer.KINDS["consultant"])
        self.assertTrue(problems)


def text_of_plain(path: Path) -> tuple[list, str]:
    d = docx.Document(str(path))
    return d.paragraphs, "\n".join(p.text for p in d.paragraphs)


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

    def test_gemini_2_5_flash_is_the_last_resort_in_the_default_order(self):
        from orchestrator.hr.settings import DUTIES_MODELS, REPLY_MODELS
        self.assertEqual(DUTIES_MODELS[-1], ModelChoice("gemini-2.5-flash"))
        self.assertEqual(REPLY_MODELS[-1], ModelChoice("gemini-2.5-flash"))
        for m in DUTIES_MODELS[:-1]:
            self.http.on("POST", GEMINI + m.id, http_error(503))
        self.http.on("POST", GEMINI + "gemini-2.5-flash", self.answer(json.dumps({"duties": FIVE})))
        made = duties.find_or_write(self.table, self.http, "g", DUTIES_MODELS, "Marketing Intern", "Medoc Health",
                                    "x", date(2026, 11, 19))
        self.assertEqual((made.items, made.by), (tuple(FIVE), "gemini-2.5-flash"))
        self.assertEqual(self.http.count(GEMINI), len(DUTIES_MODELS))

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
        template(self.home / "hr/templates/offer_internship.docx")
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
        shown = self.hr("offer internship\n" + ASHA)
        self.assertIn("Internship offer letter: Asha Verma", shown)
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
        shown = self.hr("offer intern Rohan Das, Marketing intern, 05/01/2027, 6, 12000")
        self.assertIn("saved for this position, no model call", shown)
        self.assertEqual(self.http.count(GEMINI), 1)
        self.assertIn("no email", shown)

    def test_duties_set_by_you_are_used_and_listed(self):
        said = self.hr("duties Data Analyst Intern = Clean and check datasets from hospital systems for reports; "
                       "Build weekly dashboards on patient flow for the operations team; "
                       "Write short notes explaining trends to managers and clinicians; "
                       "Help automate recurring reports with spreadsheets and simple scripts")
        self.assertIn("Saved 4 duties", said)
        self.assertIn("set by you", self.hr("offer internship Meera, Data Analyst Intern, 01/12/2026, 2, 10000"))
        self.assertEqual(self.http.count(GEMINI), 0)
        self.assertIn("Data Analyst Intern: 4 duties, you", self.hr("duties list"))
        self.assertIn("Forgot", self.hr("duties forget data analyst intern"))

    def test_the_kind_is_asked_for_and_each_kind_has_its_own_template_and_words(self):
        self.assertIn("Which kind of offer?", self.hr("offer " + ASHA))
        (self.home / "hr/templates/offer_consultant.docx").write_bytes(
            (self.home / "hr/templates/offer_internship.docx").read_bytes())
        shown = self.hr("offer consultant\n" + ASHA.replace("Marketing Intern", "Growth Consultant"))
        self.assertIn("Consultant offer letter: Asha Verma", shown)
        self.assertIn("fee ₹15,000 a month", shown)
        call = self.http.calls[0]
        self.assertEqual(call.headers["x-goog-api-key"], "g")  # the one GEMINI_API_KEY
        self.assertIn("Growth Consultant (consulting engagement)", json.dumps(call.json_body))

    def test_a_bad_request_or_a_missing_template_makes_nothing(self):
        # the plain reading misses the stipend; the models are asked to read it, their answer (here no
        # people at all) is not trusted, and the missing stipend is asked for, never guessed
        said = self.hr("offer internship\nName: Asha\nPosition: Intern\nStart: 01/12/2026\nMonths: 3")
        self.assertIn("Stipend is missing", said)
        self.assertEqual(self.http.count(GEMINI), 4)  # Gemma 31B, 26B, Flash-Lite 3.1, 3.5: none usable
        (self.home / "hr/templates/offer_internship.docx").unlink()
        self.assertIn("No internship offer template", self.hr("offer internship\n" + ASHA))
        self.assertEqual(self.http.count(GEMINI), 4)
        self.assertIn("Nothing was waiting", self.hr("offer no"))

    def test_cc_is_copied_on_every_offer_mail_but_never_twice_to_the_same_person(self):
        (self.state / "brief.yaml").write_text("hr:\n  mailbox: hr@co.com\n  sender_name: Medoc HR\n"
                                               "  cc: [Boss@co.com]\n", encoding="utf-8")
        self.http.on("GET", GRAPH + "/me", {"mail": "boss@co.com"})
        self.hr("offer internship\n" + ASHA)
        self.assertIn("to boss@co.com only", self.hr("offer test"))
        self.assertNotIn("ccRecipients", self.mails[0])  # the To is the cc already
        self.hr("offer yes")
        self.assertEqual(self.mails[1]["ccRecipients"], [{"emailAddress": {"address": "Boss@co.com"}}])
        self.assertEqual(self.mails[1]["toRecipients"][0]["emailAddress"]["address"], "asha@example.com")

    def test_several_people_unpaid_months_one_message_two_letters_one_duties_call(self):
        said = self.hr("offer internship\nName : Rishabh Mishra\nmonth :June -July\nrole : Trainee software developer\n"
                       "Email: r@example.com\n\nName : sanidhya pawar\nmonth : june -july\n"
                       "role : Trainee software developer\nEmail: s@example.com\n\nStipend - Unpaid")
        self.assertIn("2 offer letters", said)
        self.assertIn("Sanidhya Pawar", said)
        self.assertIn("1 June 2027 – 31 July 2027 (2 months)", said)
        self.assertIn("stipend: unpaid", said)
        self.assertEqual(self.http.count(GEMINI), 1)  # duties once for the position, nothing to read
        letter = next((self.home / "hr/offers").glob("*sanidhya-pawar/*.docx"))
        d = docx.Document(str(letter))
        self.assertEqual(d.tables, [])
        self.assertIn("unpaid internship", "\n".join(p.text for p in d.paragraphs))
        self.assertIn("Sent 2 of 2", self.hr("offer yes"))
        self.assertEqual([m["attachments"][0]["name"] for m in self.mails],
                         ["Offer Letter - Rishabh Mishra.pdf", "Offer Letter - Sanidhya Pawar.pdf"])

    def test_a_message_in_another_shape_is_read_by_the_model_then_checked(self):
        people = {"people": [{"name": "Meera Iyer", "position": "Data Analyst Intern", "start": "",
                              "period": "January - March", "months": "", "pay": "12000", "email": ""}]}
        answers = iter([people, {"duties": FIVE}])
        self.http.on("POST", GEMINI, lambda _c: {"candidates": [{"content": {"parts": [
            {"text": json.dumps(next(answers))}]}}], "usageMetadata": {}})
        said = self.hr("offer internship Please make one for Meera Iyer, our data analyst intern, "
                       "January to March, 12k a month")
        self.assertIn("read by gemma-4-31b-it", said)
        self.assertIn("1 January 2027 – 31 March 2027 (3 months)", said)
        self.assertIn("Meera Iyer", json.dumps(self.http.calls[0].json_body))


class Unpaid(unittest.TestCase):
    def test_period_words_to_a_start_and_months(self):
        today = date(2026, 11, 26)
        self.assertEqual(offer.period("June -July", today), (date(2027, 6, 1), 2))
        self.assertEqual(offer.period("Dec to Feb", today), (date(2026, 12, 1), 3))
        self.assertEqual(offer.period("Nov 2026 - Jan 2027", today), (date(2026, 11, 1), 3))
        self.assertIsNone(offer.period("soon", today))

    def test_a_line_given_once_is_for_everyone_and_lines_before_the_first_name_too(self):
        blocks = offer.people("Position: Intern\nName: A\nTenure: 2\nName: B\nTenure: 3\nStipend: Unpaid")
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            self.assertIn("stipend: unpaid", block.lower())
            self.assertIn("position: intern", block.lower())
        self.assertEqual(offer.people(ASHA), [ASHA])


if __name__ == "__main__":
    unittest.main()
