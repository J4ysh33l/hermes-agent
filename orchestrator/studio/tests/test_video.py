"""/studio video: storyboard checks, how voice timings become scenes and captions, the render's quality
flags; plus one live render (real Kokoro + real Remotion) when STUDIO_KOKORO_PYTHON and
STUDIO_KOKORO_MODELS point at an installed voice and orchestrator/studio/remotion has node_modules
(STUDIO_BROWSER optionally names a Chrome headless shell).

The promises tested: a bad storyboard is refused before anything is spoken or rendered; each scene starts
when its first sentence starts; captions show the script as written (not the Devanagari the voice read)
and cover each sentence's time in order; list items get their sentences' start times; files a scene uses
travel with the job; the render asks for the configured quality; a missing Remotion says how to install it.

Run: python3 orchestrator/studio/tests/test_video.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from itertools import pairwise
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from orchestrator.studio import profile, settings, storyboard, video, voice

DEFAULT = profile.load("default", Path("/nowhere"))

ALL_TYPES = {"title": "Rust in 30 seconds",
             "scenes": [{"type": "title", "say": "Rust is fast.", "text": "Rust is fast", "kicker": "100s"},
                        {"type": "bullets", "say": "Why? No GC. Safe threads.", "title": "Why",
                         "items": ["No GC", "Safe threads"]},
                        {"type": "code", "say": "Here it is.", "code": "fn main() {}"},
                        {"type": "stat", "say": "Loved by most.", "value": 87, "suffix": "%", "label": "loved"},
                        {"type": "image", "say": "Meet Ferris.", "src": "crab.jpg"},
                        {"type": "compare", "say": "C plus plus or Rust.",
                         "left": {"label": "C++", "points": ["fast"]}, "right": {"label": "Rust", "points": ["safe"]}}]}


class StoryboardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        (self.folder / "crab.jpg").write_bytes(b"jpg")

    def refused(self, raw: dict, words: str) -> None:
        with self.assertRaises(storyboard.StoryboardError) as caught:
            storyboard.parse(raw, self.folder)
        self.assertIn(words, str(caught.exception))

    def test_every_scene_type_is_accepted(self):
        board = storyboard.parse(ALL_TYPES, self.folder)
        self.assertEqual([s.type for s in board.scenes], ["title", "bullets", "code", "stat", "image", "compare"])
        self.assertEqual(board.scenes[1].fields["items"], ("No GC", "Safe threads"))

    def test_mistakes_are_refused_before_anything_is_made(self):
        self.refused({"scenes": [{"type": "chart", "say": "x."}]}, "type must be one of")
        self.refused({"scenes": [{"type": "title", "say": "x.", "text": "t", "colour": "red"}]}, "unknown key 'colour'")
        self.refused({"scenes": [{"type": "title", "text": "t"}]}, "scene 1.say is required")
        self.refused({"scenes": [{"type": "stat", "say": "x.", "value": "lots", "label": "l"}]}, "must be a number")
        self.refused({"scenes": [{"type": "image", "say": "x.", "src": "missing.png"}]}, "not found")
        self.refused({"scenes": [{"type": "bullets", "say": "x.", "items": []}]}, "list of 1 to")
        self.refused({"scenes": []}, "at least one scene")
        self.refused({"scenes": [{"type": "title", "say": "A *big deal.", "text": "t"}]}, "not closed")
        self.refused({"scenes": [{"type": "title", "say": "x.", "text": "t", "exit": "explode"}]}, "must be one of")

    def test_emphasis_is_captioned_but_never_spoken(self):
        board = storyboard.parse({"scenes": [{"type": "title", "say": "It is *really fast* now.", "text": "t",
                                              "enter": "drop", "exit": "whip"}]}, self.folder)
        scene = board.scenes[0]
        self.assertEqual(scene.say, "It is really fast now.")
        self.assertEqual((scene.enter, scene.exit), ("drop", "whip"))
        words = video.word_times(scene.marked, 0.0, 1.0)
        self.assertEqual([(w["text"], w["emphasis"]) for w in words],
                         [("It", False), ("is", False), ("really", True), ("fast", True), ("now.", False)])


def fake_speech(job: Path, spoken: list[str]) -> voice.Speech:
    spans, at = [], 0.0
    for text in spoken:
        spans.append((text, at, at + 1.0))
        at += 1.25
    return voice.Speech(job / "voice.wav", at, tuple(spans), 0)


class PropsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        (self.folder / "crab.jpg").write_bytes(b"jpg")
        self.job = self.folder / "job"
        self.job.mkdir()

    def test_scenes_start_with_their_first_sentence_and_items_get_beats(self):
        board = storyboard.parse(ALL_TYPES, self.folder)
        said = [s for scene in board.scenes for s in voice.sentences(scene.say)]
        out = video.props(board, self.job, fake_speech(self.job, said), DEFAULT)
        self.assertEqual([s["start"] for s in out["scenes"]], [0.0, 1.25, 5.0, 6.25, 7.5, 8.75])
        self.assertEqual(out["scenes"][1]["beats"], [0.0, 1.25, 2.5])  # "Why?" then one sentence per item
        self.assertEqual(out["scenes"][4]["src"], "assets/04-crab.jpg")
        self.assertTrue((self.job / "assets/04-crab.jpg").is_file())
        self.assertGreater(out["seconds"], 10.0)

    def test_captions_show_the_script_as_written_in_order(self):
        board = storyboard.parse({"scenes": [{"type": "title", "say": "Doston yeh bahut important hai.",
                                              "text": "t"}]}, self.folder)
        out = video.props(board, self.job, fake_speech(self.job, ["दोस्तों ये बहुत इम्पॉर्टेंट है।"]), DEFAULT)
        self.assertEqual([w["text"] for w in out["words"]], ["Doston", "yeh", "bahut", "important", "hai."])
        times = [(w["start"], w["end"]) for w in out["words"]]
        self.assertEqual(times[0][0], 0.0)
        self.assertAlmostEqual(times[-1][1], 1.0, places=2)
        self.assertTrue(all(a[1] <= b[0] + 1e-6 for a, b in pairwise(times)))

    def test_a_voice_that_lost_sentences_stops_the_render(self):
        board = storyboard.parse({"scenes": [{"type": "title", "say": "One. Two.", "text": "t"}]}, self.folder)
        with self.assertRaises(video.VideoError):
            video.props(board, self.job, fake_speech(self.job, ["One."]), DEFAULT)


class ProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home)
        (self.home / "studio/profiles").mkdir(parents=True)

    def write(self, name: str, text: str) -> None:
        (self.home / "studio/profiles" / f"{name}.yaml").write_text(text, encoding="utf-8")

    def test_a_page_profile_states_only_what_differs(self):
        self.write("mypage", "extends: bold\ntheme:\n  accent: \"#00ff88\"\nvoice:\n  speed: 1.1\n")
        page = profile.load("mypage", self.home)
        self.assertEqual(page.section("theme")["accent"], "#00ff88")  # mine
        self.assertEqual(page.section("motion")["exit"], "whip")  # from bold
        self.assertEqual(page.section("theme")["mono"], "jetbrains")  # from default
        self.assertEqual(video.voiced(settings.Settings(), page).speed, 1.1)  # the page's voice is used
        self.assertEqual(page.render_props()["captions"]["font"], "anton")

    def test_your_profile_wins_over_a_built_in_one_of_the_same_name(self):
        self.write("bold", "motion:\n  exit: cut\n")
        self.assertEqual(profile.load("bold", self.home).section("motion")["exit"], "cut")

    def test_mistakes_are_named(self):
        for text, words in (("theme:\n  accent: yellow\n", "colour like"), ("motion:\n  wobble: 1\n", "unknown key"),
                            ("extends: nope\n", "No profile 'nope'"), ("elements:\n  memes: sometimes\n", "one of")):
            self.write("bad", text)
            with self.assertRaises(profile.ProfileError) as caught:
                profile.load("bad", self.home)
            self.assertIn(words, str(caught.exception))

    def test_off_written_bare_in_yaml_means_off(self):
        self.write("quiet", "elements:\n  music: off\n")
        self.assertEqual(profile.load("quiet", self.home).section("elements")["music"], "off")


class RenderTest(unittest.TestCase):
    def test_render_asks_for_the_configured_quality(self):
        s = settings.parse({"studio": {"video_crf": 16, "video_preset": "slower", "video_browser": "/x/chrome"}})
        args = video.render_args(s, Path("/job"), Path("/out.mp4"))
        for flag in ("--crf=16", "--x264-preset=slower", "--jpeg-quality=95", "--audio-bitrate=320k",
                     "--pixel-format=yuv420p", "--concurrency=1", "--browser-executable=/x/chrome"):
            self.assertIn(flag, args)

    def test_unknown_preset_is_refused(self):
        with self.assertRaises(ValueError):
            settings.parse({"studio": {"video_preset": "fastest"}})

    def test_without_remotion_it_says_how_to_install(self):
        board = storyboard.parse({"scenes": [{"type": "title", "say": "Hi.", "text": "t"}]}, Path("."))
        with mock.patch.object(video, "PROJECT", Path("/nowhere")), self.assertRaises(video.VideoError) as caught:
            video.make(None, "", settings.Settings(), Path(tempfile.gettempdir()), board, Path("x.mp4"))
        self.assertIn("install.sh", str(caught.exception))


LIVE_PY, LIVE_MODELS = os.environ.get("STUDIO_KOKORO_PYTHON", ""), os.environ.get("STUDIO_KOKORO_MODELS", "")


@unittest.skipUnless(LIVE_PY and LIVE_MODELS and (video.PROJECT / "node_modules/.bin/remotion").is_file(),
                     "live render: set STUDIO_KOKORO_PYTHON and STUDIO_KOKORO_MODELS, run install.sh")
class RealRenderTest(unittest.TestCase):
    def test_storyboard_to_vertical_short(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home)
        (home / "crab.jpg").write_bytes(subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=orange:s=540x960", "-frames:v", "1", "-f",
             "image2", "-c:v", "mjpeg", "pipe:1"], capture_output=True, check=True).stdout)
        board = storyboard.parse(ALL_TYPES, home)
        s = settings.parse({"studio": {"studio_python": LIVE_PY, "models_dir": LIVE_MODELS,
                                       "video_browser": os.environ.get("STUDIO_BROWSER", ""),
                                       "video_preset": "veryfast"}})
        made = video.make(None, "", s, home, board, home / "short.mp4")
        probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(made.path)],
                                          capture_output=True, text=True, check=True).stdout)["streams"]
        picture = next(p for p in probe if p["codec_type"] == "video")
        self.assertEqual((picture["width"], picture["height"], picture["r_frame_rate"]), (1080, 1920, "30/1"))
        self.assertTrue(any(p["codec_type"] == "audio" for p in probe))
        self.assertTrue(json.loads((made.job / "props.json").read_text())["words"])


if __name__ == "__main__":
    unittest.main()
