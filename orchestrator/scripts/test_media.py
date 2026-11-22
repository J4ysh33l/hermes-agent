#!/usr/bin/env python3
"""Self-check for media/logoswap.py, compare.py and the editplan qc/music additions:  python3 test_media.py
Builds tiny synthetic media in a temp dir (needs ffmpeg + Pillow); touches nothing else."""
import json, re, subprocess, sys, tempfile, unittest
from pathlib import Path
from PIL import Image, ImageDraw

M = Path(__file__).parent / "media"

def sh(*cmd):
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, check=False)
    return p.returncode, p.stdout + p.stderr

def py(script, *args):
    return sh(sys.executable, "-I", M / script, *args)

def ff(*args):
    rc, out = sh("ffmpeg", "-v", "error", "-y", *args); assert rc == 0, out

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = d = Path(tempfile.mkdtemp())
        im = Image.new("RGB", (400, 300), (30, 120, 160)); ImageDraw.Draw(im).rectangle([20, 20, 141, 71], fill=(220, 30, 30))
        im.save(d / "a.png"); im.save(d / "b.jpg", quality=95)
        lg = Image.new("RGBA", (60, 60), (0, 0, 0, 0)); ImageDraw.Draw(lg).ellipse([0, 0, 59, 59], fill=(255, 255, 0, 255)); lg.save(d / "new.png")
        ff("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15:duration=6", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
           "-vf", "drawbox=x=10:y=10:w=100:h=40:color=red:t=fill", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", d / "v.mp4")
        (d / "m.json").write_text(json.dumps({"logo": "new.png", "rules": [
            {"match": "a.png", "box": [20, 20, 122, 52]}, {"match": "b.jpg", "box_pct": [0.05, 0.0667, 0.31, 0.175], "cover": "#ff00ff"},
            {"match": "v.mp4", "box": [10, 10, 100, 40], "start": 1, "end": 4}]}))

    def test_logoswap(self):
        d = self.d
        rc, out = py("logoswap.py", "swap", d / "m.json", d / "a.png", d / "b.jpg", d / "v.mp4", "--out", d / "o1")
        self.assertEqual(rc, 0, out)
        # video: swapped inside the window, original logo still there after it (the window is honoured)
        rc, out = py("compare.py", d / "v.mp4", d / "o1" / "v.mp4", "--at", "2", "--min-diff", "1", "--out", d / "c.png"); self.assertEqual(rc, 0, out)
        # QC must catch an unswapped copy, a missing rule, a box outside the frame, and --out == the originals' folder
        (d / "bad").mkdir(exist_ok=True); (d / "bad" / "a.png").write_bytes((d / "a.png").read_bytes())
        self.assertEqual(py("logoswap.py", "qc", d / "m.json", d / "a.png", "--out", d / "bad")[0], 1)
        (d / "m2.json").write_text(json.dumps({"logo": "new.png", "rules": [{"match": "a.png", "box": [390, 20, 120, 50]}]}))
        rc, out = py("logoswap.py", "swap", d / "m2.json", d / "a.png", d / "b.jpg", "--out", d / "o2"); self.assertEqual(rc, 1); self.assertIn("does not fit", out); self.assertIn("no rule", out)
        rc, out = py("logoswap.py", "swap", d / "m.json", d / "a.png", "--out", d); self.assertEqual(rc, 1); self.assertIn("originals", out)
        self.assertEqual(py("logoswap.py", "preview", d / "m.json", d / "v.mp4", "--out", d / "p.png", "--grid", "50")[0], 0)

    def test_compare(self):
        d = self.d; (d / "o1").mkdir(exist_ok=True)
        ch = Image.open(d / "a.png"); ImageDraw.Draw(ch).rectangle([20, 20, 140, 70], fill=(0, 0, 0)); ch.save(d / "o1" / "changed.png")   # 121x51 of 400x300 = 5.1%
        self.assertEqual(py("compare.py", d / "a.png", d / "a.png", "--out", d / "s0.png", "--max-diff", "0")[0], 0)
        rc, out = py("compare.py", d / "a.png", d / "o1" / "changed.png", "--out", d / "s1.png"); self.assertEqual(rc, 0)
        self.assertRegex(out, r"[1-9]\.\d\d% changed")                    # about 5%: the logo area
        self.assertEqual(py("compare.py", d / "a.png", d / "o1" / "changed.png", "--out", d / "s2.png", "--max-diff", "0.5")[0], 1)
        (d / "n").mkdir(exist_ok=True); (d / "n" / "changed.png").write_bytes((d / "a.png").read_bytes()); (d / "n" / "x.png").write_bytes((d / "a.png").read_bytes())
        rc, out = py("compare.py", d / "o1", d / "n", "--out", d / "sheets"); self.assertEqual(rc, 1); self.assertIn("only in", out)

    def test_editplan_qc(self):
        d = self.d; qc = lambda f, *a: py("editplan.py", "qc", f, *a)
        ff("-i", d / "v.mp4", "-f", "lavfi", "-i", "sine=frequency=440:duration=10", "-vf", "tpad=stop_mode=clone:stop_duration=4", "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", d / "frozen.mp4")
        ff("-i", d / "v.mp4", "-itsoffset", "0.6", "-i", d / "v.mp4", "-map", "0:v", "-map", "1:a", "-c", "copy", d / "late.mp4")
        ff("-i", d / "v.mp4", "-c:v", "copy", "-af", "atrim=0:4.5", "-c:a", "aac", d / "short.mp4")
        for f, bad in (("frozen.mp4", "FAIL frozen picture"), ("late.mp4", "FAIL a/v start offset"), ("short.mp4", "FAIL a/v length")):
            rc, out = qc(d / f); self.assertEqual(rc, 1); self.assertIn(bad, out, f)
        (d / "plan.json").write_text(json.dumps({"source": "v.mp4", "output": {"fps": 15}, "segments": [{"start": 0, "end": 3}, {"start": 4, "end": 6}]}))
        self.assertEqual(py("editplan.py", "render", d / "plan.json", "--out", d / "r.mp4")[0], 0)
        rc, out = qc(d / "r.mp4", "--plan", d / "plan.json"); self.assertEqual(rc, 0, out)          # a normal render passes every check
        self.assertEqual(qc(d / "frozen.mp4", "--max-freeze", "5")[1].count("PASS frozen"), 1)       # threshold is adjustable

    def test_music_duck(self):
        d = self.d
        ff("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15:duration=6", "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-af", "volume=enable='between(t,3,6)':volume=0",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", d / "voice.mp4")                 # voice only in the first 3 s
        ff("-f", "lavfi", "-i", "sine=frequency=880:duration=2", "-c:a", "libmp3lame", d / "bed.mp3")            # 2 s bed must loop over 6 s
        def music_level(duck, t0):
            (d / f"p{duck}.json").write_text(json.dumps({"source": "voice.mp4", "output": {"fps": 15, "loudnorm": False}, "segments": [{"start": 0, "end": 6}], "music": {"path": "bed.mp3", "gain_db": -12, "duck": duck}}))
            self.assertEqual(py("editplan.py", "render", d / f"p{duck}.json", "--out", d / f"m{duck}.mp4")[0], 0)
            out = sh("ffmpeg", "-hide_banner", "-ss", str(t0), "-t", "2", "-i", d / f"m{duck}.mp4", "-af", "bandpass=f=880:width_type=h:w=100,volumedetect", "-f", "null", "-")[1]
            return float(re.search(r"mean_volume: (-?[\d.]+) dB", out).group(1))
        self.assertGreater(music_level(True, 3.5) - music_level(True, 0.5), 3)        # ducked: bed is clearly quieter while the voice speaks
        self.assertLess(abs(music_level(False, 3.5) - music_level(False, 0.5)), 1)    # not ducked: same level both times (also proves the bed loops)
        (d / "pbad.json").write_text(json.dumps({"source": "voice.mp4", "segments": [{"start": 0, "end": 6}], "music": {"path": "nope.mp3"}}))
        self.assertEqual(py("editplan.py", "validate", d / "pbad.json")[0], 1)

if __name__ == "__main__":
    unittest.main(verbosity=2)
