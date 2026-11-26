"""Sound under the voice: effects on the cuts and a music bed, mixed before the soundtrack is brought to
-14 LUFS (audio.py). The profile's ``elements.sfx`` / ``elements.music`` say off, auto or always.

Effects are made here, from formulas (ffmpeg ``aevalsrc``): nobody else's recording, so no licence to
track, and the same on every host. Each is placed so its peak lands where the eye expects it: a whoosh
on a push/whip/zoom transition, a hit on a flash, a riser into a burn, a pop when an emoji lands, and
(``always``) a tick as each list item appears. Made once into ``$HERMES_HOME/studio/sfx/``.

Music comes from ``$HERMES_HOME/studio/music/music.yaml``: the tracks you may use, each with its licence
and the credit to show; a file not listed (or listed without a licence) is never used. A video asks for a
mood ("calm piano", "inspiring corporate"); the track whose mood matches it best is used. When nothing of
yours matches, three are found on Openverse (``fetch_music``, or ``python -m orchestrator.studio music fetch
"<words>"`` to stock up) and added to it; yours always win. Openverse is asked for produced, instrumental
music (Jamendo and ccMixter first, then Freesound) under CC0, public domain or CC BY. CC BY lets a business
use it with credit: the credit is in the job's notes, to paste into the post's caption::

    - file: calm-pulse.mp3
      licence: CC0                     # or "Pixabay Content License", "CC BY 4.0", ...
      credit: "Calm Pulse by A. Artist (pixabay.com/music/...)"
      profiles: [paper]                # optional: only for these profiles
      mood: calm piano                 # optional, what it suits (matched against the video's mood)

The track starts at its first sound (no silent intro), is brought to one bed level (so a quiet and a loud
track sit alike), looped or cut to the video, faded in and out, and ducked under the voice (sidechain
compression: it dips while words are spoken and comes back up in the pauses). From ``swell`` on (an end
card with no voice) it rises to the front and fades out with the picture.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import zlib
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml

from orchestrator.brief.net import Http, HttpError

from . import openverse
from .audio import TIMEOUT, AudioError, measure
from .profile import Profile

FPS = 30
# name → (formula of t in seconds, length in s, seconds from its start to its peak)
EFFECTS: dict[str, tuple[str, float, float]] = {
    "whoosh": ("(random(0)*2-1)*if(lt(t,0.3),pow(t/0.3,2.5),exp(-(t-0.3)*14))*0.8", 0.6, 0.3),
    "hit": ("(0.9*sin(2*PI*52*t)+0.35*sin(2*PI*104*t))*exp(-5*t)+(random(0)*2-1)*0.5*exp(-40*t)", 0.9, 0.0),
    "riser": ("(0.4*sin(2*PI*t*(180+520*t))+0.25*(random(0)*2-1))*pow(t/0.7,2)", 0.7, 0.7),
    "pop": ("sin(2*PI*t*(1400-7000*t))*exp(-35*t)*0.8", 0.14, 0.0),
    "tick": ("sin(2*PI*2200*t)*exp(-90*t)*0.6", 0.06, 0.0),
}
# What each transition sounds like (none, cut and fade are quiet).
ON_TRANSITION = {"push": "whoosh", "whip": "whoosh", "zoom": "whoosh", "flash": "hit", "burn": "riser"}
LEVEL = {"whoosh": -16.0, "hit": -14.0, "riser": -18.0, "pop": -18.0, "tick": -24.0}  # dB under full scale
BED_UNDER = 20.0  # the music sits this many LU under the voice, before ducking (was a fixed -30 LUFS, tuned
# for Kokoro near -18: under a -21 LUFS clone that left only 9 LU and the music swamped the words)
RECENT = 4  # a track used by one of the last 4 videos is not used again while another one fits
# The voice, made to carry: rumble out, presence (where consonants and energy live) up, levelled by a
# gentle compressor so quiet words keep up with loud ones.
VOICE_CHAIN = "highpass=f=80,equalizer=f=3200:t=q:w=1.0:g=3,acompressor=threshold=-22dB:ratio=3:attack=5:release=90:makeup=2"
SWELL_DB = 7.0  # how far the bed rises once the voice is done (an end card)
MUSIC_SECONDS = (40, 420)  # a found track long enough to loop well, short enough to fetch quickly
MUSIC_LICENCES = "cc0,pdm,by"
MUSIC_SOURCES = "jamendo,ccmixter,freesound"  # produced music first; Freesound is mostly loops
SOURCE_RANK = {"jamendo": 0.3, "ccmixter": 0.2}
BED_TAGS = {"backgroundmusic", "commercial", "corporate", "film", "filmscore", "musicbed", "instrumental", "soft",
            "atmospheric"}
NOT_MUSIC = re.compile(r"\b(vocals?|voice|male|female|speech|talk|podcast|spoken|sing(ing|er)?|acapella|choir|rap)\b",
                       re.IGNORECASE)
FADE_IN, FADE_OUT = 0.4, 1.6


@dataclass(frozen=True)
class Cue:
    at: float  # seconds on the soundtrack where the effect starts
    name: str


@dataclass(frozen=True)
class Track:
    path: Path
    licence: str
    credit: str
    profiles: tuple[str, ...]  # () = any profile
    mood: str = ""


@dataclass(frozen=True)
class Plan:
    cues: tuple[Cue, ...]
    music: Track | None
    notes: tuple[str, ...]  # the music's credit, or why there is none


def _cut_cues(scenes: list[dict], motion: dict) -> list[Cue]:
    out = []
    for scene, following in pairwise(scenes):
        name = ON_TRANSITION.get(scene.get("transition") or motion["transition"])
        if name:  # the peak lands halfway through the overlap
            peak = following["start"] + motion["transition_frames"] / FPS / 2
            out.append(Cue(max(0.0, peak - EFFECTS[name][2]), name))
    return out


def _emoji_cues(scenes: list[dict], words: list[dict]) -> list[Cue]:
    out = []
    for scene in scenes:
        if scene.get("emoji"):  # where Short.tsx lands it: the first emphasised word, else 0.3 s in
            hit = next((w["start"] for w in words if w["emphasis"] and scene["start"] <= w["start"] < scene["end"]),
                       scene["start"] + 0.3)
            out.append(Cue(hit, "pop"))
    return out


def _item_cues(scenes: list[dict]) -> list[Cue]:
    out = []
    for scene in scenes:
        count = len(scene.get("items") or [])
        beats = scene.get("beats") or []
        if count and len(beats) >= count:  # items arrive on their sentences (motion.tsx revealAt)
            out += [Cue(scene["start"] + b, "tick") for b in beats[len(beats) - count:]]
    return out


def cues(props: dict[str, Any], use: str) -> list[Cue]:
    """Where effects go in a video (props.json as video.py wrote it); ``use`` = elements.sfx."""
    if use == "off":
        return []
    scenes, motion = props["scenes"], props["profile"]["motion"]
    found = _cut_cues(scenes, motion) + _emoji_cues(scenes, props["words"])
    if use == "always":
        found += _item_cues(scenes)
    return sorted(found, key=lambda c: c.at)


def effect(home: Path, name: str) -> Path:
    """The effect's WAV, made from its formula on first use (named by the formula, so a change remakes it)."""
    formula, seconds, _peak = EFFECTS[name]
    digest = hashlib.sha256(f"{formula}|{seconds}".encode()).hexdigest()[:10]
    path = home / "studio" / "sfx" / f"{name}-{digest}.wav"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        _ffmpeg(["-f", "lavfi", "-i", f"aevalsrc='{formula}':s=48000:d={seconds}",
                 "-af", "highpass=f=40,lowpass=f=14000", "-ac", "2", str(path)])
    return path


def library(home: Path) -> list[Track | tuple[str, str]]:
    """The tracks music.yaml allows, and (file, reason) for each entry that cannot be used."""
    folder = home / "studio" / "music"
    listing = folder / "music.yaml"
    if not listing.is_file():
        return []
    try:
        entries = yaml.safe_load(listing.read_text(encoding="utf-8")) or []
    except yaml.YAMLError as exc:
        raise AudioError(f"{listing} is not valid YAML: {exc}") from None
    out: list[Track | tuple[str, str]] = []
    for entry in entries if isinstance(entries, list) else []:
        file = str((entry or {}).get("file", "")) if isinstance(entry, dict) else ""
        path = folder / file
        if not file or not str(entry.get("licence", "")).strip():
            out.append((file or "?", "no licence given"))
        elif not path.is_file() or path.resolve().parent != folder.resolve():
            out.append((file, "file not found in the music folder"))
        else:
            profiles = entry.get("profiles") or []
            out.append(Track(path, str(entry["licence"]), str(entry.get("credit", "")) or file,
                             tuple(map(str, profiles if isinstance(profiles, list) else [profiles])), str(entry.get("mood", ""))))
    return out


def _is_music(result: dict[str, Any], query: str) -> bool:
    seconds = (result.get("duration") or 0) / 1000
    tags = " ".join(str(t.get("name", "")) for t in result.get("tags") or [] if isinstance(t, dict))
    return (MUSIC_SECONDS[0] <= seconds <= MUSIC_SECONDS[1] and not NOT_MUSIC.search(f"{result.get('title', '')} {tags}")
            and openverse.relevance(result, query) >= 0.5)


def _rank(result: dict[str, Any], query: str) -> float:
    """Better for a bed: matches the mood, produced (Jamendo/ccMixter), tagged for film or adverts."""
    tags = {str(t.get("name", "")).lower() for t in result.get("tags") or [] if isinstance(t, dict)}
    tags |= {str(g).lower() for g in result.get("genres") or []}
    return openverse.relevance(result, query) + SOURCE_RANK.get(str(result.get("source")), 0) + 0.1 * len(tags & BED_TAGS)


def fetch_music(http: Http, home: Path, query: str, count: int = 1) -> list[Track]:
    """Up to ``count`` instrumental tracks for ``query`` from Openverse (CC0, public domain or CC BY), best
    first, downloaded into the music folder and listed in music.yaml (with licence, credit, mood and where
    they came from)."""
    folder = home / "studio" / "music"
    listing = folder / "music.yaml"
    entries = (yaml.safe_load(listing.read_text(encoding="utf-8")) or []) if listing.is_file() else []
    known = {str(e.get("openverse")) for e in entries if isinstance(e, dict)}
    found = openverse.search(http, "audio", query, MUSIC_LICENCES, source=MUSIC_SOURCES, category="music")
    added: list[Track] = []
    for result in sorted(found, key=lambda r: -_rank(r, query)):
        if len(added) >= count:
            break
        if str(result.get("id")) in known or not _is_music(result, query):
            continue
        try:
            body = http.request("GET", result["url"]).body
        except HttpError:
            continue
        if len(body) < 20_000:  # an error page, not a track
            continue
        folder.mkdir(parents=True, exist_ok=True)
        ext = str(result.get("filetype") or "mp3")
        ext = "mp3" if ext.startswith("mp3") or not ext.isalnum() else ext  # Jamendo says "mp32"
        path = folder / f"ov-{str(result['id'])[:12]}.{ext}"
        path.write_bytes(body)
        licence = openverse.licence_name(result)
        entries.append({"file": path.name, "licence": licence, "credit": openverse.credit(result, "Music"),
                        "mood": query, "openverse": str(result["id"])})
        added.append(Track(path, licence, entries[-1]["credit"], (), query))
    if added:
        listing.write_text(yaml.safe_dump(entries, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return added


def queries(*moods: str) -> list[str]:
    """What to search for a mood: Openverse finds little for 3+ words, so then fewer, then each word alone
    (the genre is often in the middle: "neon *synthwave* pulse")."""
    out: list[str] = []
    for text in moods:
        words = text.split()
        singles = [w for w in words if len(w) > 2 and w.lower() not in openverse.STOP]
        for q in (" ".join(words), " ".join(words[:2]), " ".join(words[-2:]), *singles):
            if q and q not in out:
                out.append(q)
    return out[:8]


def _fits(track: Track, mood: str) -> float:
    wanted = openverse.words(mood)
    have = openverse.words(f"{track.mood} {track.credit}")
    return sum(1 for w in wanted if any(h.startswith(w) for h in have)) / len(wanted) if wanted else 0.0


def recent(home: Path) -> list[tuple[str, str]]:
    """(track file, video title) of the last videos' music, newest last."""
    path = home / "studio" / "music" / "recent.txt"
    rows = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    return [(f, t) for f, _, t in (row.partition("\t") for row in rows) if f]


def used(home: Path, track: Track, title: str) -> None:
    path = home / "studio" / "music" / "recent.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in recent(home) if r[1] != title] + [(track.path.name, title)]  # one row per video
    path.write_text("".join(f"{f}\t{t}\n" for f, t in rows[-RECENT:]), encoding="utf-8")


def choose(http: Http | None, home: Path, profile: str, moods: tuple[str, ...], title: str,
           strict: bool = False) -> tuple[Track | None, tuple[str, ...]]:
    """The track for a video: yours (this profile's) that suits the first mood best; none suits: three found
    for it on Openverse; nothing found: any of yours. A track one of the last videos used is passed over
    while another fits. The same title gets the same track among equals. ``strict`` (the director chose the
    mood): never fall back to an unrelated track; no fit = no music."""
    last = {f for f, t in recent(home) if t != title}  # its own hook clips keep the video's track
    mine = [t for t in library(home) if isinstance(t, Track) and (not t.profiles or profile in t.profiles)]
    fresh = [t for t in mine if t.path.name not in last]
    mine = fresh or mine
    mood = next((m for m in moods if m.strip()), "")
    best = max((_fits(t, mood) for t in mine), default=0.0)
    tracks = [t for t in mine if _fits(t, mood) == best] if best >= 0.5 else []
    if not tracks and http is not None:
        for query in queries(*moods):
            tracks = fetch_music(http, home, query, 3)
            if tracks:
                break
    if not tracks and strict:  # the director's mood: a track that shares a word of it, or none at all
        near = max((_fits(t, mood) for t in mine), default=0.0)
        tracks = [t for t in mine if _fits(t, mood) == near] if near > 0 else []
        if not tracks:
            why = openverse.blocked() or "none found on Openverse"
            return None, (f"music: none: nothing in the library suits the director's {mood!r} and {why}; "
                          "an unrelated track would be worse than the voice alone",)
    tracks = [t for t in tracks if t.path.name not in last] or tracks or mine
    if not tracks:
        return None, ("no music: nothing in studio/music/music.yaml suits it and none found on Openverse",)
    track = tracks[zlib.crc32(title.encode("utf-8")) % len(tracks)]
    notes = [f"music: {track.credit}" + ("" if track.licence in track.credit else f" ({track.licence})")]
    if track.licence.startswith("CC BY"):
        notes.append("music licence CC BY: put the music credit above in the post's caption")
    return track, tuple(notes)


def plan(http: Http, home: Path, look: Profile, props: dict[str, Any], title: str, music: str = "") -> Plan:
    """The effects and music for one video. ``music`` is the director's: "none" (no music: a voice-only
    piece), a mood to search for, or "" (the profile's ``music_query``). Music (``auto``/``always``): the
    track that suits it best (``choose``); none to be had: no music (``always`` says so)."""
    elements = look.section("elements")
    found = cues(props, elements["sfx"])
    if elements["music"] == "off":
        return Plan(tuple(found), None, ())
    if music == "none" and elements["music"] != "always":
        return Plan(tuple(found), None, ("music: none (the director's choice)",))
    directed = music not in ("", "none")
    moods = (music,) if directed else (elements["music_query"] or "calm",)  # the director's mood replaces the house one
    track, notes = choose(http, home, look.name, moods, title, strict=directed)
    if track is None:
        return Plan(tuple(found), None, notes if elements["music"] == "always" or directed else ())
    used(home, track, title)
    return Plan(tuple(found), track, notes)


def _ffmpeg(args: list[str]) -> None:
    try:
        done = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-y", *args], capture_output=True, text=True,
                              timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioError(f"ffmpeg failed: {exc}") from None
    if done.returncode != 0:
        raise AudioError(f"ffmpeg failed: {done.stderr.strip()[-300:]}")


def _bed_gain(track: Path, voice: Path) -> float:
    """dB that bring the track BED_UNDER under the voice (a silent track gets none)."""
    level, spoken = float(measure(track)["input_i"]), float(measure(voice)["input_i"])
    target = (spoken if spoken > -70 else -18.0) - BED_UNDER
    return 0.0 if level < -70 else max(-40.0, min(20.0, target - level))


def mix(home: Path, voice: Path, chosen: Plan, seconds: float, dst: Path, swell: float | None = None) -> Path:
    """The voice with the plan's effects and ducked music, ``seconds`` long, into ``dst`` (WAV, not yet
    normalised). From ``swell`` seconds on (the voice is done) the music comes forward. Nothing to add: the
    voice still goes through VOICE_CHAIN."""
    inputs, chains, beds = ["-i", str(voice)], [f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,{VOICE_CHAIN},"
                                                f"apad=whole_dur={seconds:.3f}[v]"], []
    for n, cue in enumerate(chosen.cues, start=1):
        inputs += ["-i", str(effect(home, cue.name))]
        delay = round(cue.at * 1000)
        chains.append(f"[{n}:a]volume={LEVEL[cue.name]}dB,adelay={delay}|{delay}[s{n}]")
        beds.append(f"[s{n}]")
    voices = "[v]"
    if chosen.music:
        m = len(chosen.cues) + 1
        inputs += ["-stream_loop", "-1", "-i", str(chosen.music.path)]
        rise = ""
        if swell is not None and swell < seconds - 0.3:  # an even ramp over 0.5 s, then held
            up = 10 ** (SWELL_DB / 20) - 1
            rise = f",volume='1+{up:.3f}*min(1,max(0,(t-{swell:.3f})/0.5))':eval=frame"
        chains += ["[v]asplit=2[vk][vm]",
                   f"[{m}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                   "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,"
                   f"atrim=0:{seconds:.3f},asetpts=N/SR/TB,"
                   f"volume={_bed_gain(chosen.music.path, voice):.2f}dB,afade=t=in:d={FADE_IN}[bed]",
                   # dips while words are spoken (fast), comes back up gently in the pauses
                   "[bed][vk]sidechaincompress=threshold=0.02:ratio=8:attack=10:release=450:knee=4[duck]",
                   f"[duck]anull{rise},afade=t=out:st={max(0.0, seconds - FADE_OUT):.3f}:d={FADE_OUT}[ducked]"]
        voices, beds = "[vm]", [*beds, "[ducked]"]
    chains.append(f"{voices}{''.join(beds)}amix=inputs={1 + len(beds)}:duration=first:normalize=0[out]")
    _ffmpeg([*inputs, "-filter_complex", ";".join(chains), "-map", "[out]", "-t", f"{seconds:.3f}", str(dst)])
    return dst
