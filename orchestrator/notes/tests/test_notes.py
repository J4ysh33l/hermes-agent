"""Smriti against fake Teams, Gemini, Telegram and GitHub, with real ffmpeg on a generated recording.

Run: python3 orchestrator/notes/tests/test_notes.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator/brief/tests"))

from fakes import FakeHttp

from hermes_platform.resolver import locate_command
from orchestrator.brief.net import HttpError, Response
from orchestrator.notes import chat, store, transcribe, vtt, work
from orchestrator.notes.transcribe import Clock
from orchestrator.recap import parts

IST = ZoneInfo("Asia/Kolkata")
GRAPH = "https://graph.microsoft.com/v1.0"
GEMINI = "https://generativelanguage.googleapis.com"
TG = "https://api.telegram.org/bot123:abc"
GH = "https://api.github.com/repos/me/handoff"
HAS_FFMPEG = locate_command("ffmpeg").found and locate_command("ffprobe").found
START = datetime(2026, 11, 23, 14, 5, tzinfo=IST).timestamp()  # Mon 14:05 IST

SESSION_1 = """WEBVTT

00:00:30.000 --> 00:00:32.000
<v Asha Verma>Namaste, shall we start?</v>

00:00:33.000 --> 00:00:35.000
<v Asha Verma>Kal ka plan pehle.</v>

00:00:36.000 --> 00:00:37.500
<v Ravi Kumar>Haan, okay.</v>

00:00:38.000 --> 00:00:39.000
<v Ravi Kumar>Main bhejta hoon.</v>
"""
SESSION_2 = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v Asha Verma>We are back.</v>\n"
CHUNKS = ["[00:00] Speaker 1: Namaste, shall we start?",
          "[00:00] Speaker 1: Kal ka plan pehle.",
          "[00:00] Speaker 2: Haan, okay.\n[00:02] Speaker 2: Main bhejta hoon."]


def event(event_id: str, subject: str, start: str, end: str, *, organizer=True, provider="teamsForBusiness"):
    return {"id": event_id, "subject": subject, "start": {"dateTime": f"2026-11-23T{start}:00.0000000"},
            "end": {"dateTime": f"2026-11-23T{end}:00.0000000"}, "isOrganizer": organizer, "isCancelled": False,
            "onlineMeetingProvider": provider, "onlineMeeting": {"joinUrl": f"https://teams.example/{event_id}"}}


class FakeClock(Clock):
    """A fixed start that moves only when the code sleeps; the usage log reads the same clock."""

    def __init__(self, start: float) -> None:
        self.t = start
        self.slept = 0.0
        super().__init__(lambda: self.t, self._sleep)

    def _sleep(self, seconds: float) -> None:
        self.t += seconds
        self.slept += seconds


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg is not installed")
class Smriti(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = tempfile.TemporaryDirectory()
        rec = Path(cls.media.name) / "rec.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=9", "-f", "lavfi",
                        "-i", "color=c=black:s=64x64:d=9", "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(rec)],
                       check=True)
        cls.recording = rec.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.media.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / "brief/tokens").mkdir(parents=True)
        (self.home / ".env").write_text("MS_CLIENT_ID=c\nMS_TENANT_ID=t\nGEMINI_API_KEY=g\nTELEGRAM_BOT_TOKEN=123:abc\n"
                                        "TELEGRAM_ALLOWED_USERS=42\nGITHUB_HANDOFF_TOKEN=gh\n", encoding="utf-8")
        (self.home / "brief/tokens/microsoft.json").write_text('{"refresh_token": "r"}', encoding="utf-8")
        self.config()
        self.clock = FakeClock(START)
        self.events = [event("E1", "Product sync", "13:00", "13:50"),
                       event("E2", "Vendor call", "12:00", "12:30", organizer=False),
                       event("E3", "Long workshop", "13:30", "15:00"),
                       event("E4", "Zoom thing", "11:00", "11:30", provider="unknown")]
        self.recordings = [{"id": "R1", "createdDateTime": "2026-11-23T07:31:00.1234567Z",
                            "endDateTime": "2026-11-23T07:31:09Z"}]
        self.transcripts = [{"id": "T2", "createdDateTime": "2026-11-23T07:45:00Z"},
                            {"id": "T1", "createdDateTime": "2026-11-23T07:30:30Z"}]
        self.vtts = {"T1": SESSION_1, "T2": SESSION_2}
        self.prompts, self.uploads, self.deleted, self.sent, self.github = [], 0, [], [], {}
        self.chunk = 0
        self.http = self.fake_http()
        self.env = mock.patch.dict("os.environ", {"HERMES_HOME": str(self.home)})
        self.env.start()
        clock = self.clock

        class Now(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.fromtimestamp(clock.t, tz)

        self.usage_clock = mock.patch("orchestrator.usage.datetime", Now)
        self.usage_clock.start()

    def tearDown(self):
        self.usage_clock.stop()
        self.env.stop()
        self.tmp.cleanup()

    def config(self, **notes) -> None:
        settings = {"chunk_minutes": 0.05, "gap_seconds": 70, "handoff_repo": "me/handoff", **notes}
        (self.home / "brief/brief.yaml").write_text(json.dumps({"notes": settings}), encoding="utf-8")

    # ---- the fake services ----------------------------------------------------------------------

    def fake_http(self) -> FakeHttp:
        http = FakeHttp()
        http.on("POST", "https://login.microsoftonline.com/", {"access_token": "a", "refresh_token": "r2"})
        http.on("GET", GRAPH, self.graph)
        http.on("POST", f"{GEMINI}/upload/v1beta/files", lambda c: Response(200, b"{}", {"x-goog-upload-url": "https://up.example/1"}))
        http.on("POST", "https://up.example/", self.upload)
        http.on("GET", f"{GEMINI}/v1beta/files/", {"state": "ACTIVE"})
        http.on("DELETE", f"{GEMINI}/v1beta/files/", lambda c: self.deleted.append(c.url) or {})
        http.on("POST", f"{GEMINI}/v1beta/models/", self.gemini)
        http.on("POST", f"{TG}/send", lambda c: self.sent.append((c.url.rsplit("/", 1)[1], c.json_body or c.data)) or {})
        http.on("PUT", f"{GH}/contents/", lambda c: self.github.update({c.url.split("contents/")[1]: c.json_body}) or {})
        http.on("POST", f"{GH}/issues", {"number": 7})
        http.on("GET", f"{GH}/contents/", self.github_get)
        return http

    def graph(self, call):
        path = urllib.parse.urlsplit(call.url).path.removeprefix("/v1.0")
        if path == "/me/calendarView":
            return {"value": self.events}
        if path == "/me/onlineMeetings":
            return {"value": [{"id": "OM1"}]}
        if path.endswith("/transcripts"):
            return {"value": self.transcripts}
        if path.endswith("/recordings"):
            return {"value": self.recordings}
        if "/transcripts/" in path:
            return self.vtts[path.split("/transcripts/")[1].split("/")[0]]
        if "/recordings/" in path:
            return self.recording
        raise AssertionError(path)

    def upload(self, call):
        self.uploads += 1
        return {"file": {"name": f"files/a{self.uploads}", "uri": f"{GEMINI}/v1beta/files/a{self.uploads}"}}

    def gemini(self, call):
        parts = call.json_body["contents"][0]["parts"]
        self.prompts.append(parts[-1]["text"])
        if "file_data" in parts[0]:
            text, self.chunk = CHUNKS[self.chunk], self.chunk + 1
        else:
            text = "# Plan\n- **Ravi** sends the plan\n1. First step"
        return {"candidates": [{"content": {"parts": [{"text": text}]}}],
                "usageMetadata": {"promptTokenCount": 1100, "candidatesTokenCount": 40}}

    def github_get(self, call):
        path = call.url.split("contents/")[1]
        if path not in self.github:
            raise HttpError(404, call.url)
        return self.github[path]

    def smriti(self, force: bool = False) -> str:
        return work.run(work.Context(self.home, self.http, self.clock), force_check=force)

    def notes(self, words: str) -> str:
        return chat.handle(words, self.home, datetime.fromtimestamp(self.clock.t, IST))

    def audio_calls(self) -> list[str]:
        return [p for p in self.prompts if "Transcribe this meeting audio" in p]

    # ---- behaviour --------------------------------------------------------------------------------

    def test_asks_once_per_ended_meeting_you_organised_then_makes_what_you_ask(self):
        asked = self.smriti(force=True)
        self.assertEqual(asked.count("🎙"), 1, asked)
        self.assertIn("🎙 Product sync ended (13:00–13:50) · recording ✓ · transcript ✓ (2 sessions)", asked)
        self.assertIn("/notes product sync summary tasks prd", asked)
        audio = self.audio_calls()  # the transcript is stored at once, before anything is asked for
        self.assertEqual(len(audio), 3)  # 9 s of audio in 3 s chunks
        self.assertIn("Latin script", audio[0])
        self.assertIn("Speaker 1: Namaste, shall we start?", audio[1])  # the previous part, for the same numbering
        self.assertEqual(len(self.deleted), 3)  # every upload removed after its call
        self.assertGreaterEqual(self.clock.slept, 2 * 70)  # audio calls at least gap_seconds apart
        self.assertEqual(self.smriti(force=True), "")  # known meetings are not asked again
        self.assertIn("🎙 Mon 23 Nov 13:00 Product sync: what do you need?", self.recap_text())  # until answered
        self.assertIn("transcript ✓ · nothing asked yet", self.notes("list"))

        self.assertIn("summary, prd by Gemini", self.notes("product sync summary prd"))
        self.assertEqual(self.smriti(), "")
        self.assertEqual(len(self.audio_calls()), 3)  # documents come from the stored transcript

        m = store.Store(self.home).meetings["E1"]
        text = Path(m["transcript"]).read_text(encoding="utf-8")
        self.assertIn("[00:00] Asha Verma: Namaste, shall we start?", text)
        self.assertIn("[00:06] Ravi Kumar: Haan, okay.", text)
        self.assertNotIn("Speaker", text)
        self.assertEqual([r["status"] for r in m["requests"]], ["done", "done"])
        kinds = [k for k, _ in self.sent]
        self.assertEqual(kinds, ["sendMessage", "sendDocument"])
        self.assertIn("📝 Summary: Mon 23 Nov 13:00 Product sync", self.sent[0][1]["text"])
        self.assertIn(b'filename="PRD - Product sync.docx"', self.sent[1][1])
        self.assertFalse(list(Path(m["transcript"]).parent.glob("*.mp4")))  # the video is not kept

        self.assertIn("tasks by Gemini", self.notes("last tasks"))
        self.smriti()
        self.assertEqual(len(self.audio_calls()), 3)  # the saved transcript is reused: no audio again
        self.assertIn("📝 Tasks", self.sent[-1][1]["text"])
        self.assertIn("transcript ✓ · summary ✓ · prd ✓ · tasks ✓", self.notes("list"))

    def test_claude_writes_it_through_the_handoff_repo(self):
        self.smriti(force=True)
        self.notes("product sync doc client follow-up email claude")
        self.smriti()
        req = store.Store(self.home).meetings["E1"]["requests"][0]
        self.assertEqual((req["status"], req["issue"], req["what"]), ("claude", 7, "client follow-up email"))
        self.assertIn(f"smriti/{req['id']}/transcript.md", self.github)
        self.assertIn("Asha Verma", base64.b64decode(self.github[f"smriti/{req['id']}/transcript.md"]["content"]).decode())
        self.smriti()  # Claude has not written it yet
        self.assertEqual(self.sent, [])
        self.github[f"smriti/{req['id']}/result.md"] = {"content": base64.b64encode(b"# Email\nHi team").decode()}
        self.smriti()
        self.assertIn(b'filename="client follow-up email - Product sync.docx"', self.sent[0][1])
        self.assertEqual(store.Store(self.home).meetings["E1"]["requests"][0]["status"], "done")

    def test_skip_means_no_transcript_either(self):
        recordings, self.recordings, self.transcripts = self.recordings, [], []
        self.smriti(force=True)  # Teams is still processing: nothing to transcribe yet
        self.assertIn("Noted: nothing needed", self.notes("product sync skip"))
        self.recordings = recordings
        self.clock.t += 2 * 3600
        self.smriti()  # the 16:00 check: another meeting has ended by now and gets its transcript
        skipped = store.Store(self.home).meetings["E1"]
        self.assertEqual((skipped["skipped"], skipped["transcript"]), (True, ""))
        self.assertIn("Product sync — skipped", self.notes("list"))

    def test_over_the_audio_budget_it_waits_without_downloading(self):
        self.config(daily_audio_minutes=0)
        self.smriti(force=True)
        self.notes("product sync summary")
        self.smriti()
        self.assertEqual(self.audio_calls(), [])
        self.assertFalse(any("/recordings/R1/content" in c.url for c in self.http.calls))
        self.assertIn("today's budget has 0 left", self.recap_text())

    def test_a_meeting_with_nothing_recorded_is_reported_once_after_a_day(self):
        self.recordings, self.transcripts = [], []
        self.smriti(force=True)
        self.notes("product sync summary tasks")
        self.assertEqual(self.smriti(), "")  # Teams may still be processing
        self.clock.t += 25 * 3600
        late = self.smriti()
        self.assertEqual(late.count("no recording or transcript"), 1, late)
        self.assertIn("failed: Teams has no recording or transcript", self.recap_text())

    def test_a_name_matching_two_meetings_is_never_guessed(self):
        self.events.append(event("E5", "Product review", "10:00", "10:30"))
        self.smriti(force=True)
        reply = self.notes("product summary")
        self.assertIn("“product” matches 2 meetings", reply)
        self.assertEqual(store.Store(self.home).open_requests(), [])

    def recap_text(self) -> str:
        session = mock.Mock(local_now=datetime.fromtimestamp(self.clock.t, IST))
        return "\n".join(line.text for line in parts.meetings(session, self.home))


class Parsing(unittest.TestCase):
    def test_what_to_make_is_read_from_the_words(self):
        ask = chat.parse("product sync summary tasks prd claude")
        self.assertEqual((ask.meeting, ask.kinds, ask.model), ("product sync", ("summary", "tasks", "prd"), "claude"))
        doc = chat.parse("onboarding doc client follow-up email")
        self.assertEqual((doc.meeting, doc.kinds, doc.what, doc.model), ("onboarding", ("doc",), "client follow-up email", "gemini"))
        self.assertTrue(chat.parse("last skip").skip)
        self.assertEqual(chat.parse("product sync summary").model, "gemini")  # claude only when written
        self.assertIsNone(chat.parse("summary"))  # no meeting named

    def test_noise_only_turns_are_dropped(self):
        turns = transcribe.parse_turns("[00:00] Speaker 1: [unclear]\n[no speech]\n[00:05] Speaker 2: Haan [unclear] theek", 60)
        self.assertEqual([(t.start, t.speaker, t.text) for t in turns], [(65, "Speaker 2", "Haan [unclear] theek")])

    def test_transcript_sessions_join_on_one_clock_in_time_order(self):
        first, second = datetime(2026, 11, 23, 13, 0), datetime(2026, 11, 23, 13, 15)
        cues = vtt.join([(second, SESSION_2), (first, SESSION_1)])
        self.assertEqual(cues[0].speaker, "Asha Verma")
        self.assertEqual(cues[-1].start, 15 * 60 + 1)
        text = vtt.render(cues, [15 * 60])
        self.assertIn("--- transcription restarted at 15:00 ---\n[15:01] Asha Verma: We are back.", text)


if __name__ == "__main__":
    unittest.main()
