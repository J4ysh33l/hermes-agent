"""OmniVoice wiring (the model itself is not installed in tests): settings, the job the worker gets,
and the Whisper check's word match."""

import importlib.util
import sys
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


if __name__ == "__main__":
    unittest.main()
