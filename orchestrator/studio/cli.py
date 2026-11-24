"""On the host, no Telegram:
  python -m orchestrator.studio voice "text" --out speech.wav
  python -m orchestrator.studio write "notes or a draft script" --out sb.json [--notes notes.txt] [--profile bold] [--seconds 45] [--claude]
  python -m orchestrator.studio cover storyboard.json --out cover.png [--scene 1] [--words "2-5 big words"] [--profile bold]
  python -m orchestrator.studio wishes        (visuals the writer wanted but we cannot make yet, most wanted first)
  python -m orchestrator.studio video storyboard.json --out short.mp4 [--profile bold]   (storyboard.py: format)
or any ``/studio`` words (``python -m orchestrator.studio voices``)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from orchestrator.brief.store import default_state_dir

from . import chat, cover, profile, storyboard, video, voice, writer


def _video(home: Path, words: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.studio video")
    parser.add_argument("storyboard", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--profile", default="", help="page profile (default: the storyboard's, else studio.profile)")
    args = parser.parse_args(words)
    ctx = chat.Context(home)
    try:
        made = video.make(ctx.http, ctx.key, ctx.settings, home, storyboard.load(args.storyboard), args.out,
                          args.profile)
    except (storyboard.StoryboardError, profile.ProfileError, voice.VoiceError, video.VideoError) as exc:
        print(f"⚠️ {exc}", file=sys.stderr)
        return 1
    print(f"{made.path}: {made.seconds:.1f} s · voice {made.voice_took:.0f} s · render {made.render_took:.0f} s"
          f" · job {made.job}")
    return 0


def _cover(home: Path, words: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.studio cover")
    parser.add_argument("storyboard", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--scene", type=int, default=1, help="which scene, from 1 (the hook)")
    parser.add_argument("--words", default="", help="2–5 big words (default: the storyboard's title)")
    parser.add_argument("--profile", default="")
    args = parser.parse_args(words)
    ctx = chat.Context(home)
    try:
        made = cover.make(ctx.settings, home, storyboard.load(args.storyboard), args.out, args.scene, args.words,
                          args.profile)
    except (storyboard.StoryboardError, profile.ProfileError, video.VideoError, cover.CoverError) as exc:
        print(f"⚠️ {exc}", file=sys.stderr)
        return 1
    print(made)
    return 0


def _write(home: Path, words: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.studio write")
    parser.add_argument("text", nargs="*", help="the topic, facts or a draft script")
    parser.add_argument("--notes", type=Path, help="a file with the notes (added to the text)")
    parser.add_argument("--out", required=True, type=Path, help="the storyboard; hooks 2 and 3 go next to it")
    parser.add_argument("--profile", default="", help="page profile (default: studio.profile)")
    parser.add_argument("--seconds", type=float, default=0, help="length (default: the profile's writing.seconds)")
    parser.add_argument("--claude", action="store_true", help="write with Claude (studio.claude_model; paid)")
    args = parser.parse_args(words)
    ctx = chat.Context(home)
    try:
        notes = " ".join(args.text) + ("\n" + args.notes.read_text(encoding="utf-8") if args.notes else "")
        look = profile.load(args.profile or ctx.settings.profile, home)
        keys = writer.Keys(ctx.key, ctx.secrets.get("ANTHROPIC_API_KEY"))
        draft = writer.write(ctx.http, keys, ctx.settings, look, notes, args.seconds, args.out.parent, args.claude)
    except (OSError, writer.WriterError, profile.ProfileError) as exc:
        print(f"⚠️ {exc}", file=sys.stderr)
        return 1
    saved = writer.save(draft, args.out, look.name)
    print(f"{draft.title}: {len(draft.scenes) + 1} scenes, {draft.words()} words "
          f"(~{draft.words() / writer.WPM * 60:.0f} s) · {draft.model}, {draft.rounds} call(s)")
    for n, hook in enumerate(draft.hooks, 1):
        print(f"  hook {n} ({hook.family}): {hook.scene['say']}")
    for note in draft.notes:
        print(f"  note: {note}")
    for wish in draft.wishes:
        print(f"  wish: {wish}")
    if draft.wishes:
        writer.remember(draft, home, notes)
    print("Saved: " + ", ".join(map(str, saved)))
    return 0


def main(argv: list[str] | None = None) -> int:
    words = sys.argv[1:] if argv is None else argv
    home = default_state_dir().parent
    if words[:1] == ["video"]:
        return _video(home, words[1:])
    if words[:1] == ["cover"]:
        return _cover(home, words[1:])
    if words[:1] == ["write"]:
        return _write(home, words[1:])
    if words[:1] == ["wishes"]:
        found = writer.wishlist(home)
        print("\n".join(f"{n:4d}  {w}" for n, w in found) or "No wishes yet (they come from `write`).")
        return 0
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
