"""The edit, rendered: your footage cut to the plan, punched in, graded, with the graphics, captions, logo,
progress bar, music and effects, at -14 LUFS. Two video encodes, both from ``source.mp4``:

1. **Shots** (``shots/NNN.mp4``): each kept stretch of your talk, split at punch-ins, cut out with its zoom
   and grade, near lossless; joined without re-encoding into ``base.mp4``. Shot lengths are counted in frames
   from the edit's own clock, so the picture never drifts from the sound.
2. **Finish**: ``base.mp4`` + each graphic (rendered alone by Remotion on a transparent frame, only for its
   time on screen) + captions (libass) + logo + progress bar → x264 at ``edit.crf``.

The voice is cut on the same ranges with a 15 ms fade at every joint (no clicks), mixed with the studio's
effects and ducked music (studio/sound.py), and brought to -14 LUFS (studio/audio.py).
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestrator.brief.net import Http
from orchestrator.studio import audio, broll, qc, sound
from orchestrator.studio.settings import Keys, Settings as StudioSettings
from orchestrator.studio.video import PROJECT

from . import captions, cuts, plan as plans, watch
from .media import MediaError, run
from .settings import Settings
from .style import Style
from .words import Sentence, Word
import itertools

FADE = 0.015
TITLE_SHORTEST, TITLE_LONGEST = 2.5, 8.0
LOGO_PX = 96
W, H = 1080, 1920
SEAM = 960  # split screen: picture above, face below (Graphic.tsx SEAM)
FACE_TOP = 150  # the band of the frame (FACE_TOP to FACE_TOP + SEAM) that holds head and shoulders
LIST_HOLD = 1.8  # seconds a list stays after its last item arrives
MASK_KINDS = {"hide"}  # done by ffmpeg, not drawn by Remotion
PROGRESS_PX = 8


@dataclass
class Placed:
    kind: str
    start: float  # output time
    end: float
    item: dict[str, Any]


@dataclass
class Result:
    video: Path
    seconds: float
    notes: list[str] = field(default_factory=list)
    report: str = ""


def _shots(cut: cuts.CutList, points: list[float], look: Style, fps: int) -> list[dict[str, Any]]:
    """Each kept range, split where the zoom changes. A punch point toggles the zoom (in, then back out, like
    a second camera); with ``smooth`` each zoomed shot pushes in slowly instead. A point just before or at
    a range's start (a sentence after a cut pause) changes the zoom on that cut."""
    pace = look["pace"]
    punch, smooth = float(pace["punch"]), pace["punch_ease"] == "smooth"
    shots, zoomed, out = [], False, 0.0
    for r in cut.ranges:
        mine = [p for p in points if r.start - 0.4 <= p < r.end - 0.3]
        if any(p <= r.start + 0.3 for p in mine):
            zoomed = not zoomed
        inside = [p for p in mine if p > r.start + 0.3]
        edges = [r.start, *inside, r.end]
        for k, (a, b) in enumerate(itertools.pairwise(edges)):
            if k:
                zoomed = not zoomed
            start_f, end_f = round(out * fps), round((out + b - a) * fps)
            zoom = (1.0, punch) if smooth and zoomed else (punch, punch) if zoomed else (1.0, 1.0)
            shots.append({"src": a, "frames": max(1, end_f - start_f), "zoom": zoom})
            out += b - a
    return shots


def grade_filter(look: Style, extra: dict[str, float] | None = None) -> str:
    """The style's grade, plus what the editor added for this footage (plan "grade", already range-checked)."""
    g = dict(look["grade"])
    for key, value in (extra or {}).items():
        g[key] = round(float(g.get(key, 0)) + value, 3)
    w = float(g["warmth"])
    steps = [f"eq=contrast={g['contrast']}:saturation={g['saturation']}:brightness={g['brightness']}"]
    if w:
        steps.append(f"colorbalance=rs={0.04 * w:.3f}:bs={-0.04 * w:.3f}:rm={0.05 * w:.3f}:bm={-0.05 * w:.3f}:"
                     f"rh={0.02 * w:.3f}:bh={-0.03 * w:.3f}")
    if g["sharpen"]:
        steps.append(f"unsharp=5:5:{g['sharpen']}")
    return ",".join(steps)


def _zoom_filter(zoom: tuple[float, float], seconds: float, focus: tuple[float, float] = (0.5, 0.42)) -> str:
    a, b = zoom
    if a == b == 1.0:
        return ""
    z = f"{a}+({b - a})*min(t/{max(seconds, 0.1):.3f},1)" if a != b else f"{a}"
    # scale up and crop around the face (watch.focus), so the face stays where it is while the frame closes in
    fx, fy = (min(max(v, 0.0), 1.0) for v in focus)
    return (f"scale=w='trunc(1080*({z})/2)*2':h='trunc(1920*({z})/2)*2':eval=frame:flags=bicubic,"
            f"crop=1080:1920:(iw-1080)*{fx:.3f}:(ih-1920)*{fy:.3f},")


def build_base(job: Path, shots: list[dict[str, Any]], look: Style, edit: Settings, extra: dict[str, float] | None = None
               ) -> Path:
    folder = job / "shots"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    grade = grade_filter(look, extra)
    listing = []
    for n, shot in enumerate(shots):
        out = folder / f"{n:03d}.mp4"
        seconds = shot["frames"] / edit.fps
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{shot['src']:.3f}", "-i", str(job / "source.mp4"),
             "-vf", _zoom_filter(shot["zoom"], seconds, watch.focus(job, shot["src"], shot["src"] + seconds)) + grade + ",format=yuv420p", "-frames:v", str(shot["frames"]),
             "-r", str(edit.fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-threads", str(edit.threads),
             "-an", str(out)])
        listing.append(f"file '{out.name}'")
    (folder / "list.txt").write_text("\n".join(listing) + "\n", encoding="utf-8")
    base = job / "base.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(folder / "list.txt"), "-c", "copy", str(base)])
    return base


def cut_voice(job: Path, cut: cuts.CutList) -> Path:
    parts, chain = [], []
    for n, r in enumerate(cut.ranges):
        chain.append(f"[0:a]atrim={r.start:.4f}:{r.end:.4f},asetpts=PTS-STARTPTS,afade=t=in:d={FADE},"
                     f"afade=t=out:st={max(0.0, r.seconds - FADE):.4f}:d={FADE}[a{n}]")
        parts.append(f"[a{n}]")
    chain.append(f"{''.join(parts)}concat=n={len(parts)}:v=0:a=1[out]")
    out = job / "voice-cut.wav"
    script = job / "voice-cut.filter"
    script.write_text(";\n".join(chain), encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(job / "voice.wav"), "-filter_complex_script", str(script),
         "-map", "[out]", "-ar", "48000", str(out)])
    return out


def _list_beats(item: dict[str, Any], start: float, end: float, words: list[Word], cut: cuts.CutList, fps: int) -> list[int]:
    """The frame each list item arrives on: when its first word is said, else evenly through the first 70%."""
    beats, spoken = [], [(w.text.lower().strip(".,!?"), cut.to_output(w.start)) for n, w in enumerate(words) if n in set(cut.kept_words)]
    after = start - 0.05
    for k, text in enumerate(item.get("items") or []):
        first = (text.split() or [""])[0].lower().strip(".,!?")
        hit = next((t for w, t in spoken if w == first and after <= t < end), None)  # each item after the one before
        if hit is not None:
            after = hit + 0.05
        even = start + (end - start) * 0.7 * k / max(1, len(item["items"]))
        beats.append(max(0, round(((hit if hit is not None else even) - start) * fps)))
    return beats


def place(chosen: plans.Plan, found: list[Sentence], words: list[Word], cut: cuts.CutList, look: Style, fps: int
          ) -> tuple[list[Placed], list[str]]:
    notes, out = [], []
    first_kept = next((s for s in found if s.id not in cut.dropped and s.id not in chosen.drop), None)
    if chosen.title and look["title"]["kind"] != "none" and first_kept:
        end = float(look["title"]["seconds"]) or cut.to_output(first_kept.end) + 0.4
        out.append(Placed("title", 0.0, min(max(end, TITLE_SHORTEST), TITLE_LONGEST if not look["title"]["seconds"] else end),
                          {"kind": "title", "text": chosen.title, "sub": chosen.subtitle}))
    for g in plans.place(chosen, found):
        if not any(r.start - 0.05 <= g.start <= r.end for r in cut.ranges):
            notes.append(f"{g.kind} at {g.data.get('at')} skipped: that part was cut")
            continue
        a, b = cut.to_output(g.start), cut.to_output(g.end)
        item = {k: v for k, v in g.data.items() if k not in ("at", "to")}
        if g.kind == "list":
            beats = _list_beats(item, a, b, words, cut, fps)
            lead = max(0, beats[0] - 3) if beats else 0  # the card arrives with its first item, never empty
            a += lead / fps
            item["beats"] = [x - lead for x in beats]
            if item["beats"]:
                b = max(b, a + item["beats"][-1] / fps + LIST_HOLD)  # the last item stays long enough to read
        if g.kind == "pop":
            item["side"] = "left" if sum(p.kind == "pop" for p in out) % 2 == 0 else "right"
        out.append(Placed(g.kind, a, max(b, a + 0.5), item))
    return sorted(out, key=lambda p: p.start), notes


def _assets(job: Path, placed: list[Placed], http: Http | None, keys: Keys, home: Path) -> tuple[list[Placed], list[str]]:
    """Files for image/screenshot (from the job's assets/) and stock for cutaways, copied into gfx/public."""
    public = job / "gfx" / "public"
    public.mkdir(parents=True, exist_ok=True)
    keep, notes = [], []
    for p in placed:
        if p.kind in ("image", "screenshot"):
            src = job / "assets" / str(p.item.get("file", ""))
            if not src.is_file():
                notes.append(f"{p.kind} {p.item.get('file')!r} skipped: not in the job's assets (send it with the video)")
                continue
            shutil.copy(src, public / src.name)
            p.item["src"] = src.name
        elif p.kind in ("cutaway", "split") and p.item.get("file"):
            src = job / "assets" / str(p.item["file"])
            if not src.is_file():
                notes.append(f"{p.kind} {p.item['file']!r} skipped: not in the job's assets")
                continue
            shutil.copy(src, public / src.name)
            p.item["src"], p.item["video"] = src.name, src.suffix.lower() in (".mp4", ".mov", ".webm", ".m4v")
        elif p.kind in ("cutaway", "split"):
            got = broll.fetch(http, keys, home, str(p.item.get("query", ""))) if http else None
            if not got:
                notes.append(f"{p.kind} {p.item.get('query')!r} skipped: no stock footage found")
                continue
            path, credit = got
            shutil.copy(path, public / path.name)
            p.item["src"], p.item["video"] = path.name, path.suffix.lower() in (".mp4", ".mov", ".webm")
            notes.append(f"b-roll: {credit}")
        keep.append(p)
    return keep, notes


def _bundle(job: Path) -> Path:
    out = job / "gfx" / "bundle"
    run([str(PROJECT / "node_modules/.bin/remotion"), "bundle", "src/index.ts", "--out-dir", str(out),
         f"--public-dir={job / 'gfx' / 'public'}", "--log=error"], timeout=900, cwd=PROJECT)
    return out


def render_graphics(job: Path, placed: list[Placed], look: Style, studio: StudioSettings, fps: int) -> list[Path]:
    if not placed:
        return []
    bundle = _bundle(job)
    g = dict(look["graphics"])
    look_props = {**{k: g[k] for k in ("font", "serif", "ink", "paper", "accent", "alert", "good", "box_bg", "box_fg", "figure", "radius")},
                  "title": dict(look["title"])}
    files = []
    for n, p in enumerate(placed):
        frames = max(1, math.ceil((p.end - p.start) * fps))
        props = job / "gfx" / f"{n:02d}.json"
        props.write_text(json.dumps({"look": look_props, "item": p.item, "frames": frames}, ensure_ascii=False), encoding="utf-8")
        out = job / "gfx" / f"{n:02d}.mov"
        args = [str(PROJECT / "node_modules/.bin/remotion"), "render", str(bundle), "EditGraphic", str(out),
                f"--props={props}", "--codec=prores", "--prores-profile=4444", "--image-format=png",
                "--pixel-format=yuva444p10le", f"--concurrency={studio.video_concurrency}", "--log=error"]
        if studio.video_browser:
            args.append(f"--browser-executable={studio.video_browser}")
        run(args, timeout=1800)
        files.append(out)
    return files


def _even(x: float) -> int:
    return max(2, round(x / 2) * 2)


def _masks(placed: list[Placed], last: str) -> tuple[list[str], str]:
    """Blur each "hide" box for its time, then move the face to the bottom half during each split. Both work
    on the cut footage, before the graphics go on top."""
    chains = []
    for n, p in enumerate(q for q in placed if q.kind == "hide"):
        x, y, w, h = p.item["box"]
        bx, by = _even(x * W), _even(y * H)
        bw, bh = min(_even(w * W), W - bx), min(_even(h * H), H - by)
        chains.append(f"{last}split=2[hm{n}][hc{n}]")
        chains.append(f"[hc{n}]crop={bw}:{bh}:{bx}:{by},scale=iw/16:ih/16,gblur=sigma=2,scale={bw}:{bh}:flags=bilinear[hb{n}]")
        chains.append(f"[hm{n}][hb{n}]overlay={bx}:{by}:enable='between(t,{p.start:.3f},{p.end:.3f})'[hv{n}]")
        last = f"[hv{n}]"
    for n, p in enumerate(q for q in placed if q.kind == "split"):
        chains.append(f"{last}split=2[sm{n}][sc{n}]")
        chains.append(f"[sc{n}]crop={W}:{SEAM}:0:{FACE_TOP}[sf{n}]")
        chains.append(f"[sm{n}][sf{n}]overlay=0:{SEAM}:enable='between(t,{p.start:.3f},{p.end:.3f})'[sv{n}]")
        last = f"[sv{n}]"
    return chains, last


def finish(job: Path, base: Path, sound_file: Path, placed: list[Placed], gfx: list[Path], ass: Path | None, fonts: Path | None,
           look: Style, home: Path, seconds: float, edit: Settings, out: Path) -> Path:
    """``placed`` holds every graphic; ``gfx`` the Remotion clips for those that are drawn (all but "hide")."""
    inputs = ["-i", str(base)]
    chains, last = _masks(placed, "[0:v]")
    placed = [p for p in placed if p.kind not in MASK_KINDS]
    for n, (p, clip) in enumerate(zip(placed, gfx), start=1):
        inputs += ["-i", str(clip)]
        chains.append(f"[{n}:v]setpts=PTS-STARTPTS+{p.start:.3f}/TB[g{n}]")
        chains.append(f"{last}[g{n}]overlay=eof_action=pass:format=auto:enable='between(t,{p.start:.3f},{p.end + 0.05:.3f})'[v{n}]")
        last = f"[v{n}]"
    k = len(gfx) + 1
    logo_name = look["graphics"]["logo"]
    logo = home / "edit" / "brand" / logo_name if logo_name else None
    if logo and logo.is_file() and look["graphics"]["logo_pos"] != "none":
        inputs += ["-loop", "1", "-i", str(logo)]
        x = "W-w-48" if look["graphics"]["logo_pos"] == "top-right" else "48"
        chains.append(f"[{k}:v]scale=-1:{LOGO_PX},format=rgba,colorchannelmixer=aa=0.92[logo]")
        chains.append(f"{last}[logo]overlay={x}:64:shortest=1[vl]")
        last, k = "[vl]", k + 1
    if look["graphics"]["progress"]:
        accent = look["graphics"]["accent"].lstrip("#")
        chains.append(f"color=c=0x{accent}:s=1080x{PROGRESS_PX}:r={edit.fps}:d={seconds:.3f}[bar]")
        chains.append(f"{last}[bar]overlay=x='-W+W*t/{max(seconds, 0.1):.3f}':y=H-{PROGRESS_PX}:shortest=1[vp]")
        last = "[vp]"
    if ass is not None:
        chains.append(f"{last}subtitles='{ass}':fontsdir='{fonts}'[vs]")
        last = "[vs]"
    chains.append(f"{last}format=yuv420p[vout]")
    inputs += ["-i", str(sound_file)]
    script = job / "finish.filter"
    script.write_text(";\n".join(chains), encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex_script", str(script), "-map", "[vout]",
         "-map", f"{k}:a",
         "-c:v", "libx264", "-preset", edit.preset, "-crf", str(edit.crf), "-threads", str(edit.threads),
         "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-r", str(edit.fps),
         "-c:a", "aac", "-b:a", "256k", "-t", f"{seconds:.3f}", "-movflags", "+faststart", str(out)])
    return out


def _music(http: Http | None, home: Path, look: Style, chosen: plans.Plan, title: str) -> tuple[sound.Track | None, list[str]]:
    use = look["sound"]["music"]
    if use == "off" or (use == "auto" and not chosen.music):
        return None, []
    tracks = [t for t in sound.library(home) if isinstance(t, sound.Track) and (not t.profiles or look.name in t.profiles)]
    if not tracks and http is not None:  # Openverse finds little for 3+ words: then fewer, then the style's own
        for query in _music_queries(chosen.music, look["sound"]["music_query"]):
            tracks = sound.fetch_music(http, home, query)
            if tracks:
                break
    if not tracks:
        return None, ["no music: nothing in studio/music/music.yaml and none found on Openverse"]
    track = tracks[int(hashlib.sha256(title.encode()).hexdigest(), 16) % len(tracks)]
    return track, [f"music: {track.credit}" + ("" if track.licence in track.credit else f" ({track.licence})")]


def _music_queries(asked: str, default: str) -> list[str]:
    out = []
    for text in (asked, default):
        words = text.split()
        for q in (" ".join(words), " ".join(words[:2]), " ".join(words[-2:]), words[-1] if words else ""):
            if q and q not in out:
                out.append(q)
    return out[:6]


def _cues(placed: list[Placed], use: str) -> list[sound.Cue]:
    if use == "off":
        return []
    out = []
    for p in placed:
        if p.kind in ("stat", "emoji", "lower_third", "chapter", "pop") or (use == "always" and p.kind in ("list", "headline", "quote")):
            out.append(sound.Cue(p.start, "pop"))
        elif p.kind in ("cutaway", "split"):
            out.append(sound.Cue(max(0.0, p.start - sound.EFFECTS["whoosh"][2]), "whoosh"))
    return out


def render(job: Path, look: Style, chosen: plans.Plan, words: list[Word], found: list[Sentence], edit: Settings,
           studio: StudioSettings, home: Path, out: Path, http: Http | None = None, keys: Keys = Keys()) -> Result:
    cut = cuts.build(words, found, look, chosen.drop, chosen.trim, chosen.keep)
    if not cut.ranges:
        raise MediaError("nothing is left after the cuts")
    (job / "cuts.json").write_text(json.dumps(cut.as_dict(), indent=1), encoding="utf-8")
    shots = _shots(cut, plans.punch_points(chosen, found, cut, look), look, edit.fps)
    seconds = sum(s["frames"] for s in shots) / edit.fps
    base = build_base(job, shots, look, edit, chosen.grade)
    placed, notes = place(chosen, found, words, cut, look, edit.fps)
    placed, more = _assets(job, placed, http, keys, home)
    notes += more
    gfx = render_graphics(job, [p for p in placed if p.kind not in MASK_KINDS], look, studio, edit.fps)
    ass = fonts = None
    if look["captions"]["show"]:
        hidden = [(p.start, p.end) for p in placed if p.kind in plans.CARD_KINDS]
        seam = [(p.start, p.end) for p in placed if p.kind in plans.SPLIT_KINDS]
        ass, fonts = captions.write(captions.pages(words, cut, look, hidden), look, job, seam)
    voice = cut_voice(job, cut)
    track, music_notes = _music(http, home, look, chosen, chosen.title.replace("*", "") or job.name)
    mixed = sound.mix(home, voice, sound.Plan(tuple(_cues(placed, look["sound"]["sfx"])), track, tuple(music_notes)), seconds,
                      job / "mix.wav")
    final_sound = audio.normalize(mixed, job / "sound.wav")
    finish(job, base, final_sound, placed, gfx, ass, fonts, look, home, seconds, edit, out)
    report = qc.run(out, expected=seconds)
    return Result(out, seconds, notes + music_notes + ([chosen.notes] if chosen.notes else []), report.summary())
