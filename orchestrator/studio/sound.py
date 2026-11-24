"""Sound under the voice: effects on the cuts and a music bed, mixed before the soundtrack is brought to
-14 LUFS (audio.py). The profile's ``elements.sfx`` / ``elements.music`` say off, auto or always.

Effects are made here, from formulas (ffmpeg ``aevalsrc``): nobody else's recording, so no licence to
track, and the same on every host. Each is placed so its peak lands where the eye expects it: a whoosh
on a push/whip/zoom transition, a hit on a flash, a riser into a burn, a pop when an emoji lands, and
(``always``) a tick as each list item appears. Made once into ``$HERMES_HOME/studio/sfx/``.

Music comes from ``$HERMES_HOME/studio/music/music.yaml``: the tracks you may use, each with its licence
and the credit to show; a file not listed (or listed without a licence) is never used. When it has nothing
for the page, one CC0 track is found on Openverse for the profile's ``elements.music_query`` (``fetch_music``,
or ``python -m orchestrator.studio music fetch "<words>"`` to stock up) and added to it; yours always win::

    - file: calm-pulse.mp3
      licence: CC0                     # or "Pixabay Content License", "CC BY 4.0", ...
      credit: "Calm Pulse by A. Artist (pixabay.com/music/...)"
      profiles: [paper]                # optional: only for these profiles
      mood: calm                       # optional, free text

The track is brought to one bed level (so a quiet and a loud track sit alike), looped or cut to the video,
faded in and out, and ducked under the voice (sidechain
compression: it dips while words are spoken and comes back up in the pauses). The credit goes into the
job's notes, which travel with the preview.
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
BED_LUFS = -33.0  # the music under the voice (Kokoro speaks near -18 LUFS), before ducking
MUSIC_SECONDS = (30, 600)  # a found track long enough to loop well, short enough to fetch quickly
NOT_MUSIC = re.compile(r"\b(vocals?|voice|speech|talk|podcast|spoken|sing(ing|er)?|acapella)\b", re.IGNORECASE)
FADE_IN, FADE_OUT = 0.6, 1.2


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
                             tuple(map(str, profiles if isinstance(profiles, list) else [profiles]))))
    return out


def _yours(home: Path, look: Profile) -> list[Track]:
    return [t for t in library(home) if isinstance(t, Track) and (not t.profiles or look.name in t.profiles)]


def _is_music(result: dict[str, Any], query: str) -> bool:
    seconds = (result.get("duration") or 0) / 1000
    tags = " ".join(str(t.get("name", "")) for t in result.get("tags") or [] if isinstance(t, dict))
    return (MUSIC_SECONDS[0] <= seconds <= MUSIC_SECONDS[1] and not NOT_MUSIC.search(f"{result.get('title', '')} {tags}")
            and openverse.relevance(result, query) >= 0.5)


def fetch_music(http: Http, home: Path, query: str, count: int = 1) -> list[Track]:
    """Up to ``count`` CC0/public-domain tracks for ``query`` from Openverse, downloaded into the music
    folder and listed in music.yaml (with licence, credit and where they came from)."""
    folder = home / "studio" / "music"
    listing = folder / "music.yaml"
    entries = (yaml.safe_load(listing.read_text(encoding="utf-8")) or []) if listing.is_file() else []
    known = {str(e.get("openverse")) for e in entries if isinstance(e, dict)}
    added: list[Track] = []
    for result in openverse.search(http, "audio", f"{query} music"):
        if len(added) >= count:
            break
        if str(result.get("id")) in known or not _is_music(result, query):
            continue
        try:
            body = http.request("GET", result["url"]).body
        except HttpError:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"ov-{str(result['id'])[:12]}.{result.get('filetype') or 'mp3'}"
        path.write_bytes(body)
        licence = openverse.LICENCE_NAMES[str(result["license"]).lower()]
        entries.append({"file": path.name, "licence": licence, "credit": openverse.credit(result, "Music"),
                        "mood": query, "openverse": str(result["id"])})
        added.append(Track(path, licence, entries[-1]["credit"], ()))
    if added:
        listing.write_text(yaml.safe_dump(entries, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return added


def plan(http: Http, home: Path, look: Profile, props: dict[str, Any], title: str) -> Plan:
    """The effects and music for one video. Music (``auto``/``always``): a track from your library for this
    profile, else one found for its ``music_query``; none to be had: no music (``always`` says so)."""
    elements = look.section("elements")
    found = cues(props, elements["sfx"])
    if elements["music"] == "off":
        return Plan(tuple(found), None, ())
    tracks = _yours(home, look) or fetch_music(http, home, elements["music_query"] or "calm")
    if not tracks:
        why = "no music: nothing in studio/music/music.yaml and none found on Openverse (sound.py)"
        return Plan(tuple(found), None, (why,) if elements["music"] == "always" else ())
    track = tracks[zlib.crc32(title.encode("utf-8")) % len(tracks)]  # the same video gets the same track
    return Plan(tuple(found), track, (f"music: {track.credit}" + ("" if track.licence in track.credit
                                                                     else f" ({track.licence})"),))


def _ffmpeg(args: list[str]) -> None:
    try:
        done = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-y", *args], capture_output=True, text=True,
                              timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioError(f"ffmpeg failed: {exc}") from None
    if done.returncode != 0:
        raise AudioError(f"ffmpeg failed: {done.stderr.strip()[-300:]}")


def _bed_gain(track: Path) -> float:
    """dB that bring the track to the bed level (a silent track gets none)."""
    level = float(measure(track)["input_i"])
    return 0.0 if level < -70 else max(-40.0, min(20.0, BED_LUFS - level))


def mix(home: Path, voice: Path, chosen: Plan, seconds: float, dst: Path) -> Path:
    """The voice with the plan's effects and ducked music, ``seconds`` long, into ``dst`` (WAV, not yet
    normalised). Nothing to add: the voice is copied."""
    if not chosen.cues and not chosen.music:
        dst.write_bytes(voice.read_bytes())
        return dst
    inputs, chains, beds = ["-i", str(voice)], [f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,apad=whole_dur={seconds:.3f}[v]"], []
    for n, cue in enumerate(chosen.cues, start=1):
        inputs += ["-i", str(effect(home, cue.name))]
        delay = round(cue.at * 1000)
        chains.append(f"[{n}:a]volume={LEVEL[cue.name]}dB,adelay={delay}|{delay}[s{n}]")
        beds.append(f"[s{n}]")
    voices = "[v]"
    if chosen.music:
        m = len(chosen.cues) + 1
        inputs += ["-stream_loop", "-1", "-i", str(chosen.music.path)]
        chains += ["[v]asplit=2[vk][vm]",
                   f"[{m}:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{seconds:.3f},"
                   f"volume={_bed_gain(chosen.music.path):.2f}dB,afade=t=in:d={FADE_IN},afade=t=out:st={max(0.0, seconds - FADE_OUT):.3f}:"
                   f"d={FADE_OUT}[bed]",
                   "[bed][vk]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=350[ducked]"]
        voices, beds = "[vm]", [*beds, "[ducked]"]
    chains.append(f"{voices}{''.join(beds)}amix=inputs={1 + len(beds)}:duration=first:normalize=0[out]")
    _ffmpeg([*inputs, "-filter_complex", ";".join(chains), "-map", "[out]", "-t", f"{seconds:.3f}", str(dst)])
    return dst
