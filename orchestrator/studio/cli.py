"""On the host, no Telegram:
  python -m orchestrator.studio voice "text" --out speech.wav
  python -m orchestrator.studio write "notes or a draft script" --out sb.json [--notes notes.txt] [--profile bold] [--seconds 45] [--gemini]
  python -m orchestrator.studio cover storyboard.json --out cover.png [--scene 1] [--words "2-5 big words"] [--profile bold]
  python -m orchestrator.studio queue run [--now] [--notify] | add "notes" [--gemini] | pick <id> <n> | list
  python -m orchestrator.studio auth drive    (once: Google Drive for finished videos, drive.file scope)
  python -m orchestrator.studio wishes        (visuals the writer wanted but we cannot make yet, most wanted first)
  python -m orchestrator.studio video storyboard.json --out short.mp4 [--profile bold]   (storyboard.py: format)
or any ``/studio`` words (``python -m orchestrator.studio voices``)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from orchestrator.brief.store import default_state_dir

from . import audio, brief, chat, cover, drive, profile, queue, reference, research, sound, storyboard, video, voice, writer


def _video(home: Path, words: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.studio video")
    parser.add_argument("storyboard", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--profile", default="", help="page profile (default: the storyboard's, else studio.profile)")
    args = parser.parse_args(words)
    ctx = chat.Context(home)
    try:
        made = video.make(ctx.http, ctx.keys, ctx.settings, home, storyboard.load(args.storyboard), args.out,
                          args.profile)
    except (storyboard.StoryboardError, profile.ProfileError, voice.VoiceError, video.VideoError,
            audio.AudioError) as exc:
        print(f"⚠️ {exc}", file=sys.stderr)
        return 1
    print(f"{made.path}: {made.seconds:.1f} s · voice {made.voice_took:.0f} s · render {made.render_took:.0f} s"
          f" · job {made.job}")
    for note in made.notes:
        print(f"  {note}")
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
        made = cover.make(ctx.http, ctx.keys, ctx.settings, home, storyboard.load(args.storyboard), args.out,
                          args.scene, args.words,
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
    parser.add_argument("--claude", action="store_true", help="write with Claude (the default; studio.writer)")
    parser.add_argument("--gemini", action="store_true", help="write with Gemini's free models instead")
    args = parser.parse_args(words)
    ctx = chat.Context(home)
    try:
        notes = " ".join(args.text) + ("\n" + args.notes.read_text(encoding="utf-8") if args.notes else "")
        look = profile.load(args.profile or ctx.settings.profile, home)
        notes, found = research.add_to(ctx.http, ctx.keys, ctx.settings, notes,
                                       brief.seconds_of(look, args.seconds), args.out.parent)
        print(research.summary(found))
        draft = writer.write(ctx.http, ctx.keys, ctx.settings, look, notes, args.seconds, args.out.parent,
                             writer.choose(ctx.settings, args.claude, args.gemini))
    except (OSError, writer.WriterError, profile.ProfileError) as exc:
        print(f"⚠️ {exc}", file=sys.stderr)
        return 1
    saved = writer.save(draft, args.out, look.name)
    print(f"{draft.title}: {len(draft.scenes) + 1} scenes, {draft.words()} words "
          f"(~{draft.words() / brief.WPM * 60:.0f} s) · {draft.model}, {draft.rounds} call(s)")
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


def _queue(home: Path, words: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.studio queue")
    parser.add_argument("action", choices=["run", "add", "pick", "list"])
    parser.add_argument("rest", nargs="*", help="add: the notes · pick: <job id> <hook>")
    parser.add_argument("--now", action="store_true", help="run: render now, outside studio.render_window")
    parser.add_argument("--notify", action="store_true", help="run: send what happened to Telegram too")
    parser.add_argument("--gemini", action="store_true", help="add: write with Gemini")
    args = parser.parse_args(words)
    ctx = chat.Context(home)
    try:
        said = QUEUE_ACTIONS[args.action](ctx, args)
    except (queue.QueueError, writer.WriterError, profile.ProfileError, queue.HandoffError) as exc:
        print(f"⚠️ {exc}", file=sys.stderr)
        return 1
    if said:
        print(said)
    if said and args.notify:
        chat.Telegram(ctx.http, ctx.secrets).text(said)
    return 0


def _added(ctx: chat.Context, args: argparse.Namespace) -> str:
    job = queue.add(ctx, " ".join(args.rest), "gemini" if args.gemini else "")
    return f"Queued {job.id} ({job.state}): {job.data.get('title', 'Claude is writing it')}"


def _picked(ctx: chat.Context, args: argparse.Namespace) -> str:
    if len(args.rest) != 2 or not args.rest[1].isdigit():
        raise queue.QueueError("pick <job id> <hook 1-3>")
    return f"{queue.pick(ctx, args.rest[0], int(args.rest[1])).id}: hook {args.rest[1]}, renders next run"


QUEUE_ACTIONS = {"run": lambda ctx, args: queue.run(ctx, force=args.now), "add": _added, "pick": _picked,
                 "list": lambda ctx, _args: queue.status(ctx)}


def _profile(home: Path, words: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.studio profile")
    parser.add_argument("action", choices=["from"])
    parser.add_argument("video", type=Path, help="a short whose pace and colours you like")
    parser.add_argument("--name", required=True, help="the new profile's name")
    parser.add_argument("--force", action="store_true", help="replace a profile of that name")
    args = parser.parse_args(words)
    try:
        path, summary = reference.write(args.video, args.name, home, args.force)
    except (reference.ReferenceVideoError, profile.ProfileError) as exc:
        print(f"⚠️ {exc}", file=sys.stderr)
        return 1
    print(f"{path}: {summary}\nUse it with --profile {args.name} (or studio.profile: {args.name}).")
    return 0


def _music(home: Path, words: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.studio music")
    parser.add_argument("action", choices=["fetch", "list"])
    parser.add_argument("query", nargs="*", help='fetch: what to look for, e.g. "calm piano"')
    parser.add_argument("--count", type=int, default=3, help="fetch: how many tracks (default 3)")
    args = parser.parse_args(words)
    if args.action == "fetch":
        added = sound.fetch_music(chat.Context(home).http, home, " ".join(args.query) or "lofi chill", args.count)
        print("\n".join(f"+ {t.path.name}: {t.credit}" for t in added) or "Nothing new found (or Openverse unreachable).")
    for entry in sound.library(home):
        print(f"  {entry.path.name}: {entry.credit}" if isinstance(entry, sound.Track)
              else f"  ✗ {entry[0]}: {entry[1]} (not used)")
    return 0


COMMANDS = {"video": _video, "queue": _queue, "cover": _cover, "write": _write, "profile": _profile, "music": _music}


def main(argv: list[str] | None = None) -> int:
    words = sys.argv[1:] if argv is None else argv
    home = default_state_dir().parent
    if words[:1] and words[0] in COMMANDS:
        return COMMANDS[words[0]](home, words[1:])
    if words[:2] == ["auth", "drive"]:
        drive.login(chat.Context(home).http, chat.Context(home).secrets)
        return 0
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
