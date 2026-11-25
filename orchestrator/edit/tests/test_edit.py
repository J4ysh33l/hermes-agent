"""/edit: styles, sentences, the cut list, plan checks, captions, shots, the queue without Claude, and (when
ffmpeg is installed) ingest, the cut picture and the cut voice on a made-up clip.

The promises tested: a style states only what differs and a wrong value is refused by name; long pauses
shrink to the style's limit and never clip a word; the earlier of two takes is cut, a real repeat is not; a
lone "umm" goes, "toh" inside a sentence stays; the plan may not show a number that was not said, point at a
word that does not exist, overlap two cards or use a kind the style leaves out; captions follow the edited
clock and step aside for cards; punch-ins alternate; a job without Claude is still edited (cuts, captions);
the cut picture and the cut voice are the same length.

Run: python3 orchestrator/edit/tests/test_edit.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from orchestrator.edit import captions, cuts, media, plan as plans, queue, render, settings, style, watch, words
from orchestrator.edit.words import Word
import itertools

FFMPEG = shutil.which("ffmpeg") is not None


def talk(*sentences: str, gap: float = 0.1, pause: float = 0.6, start: float = 0.5) -> list[Word]:
    """Words 0.3 s long, ``gap`` apart, ``pause`` between sentences."""
    out, t = [], start
    for s in sentences:
        for w in s.split():
            out.append(Word(w, round(t, 3), round(t + 0.3, 3), 0.9))
            t += 0.3 + gap
        t += pause - gap
    return out


class Home:
    def __enter__(self) -> Path:
        self.dir = tempfile.TemporaryDirectory()
        return Path(self.dir.name)

    def __exit__(self, *exc) -> None:
        self.dir.cleanup()


class StyleTests(unittest.TestCase):
    def test_built_in_styles_load_and_mine_is_default(self) -> None:
        with Home() as home:
            self.assertEqual(style.names(home), ["aevy", "clean", "mine", "zero1"])
            mine = style.load("mine", home)
            self.assertEqual(mine["captions"]["font"], "manrope")  # Zero1 captions
            self.assertEqual(mine["title"]["font"], "newsreader")  # Aevy serif card
            self.assertEqual(mine["title"]["kind"], "card")
            self.assertEqual(mine["captions"]["script"], "latin")
            self.assertEqual(settings.Settings().style, "mine")

    def test_yours_extends_and_overrides(self) -> None:
        with Home() as home:
            path = style.create("brand", home, "mine")
            path.write_text("extends: mine\ngraphics:\n  accent: '#00AAFF'\n", encoding="utf-8")
            brand = style.load("brand", home)
            self.assertEqual(brand["graphics"]["accent"], "#00AAFF")
            self.assertEqual(brand["title"]["kind"], "card")

    def test_wrong_values_are_named(self) -> None:
        with Home() as home:
            folder = home / "edit" / "styles"
            folder.mkdir(parents=True)
            (folder / "bad.yaml").write_text("captions:\n  case: shouty\n", encoding="utf-8")
            with self.assertRaisesRegex(style.StyleError, "captions.case"):
                style.load("bad", home)
            (folder / "bad.yaml").write_text("graphics:\n  kinds: [stat, hologram]\n", encoding="utf-8")
            with self.assertRaisesRegex(style.StyleError, "hologram"):
                style.load("bad", home)


class CutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.look = style.load("mine", Path(self.home.name))

    def tearDown(self) -> None:
        self.home.cleanup()

    def test_sentences_by_stop_and_pause(self) -> None:
        ws = talk("Okay so here's the thing.", "Mocks are one part", "practice is the rest.", pause=0.9)
        found = words.sentences(ws)
        self.assertEqual([s.text for s in found], ["Okay so here's the thing.", "Mocks are one part", "practice is the rest."])
        self.assertIn("S2 [", words.numbered(found))

    def test_long_pauses_shrink_and_words_stay_whole(self) -> None:
        ws = talk("First line here.", "Second line here.", pause=2.0)
        cut = cuts.build(ws, words.sentences(ws), self.look)
        self.assertEqual(len(cut.ranges), 2)
        gap_kept = (cut.ranges[0].end - ws[2].end) + (ws[3].start - cut.ranges[1].start)
        self.assertLessEqual(gap_kept, self.look["pace"]["max_pause"] + 1e-6)
        for n in cut.kept_words:  # every kept word is inside a range
            self.assertTrue(any(r.start <= ws[n].start and ws[n].end <= r.end for r in cut.ranges))
        self.assertAlmostEqual(cut.to_output(ws[3].start), cut.ranges[0].seconds + (ws[3].start - cut.ranges[1].start), places=3)

    def test_retake_and_false_start_are_cut(self) -> None:
        ws = talk("The best way to prepare is practice.", "The best way to prepare is daily practice.", "Then review.")
        found = words.sentences(ws)
        self.assertIn(1, cuts.retakes(found))
        self.assertNotIn(2, cuts.retakes(found))
        ws = talk("So the", "So the real problem is time.", pause=0.8)
        self.assertIn(1, cuts.retakes(words.sentences(ws)))
        ws = talk("Practice daily.", "Review weekly.", "Rest on Sunday.")
        self.assertEqual(cuts.retakes(words.sentences(ws)), {})
        ws = talk("Pick your weakest section first.", "Pick your strongest section last.")
        self.assertEqual(cuts.retakes(words.sentences(ws)), {})  # one word in five different: two points, not a retake

    def test_the_plan_can_overrule_a_retake(self) -> None:
        ws = talk("Do it daily.", "Do it daily.")
        found = words.sentences(ws)
        self.assertIn(1, cuts.build(ws, found, self.look).dropped)
        self.assertNotIn(1, cuts.build(ws, found, self.look, keep_ids={1}).dropped)

    def test_fillers(self) -> None:
        ws = [Word("umm,", 0.0, 0.3), Word("ye", 0.6, 0.8), Word("toh", 0.85, 1.0), Word("sahi", 1.05, 1.3), Word("hai.", 1.35, 1.6)]
        self.assertEqual(cuts.fillers(ws, "alone"), {0})  # "toh" inside the sentence is grammar
        self.assertEqual(cuts.fillers(ws, "keep"), set())

    def test_words_cut_from_inside_and_speed(self) -> None:
        ws = talk("The best way to reduce costs of all these costs is prevention.")
        found = words.sentences(ws)
        cut = cuts.build(ws, found, self.look, cut={1: [(6, 9)]})
        self.assertEqual(" ".join(ws[n].text for n in cut.kept_words), "The best way to reduce costs is prevention.")
        self.assertGreater(len(cut.ranges), 1)
        fast = cuts.build(ws, found, self.look)
        fast.speed = 1.25
        self.assertAlmostEqual(fast.seconds * 1.25, sum(r.seconds for r in fast.ranges), places=6)
        self.assertAlmostEqual(fast.to_source(fast.to_output(ws[3].start)), ws[3].start, places=6)

    def test_plan_drop_and_trim(self) -> None:
        ws = talk("Hi guys welcome back.", "Mocks are not enough.", "Practice is.")
        found = words.sentences(ws)
        cut = cuts.build(ws, found, self.look, {1: "warm-up"}, {2: (1, 3)})
        kept = [ws[n].text for n in cut.kept_words]
        self.assertEqual(kept, ["Mocks", "are", "not", "Practice", "is."])


class PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.look = style.load("mine", Path(self.home.name))
        self.ws = talk("Here's the thing nobody tells you.", "Do the same questions 10 times.", "That is what matters.")
        self.found = words.sentences(self.ws)
        self.cut = cuts.build(self.ws, self.found, self.look)

    def tearDown(self) -> None:
        self.home.cleanup()

    def check(self, raw: dict) -> list[str]:
        return plans.check(plans.Plan.parse({"title": "Mocks alone won't do it", **raw}), self.found, self.cut, self.look)

    def test_director_moves_are_checked(self) -> None:
        ok = self.check({"graphics": [{"kind": "pop", "at": "S1.2", "text": "Nobody tells you"},
                                      {"kind": "split", "at": "S2.1", "to": "S2.6", "file": "demo.mp4"},
                                      {"kind": "hide", "at": "S2.1", "box": [0.1, 0.6, 0.3, 0.1]}]})
        self.assertEqual(ok, [])
        bad = self.check({"graphics": [{"kind": "split", "at": "S2.1"},
                                       {"kind": "hide", "at": "S2.1", "box": [0.9, 0.9, 0.5, 0.5]},
                                       {"kind": "pop", "at": "S3.1", "text": "a chip far too long to fit beside a face"}]})
        self.assertTrue(any("'query'" in p for p in bad))
        self.assertTrue(any("box must be" in p for p in bad))
        self.assertTrue(any("characters" in p for p in bad))

    def test_a_faceless_library_scene_can_fill_the_frame(self) -> None:
        chart = {"kind": "scene", "type": "library", "layout": "full", "at": "S2.1", "to": "S3.4",
                 "scene": {"type": "chart", "kind": "bar", "title": "Same *questions*", "labels": ["once", "ten times"],
                           "values": [1, 10]}, "beats": [{"at": "S2.1"}, {"at": "S2.5"}]}
        folder = Path(self.home.name) / "edit" / "styles"
        folder.mkdir(parents=True)
        (folder / "scenes.yaml").write_text("extends: mine\ngraphics:\n  kinds: [scene]\npace:\n  broll: 0.8\n", encoding="utf-8")
        self.look = style.load("scenes", Path(self.home.name))
        self.assertEqual(self.check({"graphics": [chart]}), [])
        wrong = self.check({"graphics": [{**chart, "layout": "panel"},
                                         {**chart, "at": "S1.1", "to": "S1.6", "scene": {"type": "chart", "kind": "pie"}},
                                         {**chart, "at": "S3.1", "beats": [{"at": "S1.1"}]}]})
        self.assertTrue(any("layout must be full" in p for p in wrong))
        self.assertTrue(any("kind" in p and "pie" in p or "must be one of" in p for p in wrong))
        self.assertTrue(any("outside the scene" in p for p in wrong))

    def test_a_plain_plan_gets_suggestions_not_refusal(self) -> None:
        ws = talk("Every morning the queue reaches the gate.", "Patients wait two hours for a token.",
                  "The receptionist writes each name by hand.", "Then billing asks for the same details again.",
                  "Files go missing between the wards.", "Doctors search for old reports on paper.",
                  "Claims get rejected for small errors.", "Nobody sees the whole picture of the day.",
                  "That is what we fixed first.", pause=0.2)
        found = words.sentences(ws)
        cut = cuts.build(ws, found, self.look)
        bare = plans.Plan.parse({"title": "Queues waste the morning", "punch": []})
        self.assertEqual(plans.check(bare, found, cut, self.look), [])  # no b-roll and no graphics is allowed
        self.assertTrue(any("nothing new on screen" in p for p in plans.advice(bare, found, cut, self.look)))

    def test_the_editor_is_told_what_the_camera_saw(self) -> None:
        face = [0.35, 0.25, 0.3, 0.17]
        samples = [{"t": float(t), "face": None if t in (8, 9) else face, "faces": 1, "light": 40.0 if t >= 6 else 130.0,
                    "sharp": 400.0, "motion": 2.0, "cut": t == 9} for t in range(14)]
        found = words.sentences(talk("First point is short.", "Second point runs a bit longer here.",
                                     "Third point is said in the dark.", pause=1.5))
        found = [words.Sentence(s.id, s.words, s.first) for s in found]
        text = watch.overview({"samples": samples}, "1080×1920", "sound: clean")
        self.assertIn("head and shoulders", text)
        self.assertIn("changes a lot", text)
        log = watch.log({"samples": samples}, found)
        self.assertEqual(len(log.splitlines()), len(found))
        self.assertTrue(any("dark" in line for line in log.splitlines()))
        self.assertEqual(watch.focus(Path("/nowhere"), 0, 1), (0.5, 0.42))

    def test_a_good_plan_passes(self) -> None:
        self.assertEqual(self.check({"graphics": [{"kind": "stat", "at": "S2.5", "text": "10× the same questions"},
                                                  {"kind": "emoji", "at": "S3.1", "emoji": "🔥"}]}), [])

    def test_invented_numbers_bad_anchors_overlaps_and_kinds(self) -> None:
        self.assertTrue(any("'99'" in p for p in self.check({"graphics": [{"kind": "stat", "at": "S2.1", "text": "99 %ile"}]})))
        self.assertTrue(any("S9" in p for p in self.check({"graphics": [{"kind": "stat", "at": "S9.1", "text": "x"}]})))
        self.assertTrue(any("6 words" in p for p in self.check({"graphics": [{"kind": "stat", "at": "S2.40", "text": "x"}]})))
        overlap = self.check({"graphics": [{"kind": "stat", "at": "S2.1", "text": "a"}, {"kind": "headline", "at": "S2.3", "text": "b"}]})
        self.assertTrue(any("overlap" in p for p in overlap))
        self.assertTrue(any("does not use cutaway" in p for p in plans.check(plans.Plan.parse({"title": "Mocks alone won't do it", "graphics": [{"kind": "cutaway", "at": "S2.1", "query": "desk"}]}), self.found, self.cut, style.load("zero1", Path(self.home.name)))))
        self.assertTrue(any("title" in p for p in plans.check(plans.Plan(title="Hi"), self.found, self.cut, self.look)))

    def test_basic_plan_and_punch_rhythm(self) -> None:
        chosen = plans.basic(self.found, self.look)
        self.assertEqual(chosen.title, "Here's the thing nobody tells you")
        ws = talk(*[f"Sentence number {n} goes here." for n in range(12)])
        found = words.sentences(ws)
        cut = cuts.build(ws, found, self.look)
        points = plans.punch_points(plans.Plan(), found, cut, self.look)
        outs = [cut.to_output(p) for p in points]
        self.assertTrue(points and all(b - a >= self.look["pace"]["punch_every"] for a, b in zip([0.0] + outs, outs)))
        shots = render._shots(cut, points, self.look, 30)
        self.assertEqual({s["zoom"] for s in shots}, {(1.0, 1.0), (self.look["pace"]["punch"],) * 2})
        self.assertAlmostEqual(sum(s["frames"] for s in shots) / 30, cut.seconds, delta=1 / 30)


class CaptionTests(unittest.TestCase):
    def test_pages_follow_the_edit_and_hide_for_cards(self) -> None:
        with Home() as home:
            look = style.load("mine", home)
            ws = talk("ye SIP aapko rich nahi banayega.", "Practice karo daily.", pause=2.0)
            cut = cuts.build(ws, words.sentences(ws), look)
            pages = captions.pages(ws, cut, look)
            self.assertTrue(all(len(p.words) <= look["captions"]["words"] + 1 for p in pages))
            self.assertEqual(" ".join(w for p in pages for w, _a, _b in p.words), "ye SIP aapko rich nahi banayega Practice karo daily")
            self.assertTrue(all(a.end <= b.start + 1e-6 for a, b in itertools.pairwise(pages)))
            self.assertLess(pages[-1].end, ws[-1].end)  # the 2 s pause was cut, so captions moved earlier
            hidden = captions.pages(ws, cut, look, [(0.0, 2.0)])
            self.assertTrue(all(p.start >= 1.5 for p in hidden))
            text = captions.ass(pages, look)
            self.assertIn("Manrope ExtraBold", text)
            self.assertIn("\\pos(540,1114)", text)


class QueueTests(unittest.TestCase):
    def test_a_job_without_the_director_waits_for_you(self) -> None:
        with Home() as home:
            (home / "brief").mkdir()
            (home / "brief" / "brief.yaml").write_text("edit:\n  approve: false\n", encoding="utf-8")
            job = queue.add(home, "/nowhere/clip.mp4", "mine", "CAT reel")
            ws = talk("Here's the thing nobody tells you.", "Practice the same questions.")
            (job.folder / "transcript.json").write_text(json.dumps({"words": [{"w": w.text, "s": w.start, "e": w.end} for w in ws]}))
            job.log("test", "transcribed")
            ctx = mock.Mock(home=home, edit=settings.Settings(approve=False), keys=mock.Mock(claude=""))
            ctx.settings.claude_via = "handoff"
            with mock.patch.object(queue, "_hand", return_value=mock.Mock(ready=False)), \
                    mock.patch.object(queue, "Telegram") as telegram:
                queue._plan(ctx, job)  # approve: false, yet a captions-only cut still asks first
            self.assertEqual(job.state, "approval")
            telegram.return_value.text.assert_called_once()
            saved = json.loads((job.folder / "plan.json").read_text())
            self.assertIn("NOT A FINISHED EDIT", saved["notes"])
            queue.cancel(home, job.id)
            self.assertEqual(queue.load(home, job.id).state, "cancelled")

    def test_wrong_style_or_source_is_refused_early(self) -> None:
        with Home() as home:
            with self.assertRaises(style.StyleError):
                queue.add(home, "x.mp4", "nope", "")
            job = queue.add(home, "ftp://x", "mine", "")
            with self.assertRaisesRegex(queue.QueueError, "anyone with the link"):
                queue.fetch(mock.Mock(), job)


@unittest.skipUnless(FFMPEG, "ffmpeg not installed")
class MediaTests(unittest.TestCase):
    def test_ingest_cut_picture_and_voice_match(self) -> None:
        with Home() as home:
            look = style.load("mine", home)
            src = home / "phone.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25", "-f", "lavfi", "-i",
                            "sine=f=220:sample_rate=44100", "-t", "6", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)],
                           check=True)
            job = home / "job"
            info = media.prepare(src, job, look, 30, 23, 2)
            self.assertEqual((info.width, info.height), (640, 360))
            made = media.probe(job / "source.mp4")
            self.assertEqual((made.width, made.height, round(made.fps)), (1080, 1920, 30))
            ws = talk("One two three four.", "Five six seven.", pause=1.5)
            found = words.sentences(ws)
            cut = cuts.build(ws, found, look)
            shots = render._shots(cut, [found[1].start], look, 30)
            base = render.build_base(job, shots, look, settings.Settings(threads=2))
            voice = render.cut_voice(job, cut)
            pic, snd = media.probe(base).seconds, float(json.loads(subprocess.run(
                ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", str(voice)], capture_output=True,
                text=True, check=True).stdout)["format"]["duration"])
            self.assertAlmostEqual(pic, snd, delta=1 / 30 + 0.01)
            self.assertAlmostEqual(pic, cut.seconds, delta=0.05)


if __name__ == "__main__":
    unittest.main()
