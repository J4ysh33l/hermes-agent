"""Stock b-roll (broll.py) against fake Pexels, Pixabay and Openverse.

The promises tested: a ``stock:`` image scene gets a portrait clip tall enough, downloaded once and
credited; Pexels down means Pixabay is asked; with no key, Openverse gives a CC0 photo that carries the
search's words (not the film premiere that tops a "bullet train" search) and is big enough; b-roll off or
nothing fitting draws a title card and says why, never failing the video; the writer offers image scenes
only as ``stock:`` and only when the page allows b-roll; ``stock:`` is for image scenes only.

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

from orchestrator.studio import brief, broll, profile, storyboard
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
OPENVERSE = "https://api.openverse.org/v1/images/"
PREMIERE = {"url": "https://up/premiere.jpg", "width": 2000, "height": 3000, "license": "cc0", "provider": "wikimedia",
            "title": "Brad Pitt at the premiere", "tags": [{"name": "premiere"}], "creator": "X",
            "foreign_landing_url": "https://w/1"}
TRAIN = {"url": "https://up/train.jpg", "width": 3024, "height": 4032, "license": "cc0", "provider": "wikimedia",
         "title": "Shinkansen bullet train at Tokyo station", "tags": [], "creator": "Kei",
         "foreign_landing_url": "https://w/2", "filetype": "jpg"}
SMALL = {**TRAIN, "url": "https://up/small.jpg", "width": 600, "height": 800}
TRAIN_BOARD = {"title": "t", "scenes": [{"type": "image", "say": "Look.", "src": "stock:bullet train"}]}
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

    def test_without_keys_openverse_gives_a_cc0_photo_that_matches_the_words(self):
        http = (FakeHttp().on("GET", OPENVERSE, {"results": [PREMIERE, SMALL, TRAIN]})
                .on("GET", "https://up/train.jpg", b"photo"))
        board = storyboard.parse(TRAIN_BOARD, self.home)
        found, notes = broll.resolve(http, Keys(), self.home, board, self.look)
        self.assertEqual(Path(found.scenes[0].fields["src"]).read_bytes(), b"photo")
        self.assertIn('Photo "Shinkansen bullet train at Tokyo station" by Kei via Openverse/wikimedia, CC0', notes[0])
        self.assertIn("license=cc0%2Cpdm", http.calls[0].url)  # only works nobody holds rights to

    def test_a_host_refusing_the_download_means_the_next_result_not_a_failed_video(self):
        second = {**TRAIN, "url": "https://flickr/train2.jpg", "title": "Bullet train", "creator": "Mo"}
        http = (FakeHttp().on("GET", OPENVERSE, {"results": [TRAIN, second]})
                .on("GET", "https://up/train.jpg", http_error(429)).on("GET", "https://flickr/train2.jpg", b"ok"))
        board = storyboard.parse(TRAIN_BOARD, self.home)
        found, notes = broll.resolve(http, Keys(), self.home, board, self.look)
        self.assertEqual(Path(found.scenes[0].fields["src"]).read_bytes(), b"ok")
        self.assertIn("by Mo", notes[0])
        refused = FakeHttp().on("GET", OPENVERSE, {"results": [TRAIN]}).on("GET", "https://up/", http_error(429))
        other = self.home / "other"
        other.mkdir()
        self.assertEqual(broll.resolve(refused, Keys(), other, board, self.look)[0].scenes[0].type, "title")

    def test_without_fitting_footage_the_scene_becomes_a_title_card_and_says_why(self):
        nothing = FakeHttp().on("GET", OPENVERSE, {"results": [PREMIERE]})
        board, notes = broll.resolve(nothing, Keys(), self.home, self.board, self.look)
        self.assertEqual((board.scenes[0].type, board.scenes[0].fields["text"]), ("title", "Mumbai"))
        self.assertIn("nothing fitting found", notes[0])
        offline = FakeHttp().on("GET", OPENVERSE, http_error(429))
        self.assertEqual(broll.resolve(offline, Keys(), self.home, self.board, self.look)[0].scenes[0].type, "title")
        (self.home / "studio/profiles").mkdir(parents=True)
        (self.home / "studio/profiles/quiet.yaml").write_text("elements:\n  broll: off\n", encoding="utf-8")
        _, notes = broll.resolve(FakeHttp(), Keys(), self.home, self.board, profile.load("quiet", self.home))
        self.assertIn("b-roll is off", notes[0])

    def test_flickr_sized_portraits_pass_but_small_landscapes_do_not(self):
        # Openverse serves Flickr photos at 1024 px at most: a portrait one fills the frame well enough
        tall = {**TRAIN, "url": "https://flickr/tall.jpg", "width": 683, "height": 1024}
        wide = {**TRAIN, "url": "https://flickr/wide.jpg", "width": 1024, "height": 683}
        found = broll.openverse_photo(FakeHttp().on("GET", OPENVERSE, {"results": [wide, tall]}), "-", "bullet train")
        self.assertEqual([f.url for f in found], ["https://flickr/tall.jpg"])

    def test_stock_is_for_image_scenes_only(self):
        with self.assertRaises(storyboard.StoryboardError):
            storyboard.parse({"scenes": [{"type": "meme", "say": "x.", "src": "stock:cat", "top": "a", "bottom": "b"}]},
                             self.home)

    def test_the_director_is_offered_footage_only_where_the_page_allows_it(self):
        script = {"title": "Mumbai", "hooks": [], "lines": []}
        self.assertIn("image", brief.allowed_scenes(self.look))
        self.assertIn('"stock:', brief.direction(self.look, "notes about mumbai", script, "j", False))
        (self.home / "studio/profiles").mkdir(parents=True)
        (self.home / "studio/profiles/quiet.yaml").write_text("elements:\n  broll: off\n", encoding="utf-8")
        quiet = profile.load("quiet", self.home)
        self.assertNotIn("image", brief.allowed_scenes(quiet))
        self.assertIn('No "src"', brief.direction(quiet, "notes about mumbai", script, "j", False))


if __name__ == "__main__":
    unittest.main()
