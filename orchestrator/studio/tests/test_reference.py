"""A page profile from a reference video (reference.py), on videos ffmpeg makes for the test.

The promises tested: a fast-cut video gives hard cuts and strong punch-ins, a slow one fades; the
background is the reference's dark colour and the accent its vivid one (with enough contrast); the
length and pauses carry over; the profile written loads, and an existing one is not overwritten.

Run: python3 orchestrator/studio/tests/test_reference.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from hermes_platform.resolver import locate_command
from orchestrator.studio import profile, reference

HAS_FFMPEG = locate_command("ffmpeg").found and locate_command("ffprobe").found


def make(path: Path, shot: float, shots: int) -> Path:
    """A navy/plum video with an orange box, the whole frame changing every ``shot`` seconds (a cut), and a
    tone that stops for 0.4 s once a second (pauses)."""
    seconds = shot * shots
    spans = [f"between(t,{n * shot},{(n + 1) * shot - 0.001})" for n in range(shots)]
    boxes = ",".join(  # every other shot on a dark plum background, the orange box somewhere else each time
        [f"drawbox=x=0:y=0:w=iw:h=ih:color=0x2a1030:t=fill:enable='{s}'" for s in spans[1::2]] +
        [f"drawbox=x={20 + (n % 2) * 200}:y={100 + (n % 3) * 250}:w=300:h=420:color=0xff7a1a:t=fill:enable='{s}'"
         for n, s in enumerate(spans)])
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x0d1530:s=540x960:r=30:d={seconds}",
                    "-f", "lavfi", "-i", f"aevalsrc='0.4*sin(2*PI*220*t)*lt(mod(t,1),0.6)':s=24000:d={seconds}",
                    "-vf", boxes, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(path)], check=True)
    return path


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class ReferenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home)

    def test_a_fast_cutter_becomes_a_profile_with_its_pace_and_colours(self):
        path, summary = reference.write(make(self.home / "fast.mp4", 0.8, 15), "fastpage", self.home)
        look = profile.load("fastpage", self.home)
        motion, theme = look.section("motion"), look.section("theme")
        self.assertEqual((motion["transition"], motion["punch"]), ("cut", 0.14))
        bg, accent = theme["bg"], theme["accent"]
        self.assertLess(int(bg[1:3], 16) + int(bg[3:5], 16) + int(bg[5:7], 16), 150)  # dark navy
        self.assertGreater(int(accent[1:3], 16), 200)  # the orange
        self.assertLess(int(accent[5:7], 16), 90)
        self.assertEqual(look.section("writing")["seconds"], 12)
        self.assertAlmostEqual(look.section("voice")["pause"], 0.4, delta=0.1)
        self.assertIn("cuts", summary)
        self.assertIn("extends: default", path.read_text(encoding="utf-8"))
        with self.assertRaises(reference.ReferenceVideoError):
            reference.write(self.home / "fast.mp4", "fastpage", self.home)  # not overwritten without --force

    def test_a_slow_video_fades(self):
        reference.write(make(self.home / "slow.mp4", 6.0, 2), "slowpage", self.home)
        motion = profile.load("slowpage", self.home).section("motion")
        self.assertEqual((motion["transition"], motion["feel"]), ("fade", "soft"))


if __name__ == "__main__":
    unittest.main()
