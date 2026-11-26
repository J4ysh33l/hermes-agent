"""Effects and music under the voice (sound.py), on real ffmpeg.

The promises tested: effects land on the cuts the transitions make (their peak in the overlap), on the
emoji and, only with ``always``, on list items; ``off`` means silence under the voice; music is used only
when music.yaml gives it a licence (and only for the profiles it names), and its credit travels in the
notes; the mixed track is as long as the video, and the music dips under the voice and comes back up in
the pauses.

Run: python3 orchestrator/studio/tests/test_sound.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator/brief/tests"))

from fakes import FakeHttp

from hermes_platform.resolver import locate_command
from orchestrator.studio import profile, sound

HAS_FFMPEG = locate_command("ffmpeg").found

OPENVERSE = "https://api.openverse.org/v1/audio/"
SONG = {"id": "abc123", "url": "https://cdn/loop.mp3", "duration": 95000, "license": "cc0", "provider": "freesound",
        "title": "Lofi chill loop", "tags": [{"name": "lofi"}], "creator": "holizna", "foreign_landing_url": "https://fs/1",
        "filetype": "mp3"}
SPOKEN = {**SONG, "id": "talk1", "title": "Lofi chill podcast intro", "url": "https://cdn/talk.mp3"}
SONG_BYTES = b"song" * 8000
SHORT = {**SONG, "id": "blip", "duration": 4000, "url": "https://cdn/blip.mp3"}

PROPS = {
    "profile": {"motion": {"transition": "push", "transition_frames": 8}},
    "words": [{"text": "big", "start": 2.4, "end": 2.7, "emphasis": True}],
    "scenes": [
        {"start": 0.0, "end": 2.0, "beats": [0.0], "transition": "", "emoji": ""},
        {"start": 2.0, "end": 4.0, "beats": [0.0, 0.8, 1.4], "transition": "flash", "emoji": "🔥",
         "items": ["a", "b"]},
        {"start": 4.0, "end": 6.0, "beats": [0.0], "transition": "", "emoji": ""},
    ],
}


def look(home: Path, name: str, sfx: str, music: str) -> profile.Profile:
    (home / "studio/profiles").mkdir(parents=True, exist_ok=True)
    (home / "studio/profiles" / f"{name}.yaml").write_text(
        f"extends: default\nelements:\n  sfx: {sfx}\n  music: {music}\n", encoding="utf-8")
    return profile.load(name, home)


class CueTest(unittest.TestCase):
    def test_effects_follow_the_cuts_the_emoji_and_with_always_the_items(self):
        auto = sound.cues(PROPS, "auto")
        self.assertEqual([c.name for c in auto], ["whoosh", "pop", "hit"])
        whoosh, pop, hit = auto
        peak = whoosh.at + sound.EFFECTS["whoosh"][2]
        self.assertAlmostEqual(peak, 2.0 + 8 / 30 / 2, places=3)  # mid-overlap of the push into scene 2
        self.assertAlmostEqual(pop.at, 2.4)  # the emoji lands on the emphasised word
        self.assertAlmostEqual(hit.at, 4.0 + 8 / 30 / 2, places=3)  # this scene asked for a flash
        ticks = [c.at for c in sound.cues(PROPS, "always") if c.name == "tick"]
        self.assertEqual(ticks, [2.8, 3.4])  # the two items' sentences
        self.assertEqual(sound.cues(PROPS, "off"), [])


class MusicLibraryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        self.http = FakeHttp().on("GET", OPENVERSE, {"results": []})
        self.addCleanup(shutil.rmtree, self.home)
        self.folder = self.home / "studio/music"
        self.folder.mkdir(parents=True)
        for name in ("free.mp3", "nolicence.mp3", "paperonly.mp3"):
            (self.folder / name).write_bytes(b"x")
        (self.folder / "music.yaml").write_text(
            "- {file: free.mp3, licence: CC0, credit: Free Song by Someone}\n"
            "- {file: nolicence.mp3}\n"
            "- {file: paperonly.mp3, licence: CC0, profiles: [paper]}\n"
            "- {file: missing.mp3, licence: CC0}\n", encoding="utf-8")

    def test_only_licensed_tracks_for_this_profile_are_used_and_credited(self):
        listed = sound.library(self.home)
        refused = dict(t for t in listed if isinstance(t, tuple))
        self.assertEqual(refused, {"nolicence.mp3": "no licence given", "missing.mp3": "file not found in the music folder"})
        chosen = sound.plan(self.http, self.home, look(self.home, "mine", "auto", "auto"), PROPS, "a title")
        self.assertEqual(chosen.music.path.name, "free.mp3")  # paperonly is for the paper profile
        self.assertEqual(chosen.notes, ("music: Free Song by Someone (CC0)",))

    def test_with_no_library_a_cc0_track_is_found_for_the_page_and_kept(self):
        (self.folder / "music.yaml").unlink()
        self.http = (FakeHttp().on("GET", OPENVERSE, {"results": [SPOKEN, SHORT, SONG]})
                     .on("GET", "https://cdn/loop.mp3", SONG_BYTES))
        chosen = sound.plan(self.http, self.home, look(self.home, "mine", "auto", "auto"), PROPS, "t")
        self.assertEqual(chosen.music.path.read_bytes(), SONG_BYTES)  # not the talk, not the 4 s blip
        self.assertIn('Music "Lofi chill loop" by holizna via Openverse/freesound, CC0', chosen.notes[0])
        self.assertIn("lofi chill", self.http.calls[0].url.replace("+", " "))  # the default profile's music_query
        again = sound.plan(self.http, self.home, look(self.home, "mine", "auto", "auto"), PROPS, "t")
        self.assertEqual(again.music.path, chosen.music.path)
        self.assertEqual(self.http.count(OPENVERSE), 1)  # kept in music.yaml: searched once

    def test_no_library_means_no_music_and_always_says_so(self):
        (self.folder / "music.yaml").unlink()
        self.assertEqual(sound.plan(self.http, self.home, look(self.home, "a", "auto", "auto"), PROPS, "t").notes, ())
        said = sound.plan(self.http, self.home, look(self.home, "b", "auto", "always"), PROPS, "t").notes
        self.assertIn("no music", said[0])
        self.assertIsNone(sound.plan(self.http, self.home, look(self.home, "c", "off", "off"), PROPS, "t").music)


def _loudness(path: Path, start: float, length: float, only: str = "") -> float:
    """Mean volume over a stretch; ``only`` = a filter first (e.g. a band-pass to hear the music alone)."""
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", str(start), "-t", str(length), "-i", str(path),
                          "-af", f"{only + ',' if only else ''}volumedetect", "-f", "null", "-"], capture_output=True, text=True, check=True).stderr
    return float(re.findall(r"mean_volume: (-?[\d.]+) dB", log)[-1])


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class MixTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        self.http = FakeHttp().on("GET", OPENVERSE, {"results": []})
        self.addCleanup(shutil.rmtree, self.home)
        music = self.home / "studio/music"
        music.mkdir(parents=True)
        # a steady 2 s "song" (looped to the video) and a "voice" speaking 0–2 s, silent 2–4 s, speaking 4–5 s
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=330:d=2", "-ac", "2",
                        str(music / "bed.wav")], check=True)
        (music / "music.yaml").write_text("- {file: bed.wav, licence: CC0}\n", encoding="utf-8")
        self.voice = self.home / "voice.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "aevalsrc='0.5*sin(2*PI*2000*t)*(lt(t,2)+gte(t,4))':s=24000:d=5", str(self.voice)], check=True)

    def test_the_music_ducks_under_the_voice_and_the_track_lasts_the_video(self):
        chosen = sound.plan(self.http, self.home, look(self.home, "m", "off", "auto"), PROPS, "t")
        out = sound.mix(self.home, self.voice, chosen, 6.0, self.home / "mix.wav")
        seconds = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                        "csv=p=0", str(out)], capture_output=True, text=True, check=True).stdout)
        self.assertAlmostEqual(seconds, 6.0, delta=0.05)
        music_only = _loudness(out, 2.6, 1.2)  # the pause: the bed back up
        self.assertGreater(music_only, -45)  # the music is there in the pause
        self.assertLess(_loudness(out, 5.5, 0.4), music_only)  # and fades out at the end
        song = "bandpass=f=330:width_type=q:w=8,bandpass=f=330:width_type=q:w=8"  # the song alone (voice: 2 kHz)
        self.assertGreater(_loudness(out, 2.6, 1.2, song) - _loudness(out, 0.5, 1.2, song), 6)  # ducked under words

    def test_once_the_voice_is_done_the_music_comes_forward(self):
        chosen = sound.plan(self.http, self.home, look(self.home, "w", "off", "auto"), PROPS, "t")
        song = "bandpass=f=330:width_type=q:w=8,bandpass=f=330:width_type=q:w=8"
        flat = sound.mix(self.home, self.voice, chosen, 8.0, self.home / "flat.wav")
        risen = sound.mix(self.home, self.voice, chosen, 8.0, self.home / "risen.wav", swell=5.0)
        self.assertAlmostEqual(_loudness(risen, 2.6, 1.0, song), _loudness(flat, 2.6, 1.0, song), delta=0.5)  # before: as it was
        self.assertGreater(_loudness(risen, 5.8, 0.5, song) - _loudness(flat, 5.8, 0.5, song), 5)  # after: up front

    def test_effects_are_made_once_and_mixed_where_planned(self):
        chosen = sound.plan(self.http, self.home, look(self.home, "s", "auto", "off"), PROPS, "t")
        out = sound.mix(self.home, self.voice, chosen, 6.0, self.home / "mix.wav")
        made = sorted(p.name.split("-")[0] for p in (self.home / "studio/sfx").iterdir())
        self.assertEqual(made, ["hit", "pop", "whoosh"])
        # the voice is silent from 2 to 4 s: the whoosh into scene 2 and the emoji's pop are heard there,
        # and nothing after them
        self.assertGreater(_loudness(out, 2.0, 0.25), -45)
        self.assertGreater(_loudness(out, 2.4, 0.1), -45)
        self.assertLess(_loudness(out, 3.0, 0.9), -80)

    def test_nothing_to_add_still_shapes_the_voice_to_the_videos_length(self):
        chosen = sound.plan(self.http, self.home, look(self.home, "q", "off", "off"), PROPS, "t")
        out = sound.mix(self.home, self.voice, chosen, 6.0, self.home / "mix.wav")
        self.assertGreater(_loudness(out, 0.5, 1.0), -30)
        self.assertLess(_loudness(out, 2.6, 1.2), -80)  # no music came in

    def test_the_music_sits_well_under_the_voice_even_in_the_pauses(self):
        # it was a fixed -30 LUFS, 9 LU under a -21 LUFS clone: the words drowned
        chosen = sound.plan(self.http, self.home, look(self.home, "m", "off", "auto"), PROPS, "t")
        out = sound.mix(self.home, self.voice, chosen, 6.0, self.home / "mix.wav")
        song = "bandpass=f=330:width_type=q:w=8,bandpass=f=330:width_type=q:w=8"
        self.assertGreater(_loudness(out, 0.5, 1.2) - _loudness(out, 2.6, 1.2, song), 12)

    def test_the_director_can_leave_the_music_out(self):
        chosen = sound.plan(self.http, self.home, look(self.home, "m", "off", "auto"), PROPS, "t", "none")
        self.assertIsNone(chosen.music)
        self.assertIn("music: none (the director's choice)", chosen.notes)


class RotationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home)
        music = self.home / "studio/music"
        music.mkdir(parents=True)
        for name in ("a.mp3", "b.mp3"):
            (music / name).write_bytes(b"x")
        (music / "music.yaml").write_text("- {file: a.mp3, licence: CC0, mood: chill}\n"
                                          "- {file: b.mp3, licence: CC0, mood: chill}\n", encoding="utf-8")

    def pick(self, title: str) -> str:
        track, _ = sound.choose(None, self.home, "default", ("chill",), title)
        sound.used(self.home, track, title)
        return track.path.name

    def test_the_next_video_gets_another_track_and_its_own_clips_keep_it(self):
        first = self.pick("GPS")
        self.assertEqual(self.pick("GPS"), first)  # a hook clip of the same video
        self.assertNotEqual(self.pick("Compound interest"), first)  # the next video: not the same song again


if __name__ == "__main__":
    unittest.main()
