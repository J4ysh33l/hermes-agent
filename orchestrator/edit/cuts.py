"""What is kept of your talk: sentences (minus retakes and the ones the plan drops), minus fillers, with
long pauses shortened to the style's ``pace.max_pause``. Pure code on word times: no model decides a time.

A cut always falls between words, ``pace.pad`` seconds outside them (never more than half the gap), so no
consonant is clipped; each joint gets a 30 ms audio crossfade when rendered.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .style import Style
from .words import Sentence, Word
import itertools

PURE = {"um", "umm", "uh", "uhh", "uhm", "hmm", "hm", "er", "erm", "ah", "aa", "mm"}  # never words
SOFT = {"matlab", "basically", "actually", "like", "toh", "na", "yaani", "dekho"}  # fillers only when they stand alone
STANDALONE = 0.15  # seconds of pause on a side that make a word "stand alone"
RETAKE = 0.85  # similarity at which the earlier of two near sentences is a retake (one word in five different is not)
FALSE_START = 1.6  # seconds: a fragment this short that the next sentence restarts is dropped
SHORTEST = 0.2  # a kept range shorter than this is joined to its neighbour


@dataclass(frozen=True)
class Range:
    start: float  # in the source
    end: float

    @property
    def seconds(self) -> float:
        return self.end - self.start


@dataclass
class CutList:
    ranges: list[Range]
    dropped: dict[int, str] = field(default_factory=dict)  # sentence id → why
    fillers: list[str] = field(default_factory=list)  # "matlab @12.3s"
    kept_words: list[int] = field(default_factory=list)  # indexes into the transcript
    speed: float = 1.0  # the edit plays this much faster than you spoke (pace.speed; pitch kept)

    @property
    def seconds(self) -> float:
        return sum(r.seconds for r in self.ranges) / self.speed

    def to_output(self, t: float) -> float:
        """A source time → its time in the edited video (a time inside a cut lands at the joint)."""
        out = 0.0
        for r in self.ranges:
            if t < r.start:
                return out / self.speed
            if t <= r.end:
                return (out + t - r.start) / self.speed
            out += r.seconds
        return out / self.speed

    def to_source(self, t: float) -> float:
        """A time in the edited video → the source time it shows."""
        out, t = 0.0, t * self.speed
        for r in self.ranges:
            if t <= out + r.seconds:
                return r.start + max(0.0, t - out)
            out += r.seconds
        return self.ranges[-1].end if self.ranges else t

    def as_dict(self) -> dict:
        return {"ranges": [[round(r.start, 3), round(r.end, 3)] for r in self.ranges], "seconds": round(self.seconds, 2),
                "dropped": {f"S{k}": v for k, v in sorted(self.dropped.items())}, "fillers": self.fillers}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower())


def retakes(found: list[Sentence]) -> dict[int, str]:
    """Sentences you said again: the earlier take of each pair, and false starts the next sentence restarts."""
    out: dict[int, str] = {}
    for n, s in enumerate(found):
        mine = _tokens(s.text)
        if not mine:
            continue
        for later in found[n + 1:n + 4]:
            theirs = _tokens(later.text)
            if later.start - s.end > 20:
                break
            similar = difflib.SequenceMatcher(None, mine, theirs).ratio()
            short_restart = (s.end - s.start <= FALSE_START and len(mine) >= 2 and theirs[:2] == mine[:2])
            if similar >= RETAKE or short_restart or (len(mine) >= 3 and theirs[:len(mine)] == mine):
                out[s.id] = f"retake of S{later.id}" if similar >= RETAKE else f"false start, said again in S{later.id}"
                break
    return out


def _bare(word: Word) -> str:
    return re.sub(r"[^\w']", "", word.text.lower())


def fillers(words: list[Word], mode: str) -> set[int]:
    if mode == "keep":
        return set()
    found = set()
    for n, w in enumerate(words):
        bare = _bare(w)
        if bare not in PURE and bare not in SOFT:
            continue
        before = w.start - words[n - 1].end if n else 9.0
        after = words[n + 1].start - w.end if n + 1 < len(words) else 9.0
        comma = bool(re.search(r"[,.…]$", w.text)) or (n and re.search(r"[,.…]$", words[n - 1].text))
        alone = before >= STANDALONE or after >= STANDALONE or bool(comma)
        if bare in PURE and (alone or mode == "all") or bare in SOFT and alone and (before >= STANDALONE and after >= STANDALONE or comma and max(before, after) >= STANDALONE):
            found.add(n)
    return found


def build(words: list[Word], found: list[Sentence], look: Style, drop: dict[int, str] | None = None,
          trim: dict[int, tuple[int, int]] | None = None, keep_ids: set[int] | frozenset[int] = frozenset(),
          cut: dict[int, list[tuple[int, int]]] | None = None) -> CutList:
    """``drop``: sentence id → reason (from the plan, added to the retakes found here); ``trim``: sentence id →
    (first word, last word) to keep, counted from 1 inside the sentence; ``keep_ids``: sentences the plan keeps
    although code took them for retakes."""
    pace = look["pace"]
    dropped = {k: v for k, v in retakes(found).items() if k not in keep_ids} if pace["retakes"] else {}
    dropped.update(drop or {})
    keep: list[int] = []
    for s in found:
        if s.id in dropped:
            continue
        a, b = (trim or {}).get(s.id, (1, len(s.words)))
        out = set()  # words cut from the middle (plan "cut"): a repeat, "of all of these ... the best way to do"
        for x, y in (cut or {}).get(s.id, []):
            out |= set(range(s.first + x - 1, s.first + y))
        keep += [n for n in range(s.first + max(1, a) - 1, s.first + min(len(s.words), b)) if n not in out]
    gone = fillers(words, pace["fillers"])
    keep = [n for n in keep if n not in gone]
    cl = CutList([], dropped, [f"{words[n].text} @{words[n].start:.1f}s" for n in sorted(gone)], keep,
                 float(pace.get("speed", 1.0)))
    if not keep:
        return cl
    longest, pad = float(pace["max_pause"]), float(pace["pad"])
    runs: list[list[int]] = [[keep[0]]]
    for prev, n in itertools.pairwise(keep):
        gap = words[n].start - words[prev].end
        (runs[-1].append(n) if n == prev + 1 and gap <= longest else runs.append([n]))
    ranges = []
    for k, run in enumerate(runs):
        first, last = words[run[0]], words[run[-1]]
        room_before = first.start - (words[run[0] - 1].end if run[0] else 0.0)
        room_after = (words[run[-1] + 1].start if run[-1] + 1 < len(words) else last.end + 1.0) - last.end
        start = first.start - min(pad, room_before / 2 if run[0] else pad)
        end = last.end + min(pad, room_after / 2)
        if k and runs[k - 1][-1] + 1 == run[0]:  # a long pause shortened: keep up to max_pause of it in total
            start = first.start - min(longest / 2, room_before / 2)
        if k + 1 < len(runs) and run[-1] + 1 == runs[k + 1][0]:
            end = last.end + min(longest / 2, room_after / 2)
        ranges.append(Range(max(0.0, start), end))
    merged: list[Range] = []
    for r in ranges:
        if merged and (r.start - merged[-1].end < 0.02 or (r.seconds < SHORTEST and r.start - merged[-1].end < 0.3)):
            merged[-1] = Range(merged[-1].start, max(merged[-1].end, r.end))
        else:
            merged.append(r)
    cl.ranges = merged
    return cl
