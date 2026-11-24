"""Stock b-roll (broll.py) against fake Pexels and Pixabay.

The promises tested: a ``stock:`` image scene gets a portrait clip tall enough, downloaded once and
credited; Pexels down means Pixabay is asked; no key, b-roll off or nothing found draws a title card and
says why, never failing the video; the writer offers image scenes only when footage can be searched, and
then only as ``stock:``; ``stock:`` is for image scenes only.

Run: python3 orchestrator/studio/tests/test_broll.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator/brief/tests"))

from fakes import FakeHttp, http_error

from orchestrator.studio import broll, profile, storyboard, writer
from orchestrator.studio.settings import Keys

PEXELS_VIDEOS = {"videos": [
    {"duration": 2, "url": "https://pexels.com/v/1", "user": {"name": "Too Short"},
     "video_files": [{"width": 1080, "height": 1920, "link": "https://cdn/short.mp4"}]},
    {"duration": 12, "url": "https://pexels.com/v/2", "user": {"name": "Asha"},
     "video_files": [{"width": 1920, "height": 1080, "link": "https://cdn/landscape.mp4"},
                     {"width": 2160, "height": 3840, "link": "https://cdn/4k.mp4"},
                     {"width": 1080, "height": 1920, "link": "https://cdn/hd.mp4"}]},
]}
PIXABAY_VIDEOS = {"hits": [{"duration": 9, "user": "ravi", "pageURL": "https://pixabay.com/v/9",
                            "videos": {"large": {"width": 1080, "height": 1920, "url": "https://px/clip.mp4"}}}]}
BOARD = {"title": "t", "scenes": [{"type": "image", "say": "Look at this.", "src": "stock:mumbai street at night",
                                   "caption": "Mumbai"},
                                  {"type": "title", "say": "Done.", "text": "end"}]}


class BrollTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home)
        self.look = profile.load("default", self.home)
        self.board = storyboard.parse(BOARD, self.home)

    def test_a_tall_portrait_clip_is_fetched_once_and_credited(self):
        http = (FakeHttp().on("GET", "https://api.pexels.com/videos/search", PEXELS_VIDEOS)
                .on("GET", "https://cdn/hd.mp4", b"clip"))
        board, notes = broll.resolve(http, Keys(pexels="k"), self.home, self.board, self.look)
        src = Path(board.scenes[0].fields["src"])
        self.assertEqual(src.read_bytes(), b"clip")  # the smallest portrait file ≥ 1280 tall, from a long enough video
        self.assertEqual(notes, ("scene 1 b-roll: Video by Asha on Pexels (https://pexels.com/v/2)",))
        again, _ = broll.resolve(http, Keys(pexels="k"), self.home, self.board, self.look)
        self.assertEqual(again.scenes[0].fields["src"], str(src))
        self.assertEqual(http.count("https://api.pexels.com"), 1)  # cached: searched once

    def test_pexels_down_means_pixabay(self):
        http = (FakeHttp().on("GET", "https://api.pexels.com", http_error(503))
                .on("GET", "https://pixabay.com/api/videos/", PIXABAY_VIDEOS).on("GET", "https://px/clip.mp4", b"x"))
        _, notes = broll.resolve(http, Keys(pexels="k", pixabay="p"), self.home, self.board, self.look)
        self.assertIn("Video by ravi on Pixabay", notes[0])

    def test_without_footage_the_scene_becomes_a_title_card_and_says_why(self):
        board, notes = broll.resolve(FakeHttp(), Keys(), self.home, self.board, self.look)
        self.assertEqual((board.scenes[0].type, board.scenes[0].fields["text"]), ("title", "Mumbai"))
        self.assertIn("no PEXELS_API_KEY", notes[0])
        empty = FakeHttp().on("GET", "https://api.pexels.com", {"videos": [], "photos": []})
        board, notes = broll.resolve(empty, Keys(pexels="k"), self.home, self.board, self.look)
        self.assertEqual(board.scenes[0].type, "title")
        self.assertIn("nothing found", notes[0])

    def test_stock_is_for_image_scenes_only(self):
        with self.assertRaises(storyboard.StoryboardError):
            storyboard.parse({"scenes": [{"type": "meme", "say": "x.", "src": "stock:cat", "top": "a", "bottom": "b"}]},
                             self.home)

    def test_the_writer_offers_footage_only_when_it_can_be_searched(self):
        self.assertNotIn("image", writer.allowed_scenes(self.look))
        self.assertIn("image", writer.allowed_scenes(self.look, stock=True))
        self.assertIn('"stock:', writer.prompt(self.look, "notes about mumbai", 30, 80, stock=True))
        self.assertIn('No "src"', writer.prompt(self.look, "notes about mumbai", 30, 80))


if __name__ == "__main__":
    unittest.main()
