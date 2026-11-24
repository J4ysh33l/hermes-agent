"""The studio queue, the quality check and the loudness step, against fake Claude, Telegram, Drive and
GitHub; renders are stand-ins (the real ones are tested in test_video.py and test_custom.py).

The promises tested: /studio make writes now and renders only inside the night window (or on /studio
run); a render delivers the video, cover and hook clips to Telegram, and to Drive only when the quality
check passed and Drive is signed in; a failed check never reaches Drive; without an API key Claude writes
through the handoff repo, the queue waits for the answer, saves its components, and sends one fix request
when the checks fail; picking a hook re-renders with it; two runs never overlap; the quality check names
dead air, a black picture and the wrong format on real files; the voice is brought to -14 LUFS.

Run: python3 orchestrator/studio/tests/test_queue.py   (or orchestrator/run_checks.sh)
"""

from __future__ import annotations

import base64
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator/brief/tests"))
sys.path.insert(0, str(Path(__file__).parent))

from fakes import FakeHttp, http_error
from test_writer import GOOD, NOTES

from hermes_platform.resolver import locate_command
from orchestrator.studio import audio, chat, qc, queue, video

CLAUDE = "https://api.anthropic.com/v1/messages"
TG = "https://api.telegram.org/bott/"
GH = "https://api.github.com/repos/me/hand/"
NIGHT = datetime(2026, 11, 25, 2, 0)
DAY = datetime(2026, 11, 25, 14, 0)
HAS_FFMPEG = locate_command("ffmpeg").found and locate_command("ffprobe").found
RACE = (Path(__file__).parent / "data/race.tsx").read_text(encoding="utf-8")


def claude(text: str) -> dict:
    return {"stop_reason": "end_turn", "usage": {}, "content": [{"type": "text", "text": text}]}


class Stand:
    """Stand-ins for the slow tools: files appear, calls are counted."""

    def __init__(self, passed: bool = True) -> None:
        self.videos: list[tuple[str, int]] = []
        self.passed = passed

    def video(self, _http, _keys, _settings, _home, board, out: Path, _profile) -> video.Video:
        out.write_bytes(b"mp4")
        self.videos.append((out.name, len(board.scenes)))
        return video.Video(out, 14.0, out.parent, 1.0, 2.0, ("scene 2: custom scene built",))

    def cover(self, _settings, _home, _board, out: Path, scene: int, words: str, _profile) -> Path:
        out.write_bytes(b"png")
        self.cover_args = (scene, words)
        return out

    def qc(self, _video, _seconds, _pause) -> qc.Report:
        bad = () if self.passed else (qc.Check("clipping", False, "true peak 0.3 dBTP", True),)
        return qc.Report(bad, 14.0, -14.2, -1.6, 4.0)

    def tools(self) -> queue.Tools:
        return queue.Tools(video=self.video, cover=self.cover, qc=self.qc)


class Queue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = mock.patch.dict("os.environ", {"HERMES_HOME": str(self.home), "PATH": os.environ["PATH"]},
                                   clear=True)
        self.env.start()
        (self.home / "brief").mkdir()
        (self.home / "studio/profiles").mkdir(parents=True)
        (self.home / "studio/profiles/shorts.yaml").write_text("writing:\n  seconds: 15\n", encoding="utf-8")
        self.brief("")
        self.envfile("ANTHROPIC_API_KEY=a\n")
        self.http = FakeHttp()
        self.http.on("POST", CLAUDE, lambda _c: claude(json.dumps({**GOOD, "cover": {"scene": 2, "words": "Bun wins"}})))
        for method in ("sendVideo", "sendPhoto", "sendMessage"):
            self.http.on("POST", TG + method, {"ok": True})
        self.stand = Stand()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def brief(self, extra: str) -> None:
        (self.home / "brief/brief.yaml").write_text("studio:\n  profile: shorts\n" + extra, encoding="utf-8")

    def envfile(self, keys: str) -> None:
        (self.home / ".env").write_text("TELEGRAM_BOT_TOKEN=t\nTELEGRAM_HOME_CHANNEL=42\nGOOGLE_CLIENT_ID=c\n"
                                        "GOOGLE_CLIENT_SECRET=s\n" + keys, encoding="utf-8")

    def ctx(self) -> chat.Context:
        return chat.Context(self.home, self.http)

    def run_queue(self, at: datetime = NIGHT, force: bool = False) -> str:
        return queue.run(self.ctx(), at, force, self.stand.tools())

    def sent(self, method: str) -> list:
        return [c for c in self.http.calls if c.url == TG + method]

    def test_make_writes_now_and_renders_only_in_the_night_window_then_delivers(self):
        reply = chat.handle("make " + NOTES, self.home, self.http)
        self.assertIn("written by claude-opus-5-5", reply)
        self.assertIn("Hook 1 (definition-twist)", reply)
        self.assertIn("written, renders in 00:30-07:00", self.run_queue(DAY))
        self.assertEqual(self.stand.videos, [])
        said = self.run_queue(NIGHT)
        self.assertIn("delivered", said)
        self.assertEqual(self.stand.videos, [("video.mp4", 5), ("hook2.mp4", 1), ("hook3.mp4", 1)])
        self.assertEqual(self.stand.cover_args, (2, "Bun wins"))
        self.assertEqual((len(self.sent("sendVideo")), len(self.sent("sendPhoto"))), (3, 1))
        message = self.sent("sendMessage")[-1].json_body["text"]
        self.assertIn("QC passed", message)
        self.assertIn("Drive: not signed in", message)
        self.assertIn("scene 2: custom scene built", message)
        self.assertEqual(self.run_queue(NIGHT), "")  # done jobs are left alone
        self.assertIn("✅", queue.status(self.ctx()))

    def test_drive_gets_the_video_only_when_the_check_passed(self):
        tokens = self.home / "brief/tokens"
        tokens.mkdir(parents=True)
        (tokens / "drive.json").write_text('{"refresh_token": "r"}', encoding="utf-8")
        self.http.on("POST", "https://oauth2.googleapis.com/token", {"access_token": "x"})
        self.http.on("POST", "https://www.googleapis.com/drive/v3/files", {"id": "F"})
        self.http.on("POST", "https://www.googleapis.com/upload/drive/v3/files",
                     {"id": "v", "webViewLink": "https://drive/v"})
        self.stand.passed = False
        queue.add(self.ctx(), NOTES)
        self.run_queue()
        self.assertEqual(self.http.count("https://www.googleapis.com/upload"), 0)
        self.assertIn("⛔ clipping", self.sent("sendMessage")[-1].json_body["text"])
        self.stand.passed = True
        queue.add(self.ctx(), NOTES + " Again.")
        self.run_queue()
        self.assertEqual(self.http.count("https://www.googleapis.com/upload"), 2)  # video and cover
        self.assertIn("Drive: https://drive/v", self.sent("sendMessage")[-1].json_body["text"])
        self.assertEqual(json.loads((tokens / "drive.json").read_text())["folder"], "F")

    def test_without_an_api_key_claude_writes_through_the_handoff_repo(self):
        self.envfile("GITHUB_HANDOFF_TOKEN=g\n")
        self.brief("  handoff_repo: me/hand\n")
        files: dict[str, str] = {}
        self.http.on("PUT", GH + "contents/", lambda c: files.update({c.url.split("contents/")[1]: "sent"}) or {})
        self.http.on("POST", GH + "issues", {"number": 7})
        self.http.on("GET", GH + "contents/", self._github(files))
        reply = chat.handle("make " + NOTES, self.home, self.http)
        self.assertIn("issue #7", reply)
        job_id = queue.jobs(self.home)[0].id
        request = next(k for k in files if k.endswith("request.md"))
        self.assertEqual(request, f"studio/{job_id}/request.md")
        self.assertEqual(self.run_queue(), "")  # Claude has not answered: nothing to say
        answer = copy.deepcopy(GOOD)
        answer["scenes"].append({"type": "custom", "say": "Bun is done first.", "brief": "a race",
                                 "props": {"times": 25}, "component": "scene06.tsx",
                                 "fallback": {"type": "stat", "value": 25, "label": "faster"}})
        answer["scenes"][1]["value"] = 40  # not in the notes: the checks send it back
        files[f"studio/{job_id}/storyboard.json"] = json.dumps(answer)
        files[f"studio/{job_id}/scene06.tsx"] = RACE
        self.run_queue(DAY)
        fix = next(k for k in files if k.endswith("fix-1.md"))
        self.assertEqual(queue.load(self.home, job_id).state, "writing")
        answer["scenes"][1]["value"] = 25
        files[f"studio/{job_id}/storyboard-fix1.json"] = json.dumps(answer)
        self.assertIn("written, renders in", self.run_queue(DAY))
        job = queue.load(self.home, job_id)
        self.assertEqual((job.state, job.data["writer"]), ("ready", "claude (handoff)"))
        self.assertEqual(job.folder.joinpath("scene06.tsx").read_text(encoding="utf-8"), RACE)
        self.assertTrue(fix)

    def _github(self, files: dict[str, str]):
        def read(call):
            path = call.url.split("contents/")[1]
            if path not in files or files[path] == "sent":
                return http_error(404)(call)
            return {"content": base64.b64encode(files[path].encode()).decode()}
        return read

    def test_picking_a_hook_rerenders_with_it_and_skips_the_clips(self):
        job = queue.add(self.ctx(), NOTES)
        self.run_queue()
        self.stand.videos.clear()
        reply = chat.handle(f"pick {job.id} 3", self.home, self.http)
        self.assertIn("hook 3", reply)
        self.run_queue()
        self.assertEqual(self.stand.videos, [("video.mp4", 5)])
        self.assertIn("hook 3", self.sent("sendVideo")[-1].data.decode("utf-8", "replace"))

    def test_two_runs_never_overlap_and_a_failure_is_named(self):
        queue.add(self.ctx(), NOTES)
        with queue._lock(self.home) as mine:
            self.assertTrue(mine)
            self.assertEqual(self.run_queue(force=True), "A studio run is already going.")
        self.stand.video = lambda *a: (_ for _ in ()).throw(video.VideoError("Remotion failed: boom"))
        self.assertIn("failed: Remotion failed: boom", self.run_queue())
        self.assertIn("⚠️", queue.status(self.ctx()))

    def test_the_window_may_cross_midnight(self):
        self.assertTrue(queue.in_window("23:00-06:00", datetime(2026, 1, 1, 2, 0)))
        self.assertFalse(queue.in_window("23:00-06:00", datetime(2026, 1, 1, 12, 0)))
        self.assertTrue(queue.in_window("01:00-05:00", datetime(2026, 1, 1, 1, 0)))


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class RealFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, name: str, picture: str, sound: str, pix: str = "yuv420p") -> Path:
        out = self.dir / name
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", picture, "-f", "lavfi", "-i", sound,
                        "-t", "6", "-c:v", "libx264", "-pix_fmt", pix, "-r", "30", "-c:a", "aac", "-shortest",
                        str(out)], check=True, timeout=120)
        return out

    def test_the_check_names_dead_air_a_black_picture_and_the_wrong_format(self):
        moving = "testsrc2=size=1080x1920:rate=30"
        speech = "sine=frequency=220:sample_rate=48000,volume=0.25"
        good = qc.run(self.make("good.mp4", moving, speech), 6.0)
        self.assertTrue(good.passed, good.summary())
        quiet = "aevalsrc=0.25*sin(2*PI*220*t)*lt(mod(t\\,6)\\,2):s=48000"  # 2 s of tone, then silence
        dark = "color=c=black:size=1080x1920:rate=30"
        bad = qc.run(self.make("bad.mp4", dark, quiet, "yuvj420p"), 6.0)
        names = {c.name for c in bad.problems}
        self.assertTrue({"format", "dead air", "black picture"} <= names, bad.summary())
        self.assertFalse(bad.passed)

    def test_the_voice_is_brought_to_minus_14_lufs(self):
        src = self.dir / "voice.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "aevalsrc=0.05*sin(2*PI*180*t)*(0.6+0.4*sin(2*PI*3*t)):s=24000", "-t", "8", str(src)],
                       check=True, timeout=60)
        loud = audio.measure(audio.normalize(src, self.dir / "out.wav"))
        self.assertAlmostEqual(float(loud["input_i"]), -14.0, delta=1.0)
        self.assertLessEqual(float(loud["input_tp"]), -1.0)


if __name__ == "__main__":
    unittest.main()
