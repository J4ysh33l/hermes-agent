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

from orchestrator.studio import cover, profile, settings, storyboard, text, video, voice

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
        self.refused({"scenes": [{"type": "hologram", "say": "x."}]}, "type must be one of")
        self.refused({"scenes": [{"type": "title", "say": "x.", "text": "t", "colour": "red"}]}, "unknown key 'colour'")
        self.refused({"scenes": [{"type": "title", "text": "t"}]}, "scene 1.say is required")
        self.refused({"scenes": [{"type": "stat", "say": "x.", "value": "lots", "label": "l"}]}, "must be a number")
        self.refused({"scenes": [{"type": "image", "say": "x.", "src": "missing.png"}]}, "not found")
        self.refused({"scenes": [{"type": "bullets", "say": "x.", "items": []}]}, "list of 1 to")
        self.refused({"scenes": []}, "at least one scene")
        self.refused({"scenes": [{"type": "title", "say": "A *big deal.", "text": "t"}]}, "not closed")
        self.refused({"scenes": [{"type": "title", "say": "x.", "text": "t", "exit": "explode"}]}, "must be one of")
        self.refused({"scenes": [{"type": "title", "say": "x.", "text": "t", "transition": "spin"}]}, "must be one of")

    def test_a_scene_can_choose_how_it_hands_over_to_the_next(self):
        board = storyboard.parse({"scenes": [{"type": "title", "say": "One.", "text": "a", "transition": "burn"},
                                             {"type": "title", "say": "Two.", "text": "b"}]}, self.folder)
        said = [s for scene in board.scenes for s in text.sentences(scene.say)]
        job = self.folder / "job"
        job.mkdir()
        out = video.props(board, job, fake_speech(job, said), DEFAULT)
        self.assertEqual([s["transition"] for s in out["scenes"]], ["burn", ""])  # "" = the profile's
        self.assertEqual(out["profile"]["motion"]["transition"], "push")

    def test_the_newer_scene_types_are_checked_too(self):
        (self.folder / "messy.jpg").write_bytes(b"jpg")
        board = storyboard.parse({"scenes": [
            {"type": "terminal", "say": "Run it.", "lines": ["$ docker run nginx", "ok"]},
            {"type": "chart", "say": "Growth.", "labels": ["a", "b"], "values": [1, 2]},
            {"type": "diagram", "say": "Flow.", "nodes": ["A", "B"]},
            {"type": "quote", "say": "Quote.", "text": "Ship it."},
            {"type": "timeline", "say": "History.", "events": [{"when": "2013", "what": "x"}, {"when": "2014", "what": "y"}]},
            {"type": "clipping", "say": "News.", "source": "Daily", "headline": "A big shift", "highlight": "BIG shift"},
            {"type": "post", "say": "Post.", "name": "Priya", "text": "hi"},
            {"type": "meme", "say": "Meme.", "src": "crab.jpg", "bottom": "me"},
            {"type": "beforeafter", "say": "Before. After.", "before": {"label": "old", "src": "messy.jpg"},
             "after": {"label": "new"}},
            {"type": "logo", "say": "Docker.", "name": "Docker"}]}, self.folder)
        chart = board.scenes[1].fields
        self.assertEqual((chart["kind"], chart["highlight"]), ("bar", -1))  # defaults: bars, the largest lit
        self.assertEqual(storyboard.files(board.scenes[8].fields), ["messy.jpg"])  # nested files are found

    def test_the_newer_scene_types_refuse_what_cannot_be_drawn(self):
        self.refused({"scenes": [{"type": "chart", "say": "x.", "labels": ["a", "b"], "values": [1, 2, 3]}]},
                     "must pair up")
        self.refused({"scenes": [{"type": "chart", "say": "x.", "labels": ["a", "b"], "values": [1, 2],
                                  "kind": "pie"}]}, "must be one of")
        self.refused({"scenes": [{"type": "clipping", "say": "x.", "source": "s", "headline": "A big shift",
                                  "highlight": "huge"}]}, "not in the headline")
        self.refused({"scenes": [{"type": "beforeafter", "say": "x.", "before": {"label": "a", "src": "gone.jpg"},
                                  "after": {"label": "b"}}]}, "not found")
        self.refused({"scenes": [{"type": "timeline", "say": "x.", "events": [{"when": "1", "what": "a", "who": "b"},
                                                                             {"when": "2", "what": "c"}]}]},
                     "unknown key 'who'")

    def test_the_explainer_scenes_of_edit_work_in_a_faceless_short(self):
        board = storyboard.parse({"scenes": [
            {"type": "counter", "say": "Seventy percent.", "value": 70, "suffix": "%", "label": "paid out of *pocket*"},
            {"type": "stack", "say": "Who pays? Not insurance. You.", "title": "Who *pays*?",
             "rows": [{"text": "No insurance", "icon": "insurance", "mark": "cross"}, {"text": "You"}]},
            {"type": "points", "say": "The usual fixes. More cover. More money.", "title": "The usual *fixes*",
             "items": ["More cover", "More money"], "struck": True},
            {"type": "statement", "say": "Not the price. The chaos.",
             "lines": [{"text": "not the price", "strike": True}, {"text": "the *chaos*", "tone": "solution"}]},
            {"type": "steps", "say": "Book. Visit.", "steps": [{"label": "Book", "icon": "calendar"}, {"label": "Visit"}]},
            {"type": "bars", "say": "Small. Big.", "bars": [{"label": "Screen", "value": "₹1,000", "size": 0.1},
                                                         {"label": "Treat", "value": "₹5 lakh", "size": 1}]},
            {"type": "balance", "say": "Price or chaos.", "left": "Price", "right": "Chaos", "strike": "left"},
            {"type": "badge", "say": "Open every day.", "icon": "check", "text": "Open every day"}]}, self.folder)
        self.assertEqual(board.scenes[1].fields["rows"][1]["mark"], "none")  # defaults filled in for the renderer
        self.assertEqual(board.scenes[3].fields["lines"][1]["tone"], "solution")
        self.refused({"scenes": [{"type": "stack", "say": "x.", "rows": [{"text": "a", "icon": "unicorn"}, {"text": "b"}]}]},
                     "unknown icon")
        self.refused({"scenes": [{"type": "points", "say": "x.", "title": "t", "items": ["a" * 40, "b"]}]}, "at most 32")
        self.refused({"scenes": [{"type": "bars", "say": "x.", "bars": [{"label": "a", "value": "1", "size": 3},
                                                                        {"label": "b", "value": "2", "size": 1}]}]}, "from 0 to 1")

    def test_maps_name_countries_and_any_scene_may_carry_an_emoji(self):
        board = storyboard.parse({"scenes": [
            {"type": "map", "say": "India to Japan.", "highlight": ["India", "Japan"], "route": ["india", "Japan"],
             "emoji": "🔥"}]}, self.folder)
        self.assertEqual(board.scenes[0].emoji, "🔥")
        self.assertEqual(storyboard.countries(board.scenes[0].fields), ["India", "Japan", "india", "Japan"])
        self.refused({"scenes": [{"type": "map", "say": "x."}]}, "needs a focus, highlight or route")
        self.refused({"scenes": [{"type": "map", "say": "x.", "route": ["India"]}]}, "at least two")
        self.refused({"scenes": [{"type": "title", "say": "x.", "text": "t", "emoji": "this is not an emoji"}]},
                     "one emoji")

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


HAS_NODE = (video.PROJECT / "node_modules/.bin/esbuild").is_file() and shutil.which("node")

CAPTION_SCRIPT = """
import {pages, pageSize} from "%s/src/Captions";
import {DEFAULT_PROFILE} from "%s/src/theme";
const words = (s: string) => { let t = 0; return s.split(" ").map((text) => ({text, start: t, end: (t += 0.3) - 0.05, emphasis: false})); };
const lines: string[] = JSON.parse(process.argv[2]);
console.log(JSON.stringify(lines.map((s) => pages(words(s), 3).map((p) => ({words: p.map((w) => w.text),
  size: pageSize(p, DEFAULT_PROFILE.captions)})))));
"""


@unittest.skipUnless(HAS_NODE, "remotion not installed (install.sh)")
class CaptionPagesTest(unittest.TestCase):
    """The caption pages as Captions.tsx builds them (bundled with esbuild, run in node)."""

    def paged(self, *lines: str) -> list[list[dict]]:
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        (folder / "run.ts").write_text(CAPTION_SCRIPT % (video.PROJECT, video.PROJECT), encoding="utf-8")
        bin_ = video.PROJECT / "node_modules/.bin/esbuild"
        subprocess.run([str(bin_), str(folder / "run.ts"), "--bundle", "--platform=node", "--log-level=error",
                        "--external:remotion", "--external:react", "--loader:.css=empty",
                        f"--outfile={folder / 'run.js'}"], check=True, timeout=120)
        done = subprocess.run(["node", str(folder / "run.js"), json.dumps(lines)], capture_output=True, text=True,
                              check=True, timeout=60, env={**os.environ, "NODE_PATH": str(video.PROJECT / "node_modules")})
        return json.loads(done.stdout)

    def test_pages_follow_phrases_with_no_lone_words_or_dangling_articles(self):
        save, bun, wow = self.paged("Save the world today.",
                                    "Bun installs packages twenty five times faster than npm, and nobody noticed.",
                                    "Wow.")
        self.assertEqual([p["words"] for p in save], [["Save", "the", "world", "today."]])  # not 3 + 1
        texts = [p["words"] for p in bun]
        self.assertIn(["faster", "than", "npm,"], texts)  # the comma ends a page
        self.assertTrue(all(len(p) >= 2 for p in texts))
        self.assertTrue(all(p[-1].lower() not in ("the", "of", "to", "a") for p in texts))
        self.assertEqual([p["words"] for p in wow], [["Wow."]])  # a one-word sentence stays one word

    def test_a_word_too_long_for_the_width_shrinks_its_page_only(self):
        long_, short = self.paged("Supercalifragilistic internationalization happens.", "Ship it now.")
        self.assertLess(long_[0]["size"], 70)
        self.assertEqual(short[0]["size"], 92)  # the profile's size when it fits


class PropsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        (self.folder / "crab.jpg").write_bytes(b"jpg")
        self.job = self.folder / "job"
        self.job.mkdir()

    def test_scenes_start_with_their_first_sentence_and_items_get_beats(self):
        board = storyboard.parse(ALL_TYPES, self.folder)
        said = [s for scene in board.scenes for s in text.sentences(scene.say)]
        out = video.props(board, self.job, fake_speech(self.job, said), DEFAULT)
        self.assertEqual([s["start"] for s in out["scenes"]], [0.0, 1.25, 5.0, 6.25, 7.5, 8.75])
        self.assertEqual(out["scenes"][1]["beats"], [0.0, 1.25, 2.5])  # "Why?" then one sentence per item
        self.assertEqual(out["scenes"][4]["src"], "assets/04-crab.jpg")
        self.assertTrue((self.job / "assets/04-crab.jpg").is_file())
        self.assertGreater(out["seconds"], 10.0)

    def test_nested_files_travel_with_the_job(self):
        (self.folder / "messy.jpg").write_bytes(b"jpg")
        board = storyboard.parse({"scenes": [{"type": "beforeafter", "say": "Before. After.",
                                              "before": {"label": "old", "src": "messy.jpg"},
                                              "after": {"label": "new"}}]}, self.folder)
        out = video.props(board, self.job, fake_speech(self.job, ["Before.", "After."]), DEFAULT)
        self.assertEqual(out["scenes"][0]["before"]["src"], "assets/00-messy.jpg")
        self.assertEqual(out["scenes"][0]["after"]["src"], "")
        self.assertTrue((self.job / "assets/00-messy.jpg").is_file())

    def test_a_word_unit_stands_off_the_number_and_a_symbol_stays_on(self):
        # " crore" was trimmed to "crore": the video showed "120.0crore"
        def unit(suffix: str, prefix: str = "") -> tuple[str, str]:
            scene = {"type": "stat", "say": "One.", "value": 1, "label": "l", "suffix": suffix, "prefix": prefix}
            fields = storyboard.parse({"scenes": [scene]}, self.folder).scenes[0].fields
            return fields["prefix"], fields["suffix"]
        self.assertEqual(unit(" crore"), ("", " crore"))
        self.assertEqual(unit("km"), ("", " km"))
        self.assertEqual(unit("x"), ("", "x"))
        self.assertEqual(unit("%", "₹"), ("₹", "%"))
        self.assertEqual(unit("", "Rs"), ("Rs ", ""))

    def test_a_counters_own_start_does_not_move_the_scene(self):
        # a counter's "start" is the number it counts from; it once overwrote the scene's start time (0 s)
        board = storyboard.parse({"scenes": [{"type": "title", "say": "First.", "text": "a"},
                                             {"type": "counter", "say": "Then *38* of them.", "value": 38, "start": 5,
                                              "label": "of them"}]},
                                 self.folder)
        out = video.props(board, self.job, fake_speech(self.job, ["First.", "Then 38 of them."]), DEFAULT)
        counter = out["scenes"][1]
        self.assertGreater(counter["start"], 0.0)
        self.assertEqual(counter["count_from"], 5)

    def test_captions_show_the_script_as_written_in_order(self):
        board = storyboard.parse({"scenes": [{"type": "title", "say": "Doston yeh bahut important hai.",
                                              "text": "t"}]}, self.folder)
        out = video.props(board, self.job, fake_speech(self.job, ["दोस्तों ये बहुत इम्पॉर्टेंट है।"]), DEFAULT)
        self.assertEqual([w["text"] for w in out["words"]], ["Doston", "yeh", "bahut", "important", "hai."])
        times = [(w["start"], w["end"]) for w in out["words"]]
        self.assertEqual(times[0][0], 0.0)
        self.assertAlmostEqual(times[-1][1], 1.0, places=2)
        self.assertTrue(all(a[1] <= b[0] + 1e-6 for a, b in pairwise(times)))

    def test_a_beat_stays_silent_on_screen_and_directions_are_never_captioned(self):
        board = storyboard.parse({"scenes": [{"type": "title", "say": "And the winner is [beat] *India*.",
                                              "text": "t"}]}, self.folder)
        self.assertEqual(board.scenes[0].say, "And the winner is [beat] India.")  # the voice gets the direction
        speech = voice.Speech(self.job / "voice.wav", 2.0, (("And the winner is India.", 0.0, 1.8),), 0,
                              (((0.0, 1.0), (1.4, 1.8)),))  # the voice paused 1.0 → 1.4
        words = video.props(board, self.job, speech, DEFAULT)["words"]
        self.assertEqual([w["text"] for w in words], ["And", "the", "winner", "is", "India."])
        self.assertAlmostEqual(words[3]["end"], 1.0, places=3)
        self.assertEqual((words[4]["start"], words[4]["emphasis"]), (1.4, True))

    def test_a_misspelt_direction_is_refused(self):
        with self.assertRaisesRegex(storyboard.StoryboardError, r"\[beet\] is not a direction"):
            storyboard.parse({"scenes": [{"type": "title", "say": "Wait [beet] for it.", "text": "t"}]}, self.folder)

    def test_a_voice_that_lost_sentences_stops_the_render(self):
        board = storyboard.parse({"scenes": [{"type": "title", "say": "One. Two.", "text": "t"}]}, self.folder)
        with self.assertRaises(video.VideoError):
            video.props(board, self.job, fake_speech(self.job, ["One."]), DEFAULT)


class CoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        (self.folder / "crab.jpg").write_bytes(b"jpg")
        self.board = storyboard.parse(ALL_TYPES, self.folder)

    def test_the_chosen_scene_arrives_whole_with_its_file(self):
        job = self.folder / "job"
        job.mkdir()
        out = cover.props(self.board, 1, "No GC needed", job, DEFAULT)
        self.assertEqual((out["scene"]["type"], out["words"]), ("bullets", "No GC needed"))
        self.assertEqual(out["scene"]["beats"], [0.0, 0.0, 0.0])  # every item already said
        self.assertEqual(cover.props(self.board, 4, "Meet Ferris", job, DEFAULT)["scene"]["src"], "assets/04-crab.jpg")
        args = cover.still_args(settings.Settings(video_browser="/x/chrome"), job, self.folder / "c.png")
        self.assertIn("still", args)
        self.assertIn(f"--frame={cover.FRAMES - 1}", args)
        self.assertIn("--browser-executable=/x/chrome", args)

    def test_too_many_words_or_a_missing_scene_are_refused_before_rendering(self):
        with self.assertRaisesRegex(cover.CoverError, "At most 5 words"):
            cover.make(None, settings.Keys(), settings.Settings(), self.folder, self.board, self.folder / "c.png", 1,
                       "one two three four five six")
        with self.assertRaisesRegex(cover.CoverError, "Scene 9\\?"):
            cover.make(None, settings.Keys(), settings.Settings(), self.folder, self.board, self.folder / "c.png", 9, "Rust")
        self.assertFalse((self.folder / "c.png").exists())


class CountryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        self.world = self.folder / "world.json"
        names = ["India", "Japan", "United States of America", "Pakistan"]
        self.world.write_text(json.dumps({"objects": {"countries": {"geometries": [
            {"properties": {"name": n}} for n in names]}}}), encoding="utf-8")

    def board(self, **map_fields):
        return storyboard.parse({"scenes": [{"type": "map", "say": "x.", **map_fields}]}, self.folder)

    def test_names_take_the_map_spelling_and_common_short_forms_work(self):
        fixed = video.check_countries(self.board(focus="india", route=["USA", "japan"]), self.world)
        self.assertEqual(fixed.scenes[0].fields["focus"], "India")
        self.assertEqual(fixed.scenes[0].fields["route"], ("United States of America", "Japan"))

    def test_an_unknown_country_is_refused_with_the_closest_names(self):
        with self.assertRaises(video.VideoError) as caught:
            video.check_countries(self.board(highlight=["Pakistn"]), self.world)
        self.assertIn("did you mean Pakistan", str(caught.exception))


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

    def test_the_directors_theme_recolours_one_video_and_keeps_the_rest(self):
        board = storyboard.parse({"title": "T", "theme": {"bg": "#1a0b2e", "panel": "#2b1548", "text": "#fdf4ff",
                                                          "muted": "#c4a7d9", "accent": "#ff5fa2", "cool": "#3ee6e0",
                                                          "font": "anton"},
                                  "scenes": [{"type": "title", "say": "Hi.", "text": "Hi"}]}, self.home)
        look = DEFAULT.with_theme(board.theme)
        theme = look.render_props()["theme"]
        self.assertEqual((theme["bg"], theme["accent"], theme["font"]), ("#1a0b2e", "#ff5fa2", "anton"))
        self.assertEqual(theme["glow"], "#35153c")  # mixed from the new bg and accent, not the house navy
        self.assertEqual(theme["mono"], DEFAULT.section("theme")["mono"])
        self.assertEqual(look.render_props()["motion"], DEFAULT.render_props()["motion"])
        self.assertIs(DEFAULT.with_theme({}), DEFAULT)
        with self.assertRaises(storyboard.StoryboardError):
            storyboard.parse({"title": "T", "theme": "pink", "scenes": [{"type": "title", "say": "Hi.", "text": "Hi"}]},
                             self.home)

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
