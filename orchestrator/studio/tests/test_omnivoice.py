"""OmniVoice wiring (the model itself is not installed in tests): settings, the job the worker gets,
and the Whisper check's word match."""

import importlib.util
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from orchestrator.studio import settings, voice

spec = importlib.util.spec_from_file_location("voice_worker", ROOT / "orchestrator/studio/voice_worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class OmniVoice(unittest.TestCase):
    def test_settings(self):
        got = settings.parse({"studio": {"engine": "omnivoice", "omni_steps": 16, "omni_dtype": "fp32", "voice_check": ""}})
        self.assertEqual((got.engine, got.omni_steps, got.omni_dtype, got.voice_check), ("omnivoice", 16, "fp32", ""))
        self.assertEqual(settings.parse({}).omni_dtype, "bf16")

    def test_the_job_uses_the_voice_files_and_the_half_size_model_when_they_exist(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home)
        st = settings.Settings(engine="omnivoice")
        job = voice._omni_job(st, home)
        self.assertEqual((job["voice"], job["voice_hi"], job["omni_model"]), ("", "", ""))  # described voice, original model
        (home / "studio/voices").mkdir(parents=True)
        (home / "studio/voices/me.pt").write_bytes(b"x")
        (home / "studio/voices/me-hi.pt").write_bytes(b"x")
        (home / "studio/models/omnivoice-bf16").mkdir(parents=True)
        job = voice._omni_job(st, home)
        self.assertTrue(job["voice"].endswith("me.pt") and job["voice_hi"].endswith("me-hi.pt"))
        self.assertTrue(job["omni_model"].endswith("omnivoice-bf16"))
        self.assertEqual((job["steps"], job["check"], job["retries"]), (32, "small", 2))

    def test_whisper_check_tolerates_small_slips_not_wrong_words(self):
        line = "Here is what actually moves your *percentile* in the final 30 days. [beat]"
        self.assertTrue(worker._heard_right(line, "Here's what actually moves your percentile in the final 30 days."))
        self.assertFalse(worker._heard_right(line, "Here is what the tape to move 38 in the final days"))
        self.assertTrue(worker._heard_right("[pause 0.5]", ""))
        self.assertTrue(worker._heard_right("हर मॉक के बाद अपनी गलतियाँ लिखो.", "हर मौक के बाद अपनी गलतियां लिखो"))
        self.assertFalse(worker._heard_right("हर मॉक के बाद अपनी गलतियाँ लिखो.", "हर दिन पढ़ाई करो और सो जाओ"))


    def test_lines_are_spoken_as_paragraphs_of_one_language_and_speed(self):
        line = lambda text, lang="en-us", speed=1.0: {"text": text, "lang": lang, "speed": speed}
        lines = [line("One two three."), line("Four five."), line("नमस्ते दोस्तों.", "hi"), line("Six seven."),
                 line("Slow now.", speed=0.9), line("word " * 44), line("Last one.")]
        self.assertEqual(worker._paragraphs(lines), [[0, 1], [2], [3], [4], [5, 6]])  # "Last one." is too short alone
        self.assertEqual(worker._paragraphs(lines[:2] + lines[3:4]), [[0, 1, 2]])

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy not installed")
    def test_a_paragraph_is_cut_back_into_its_lines_in_the_silence_between_them(self):
        import numpy as np
        rate = worker.RATE
        loud = lambda s: np.full(int(s * rate), 0.5, dtype="float32")
        quiet = lambda s: np.zeros(int(s * rate), dtype="float32")
        audio = np.concatenate([loud(1.0), quiet(0.3), loud(1.0), quiet(0.2), loud(0.5)])  # 3 lines
        heard = [("most", 0.0, 0.4), ("aspirants", 0.4, 1.0), ("here", 1.25, 1.6), ("is", 1.6, 1.8),
                 ("what", 1.8, 2.3), ("pick", 2.55, 3.0)]
        pieces = worker._split(["Most aspirants.", "Here is what.", "Pick."], heard, audio)
        self.assertEqual([round(len(x) / rate, 2) for x in pieces], [1.03, 1.06, 0.51])  # its sound + 0.03 s: the silence each side is gated off
        breath = np.concatenate([loud(1.0), quiet(0.1), np.full(int(0.3 * rate), 0.02, dtype="float32"), loud(0.6)])
        heard2 = [("most", 0.0, 0.4), ("aspirants", 0.4, 1.0), ("pick", 1.4, 2.0)]
        _first, second = worker._split(["Most aspirants.", "Pick."], heard2, breath)
        self.assertLess(float(np.abs(second[: int(0.03 * rate)]).max()), 0.05)  # the inhale before "pick" is gone
        self.assertAlmostEqual(len(second) / rate, 0.66, places=2)
        self.assertIsNone(worker._split(["Most aspirants.", "Something else entirely here."], heard[:2], audio))


if __name__ == "__main__":
    unittest.main()
