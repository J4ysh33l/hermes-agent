"""/studio voice against a fake Kokoro (a stand-in for its environment), a fake Gemini and a fake
Telegram; plus one live run of the real Kokoro when STUDIO_KOKORO_PYTHON and STUDIO_KOKORO_MODELS
point at an installed one (install.sh).

The promises tested: each sentence goes to the voice for its script; Hinglish typed in Latin script is
put into Devanagari by Gemini first, and a rewrite that drops lines or stays in Latin script stops the
job; the clip reaches Telegram as a voice message; a missing Kokoro says how to install it.

Run: python3 orchestrator/studio/tests/test_studio.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator/brief/tests"))

from fakes import FakeHttp

from hermes_platform.resolver import locate_command
from orchestrator.studio import chat, settings, voice

GEMINI = "https://generativelanguage.googleapis.com/"
FAKE_KOKORO = """import json, sys, wave
job = json.load(sys.stdin)
json.dump(job, open(job["out"] + ".job.json", "w"))
rate, spans, at = 24000, [], 0.0
frames = b""
for line in job["lines"]:
    n = int(rate * 0.05 * len(line["text"].split()))
    spans.append([round(at, 3), round(at + n / rate, 3)])
    frames += b"\\x10\\x00" * n + b"\\x00\\x00" * int(rate * line["pause"])
    at += n / rate + line["pause"]
with wave.open(job["out"], "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(frames)
print(json.dumps({"seconds": round(len(frames) / 2 / rate, 3), "sample_rate": rate, "lines": spans}))
"""
HAS_FFMPEG = locate_command("ffmpeg").found


class Lines(unittest.TestCase):
    def test_hinglish_in_latin_script_is_told_apart_from_english_and_devanagari(self):
        self.assertTrue(voice.is_hinglish("Aaj hum baat karenge ki team tezi se kaise kaam karti hai."))
        self.assertTrue(voice.is_hinglish("Yeh product bahut accha hai, dekho."))
        for english in ("Most teams don't fail because the code is bad.", "Ship it to real users today.",
                        "नमस्ते दोस्तों, आज हम बात करेंगे।", "OK"):
            self.assertFalse(voice.is_hinglish(english), english)
        self.assertEqual(voice.sentences("One. Two!\nतीन। चार?"), ["One.", "Two!", "तीन।", "चार?"])


class Speaking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = mock.patch.dict("os.environ", {"HERMES_HOME": str(self.home)})
        self.env.start()
        (self.home / "brief").mkdir()
        (self.home / ".env").write_text("GEMINI_API_KEY=g\nTELEGRAM_BOT_TOKEN=t\nTELEGRAM_HOME_CHANNEL=42\n",
                                        encoding="utf-8")
        fake = self.home / "fake_kokoro.py"
        fake.write_text(FAKE_KOKORO, encoding="utf-8")
        python = self.home / "venvs/studio/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake}"\n', encoding="utf-8")  # ignores the worker path
        python.chmod(0o755)
        self.answers: list[list[str]] = []
        self.http = FakeHttp()
        self.http.on("POST", GEMINI, self._gemini)
        self.http.on("POST", "https://api.telegram.org/bott/sendVoice", {"ok": True})
        self.http.on("POST", "https://api.telegram.org/bott/sendDocument", {"ok": True})

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _gemini(self, _call):
        return {"candidates": [{"content": {"parts": [{"text": json.dumps({"lines": self.answers.pop(0)})}]}}]}

    def speak(self, text: str) -> voice.Speech:
        return voice.speak(self.http, "g", settings.Settings(), self.home, text, self.home / "out.wav")

    def job(self) -> dict:
        return json.loads((self.home / "out.wav.job.json").read_text(encoding="utf-8"))

    def test_each_sentence_gets_its_scripts_voice_and_hinglish_is_put_into_devanagari_first(self):
        self.answers = [["आज हम बात करेंगे कि छोटी टीम तेज़ी से प्रोडक्ट कैसे बना सकती है।"]]
        speech = self.speak("Here's the thing. Aaj hum baat karenge ki chhoti team tezi se product kaise bana "
                            "sakti hai. नमस्ते दोस्तों।")
        lines = self.job()["lines"]
        self.assertEqual([(ln["voice"], ln["lang"]) for ln in lines],
                         [("am_puck", "en-us"), ("hm_omega", "hi"), ("hm_omega", "hi")])
        self.assertEqual(lines[1]["text"], "आज हम बात करेंगे कि छोटी टीम तेज़ी से प्रोडक्ट कैसे बना सकती है।")
        self.assertEqual(speech.rewritten, 1)
        self.assertEqual(len(speech.lines), 3)
        self.assertGreater(speech.seconds, 0)
        with wave.open(str(speech.path)) as w:
            self.assertEqual((w.getframerate(), w.getnchannels()), (24000, 1))

    def test_a_rewrite_that_drops_lines_or_stays_latin_stops_before_anything_is_spoken(self):
        bad = ["Aaj hum baat karenge.", "doosri line"]
        self.answers = [bad, bad, bad]
        with self.assertRaisesRegex(voice.VoiceError, "Could not put the Hinglish lines into Devanagari"):
            self.speak("Aaj hum baat karenge ki team kaise kaam karti hai.")
        self.assertFalse((self.home / "out.wav").exists())

    def test_edge_gets_its_own_voices_and_is_picked_per_message(self):
        self.answers = [["आज हम बात करेंगे।"]]
        reply = chat.handle("voice edge Ship it today. Aaj hum baat karenge ki kya karna hai.", self.home, self.http)
        self.assertIn("🔊 Sent (edge)", reply)
        job = json.loads(next((self.home / "studio/voice").glob("*-edge.wav.job.json")).read_text(encoding="utf-8"))
        self.assertEqual(job["engine"], "edge")
        self.assertEqual([ln["voice"] for ln in job["lines"]], ["en-IN-PrabhatNeural", "hi-IN-MadhurNeural"])
        (self.home / "brief/brief.yaml").write_text("studio:\n  engine: edge\n", encoding="utf-8")
        self.assertIn("🔊 Sent (edge)", chat.handle("voice Ship it.", self.home, self.http))  # the default now

    def test_english_only_needs_no_model(self):
        self.speak("Most teams don't fail because the code is bad. They wait too long.")
        self.assertEqual(self.http.count(GEMINI), 0)

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
    def test_studio_voice_sends_a_voice_message(self):
        reply = chat.handle("voice Ship it today. Real users will tell you the truth.", self.home, self.http)
        self.assertIn("🔊 Sent (kokoro):", reply)
        self.assertEqual(self.http.count("https://api.telegram.org/bott/sendVoice"), 1)
        self.assertIn("/menu", chat.handle("help", self.home, self.http))

    def test_without_kokoro_it_says_how_to_install(self):
        (self.home / "venvs/studio/bin/python").unlink()
        self.assertIn("run orchestrator/studio/install.sh", chat.handle("voice Hello there.", self.home, self.http))


@unittest.skipUnless(os.environ.get("STUDIO_KOKORO_PYTHON") and os.environ.get("STUDIO_KOKORO_MODELS"),
                     "set STUDIO_KOKORO_PYTHON and STUDIO_KOKORO_MODELS to run the real Kokoro")
class RealKokoro(unittest.TestCase):
    def test_english_and_hindi_come_out_as_one_24khz_file_with_line_times(self):
        s = settings.Settings(studio_python=os.environ["STUDIO_KOKORO_PYTHON"],
                              models_dir=os.environ["STUDIO_KOKORO_MODELS"])
        with tempfile.TemporaryDirectory() as tmp:
            speech = voice.speak(FakeHttp(), "", s, Path(tmp), "Ship it today. नमस्ते दोस्तों।", Path(tmp) / "x.wav")
            self.assertEqual(len(speech.lines), 2)
            self.assertLess(speech.lines[0][2], speech.lines[1][1] + 0.01)
            with wave.open(str(speech.path)) as w:
                self.assertAlmostEqual(w.getnframes() / w.getframerate(), speech.seconds, delta=0.05)


if __name__ == "__main__":
    unittest.main()
