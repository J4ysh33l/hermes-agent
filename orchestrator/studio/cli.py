"""On the host, no Telegram:
  python -m orchestrator.studio voice "text" --out speech.wav
  python -m orchestrator.studio video storyboard.json --out short.mp4   (storyboard.py has the format)
or any ``/studio`` words (``python -m orchestrator.studio voices``)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from orchestrator.brief.store import default_state_dir

from . import chat, storyboard, video, voice


def _video(home: Path, words: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.studio video")
    parser.add_argument("storyboard", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(words)
    ctx = chat.Context(home)
    try:
        made = video.make(ctx.http, ctx.key, ctx.settings, home, storyboard.load(args.storyboard), args.out)
    except (storyboard.StoryboardError, voice.VoiceError, video.VideoError) as exc:
        print(f"⚠️ {exc}", file=sys.stderr)
        return 1
    print(f"{made.path}: {made.seconds:.1f} s · voice {made.voice_took:.0f} s · render {made.render_took:.0f} s"
          f" · job {made.job}")
    return 0


def main(argv: list[str] | None = None) -> int:
    words = sys.argv[1:] if argv is None else argv
    home = default_state_dir().parent
    if words[:1] == ["video"]:
        return _video(home, words[1:])
    if words[:1] == ["voice"] and "--out" in words:
        parser = argparse.ArgumentParser(prog="python -m orchestrator.studio voice")
        parser.add_argument("text", nargs="+")
        parser.add_argument("--out", required=True, type=Path)
        args = parser.parse_args(words[1:])
        ctx = chat.Context(home)
        try:
            speech = voice.speak(ctx.http, ctx.key, ctx.settings, home, " ".join(args.text), args.out)
        except voice.VoiceError as exc:
            print(f"⚠️ {exc}", file=sys.stderr)
            return 1
        print(f"{speech.path}: {speech.seconds:.1f} s")
        for text, start, end in speech.lines:
            print(f"  {start:7.2f}–{end:7.2f}  {text}")
        return 0
    print(chat.handle(" ".join(words), home))
    return 0
