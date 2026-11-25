"""Your words with their times, grouped into numbered sentences: what the editor (Claude) decides on.
Standard library only (it is copied into the handoff repo for Claude's own checks)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

END = re.compile(r"[.!?…]$")
SOFT_END = re.compile(r"[,;:]$")
LONGEST = 24  # words: a run-on sentence is split at a comma or a pause after this many
GAP = 0.7  # a pause this long ends a sentence even without a full stop (Whisper often leaves them out)
DEVANAGARI = re.compile(r"[\u0900-\u097f]")


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float
    prob: float = 1.0

@dataclass(frozen=True)
class Sentence:
    id: int
    words: tuple[Word, ...]
    first: int  # index of its first word in the whole transcript

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

def load(path: Path) -> list[Word]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Word(str(w["w"]), float(w["s"]), float(w["e"]), float(w.get("p", 1.0))) for w in raw["words"]]

def sentences(words: list[Word]) -> list[Sentence]:
    """Sentences by punctuation, long pauses and length; numbered from 1."""
    found: list[Sentence] = []
    start = 0
    for n, word in enumerate(words):
        last = n == len(words) - 1
        pause = 0.0 if last else words[n + 1].start - word.end
        size = n - start + 1
        if last or END.search(word.text) or pause >= GAP or (size >= LONGEST and (SOFT_END.search(word.text) or pause > 0.25)):
            for a, b in _split_run(words, start, n + 1):
                found.append(Sentence(len(found) + 1, tuple(words[a:b]), a))
            start = n + 1
    return found


RUN_MAX = 30  # words: a longer "sentence" (Whisper left out the stops) is split at its longest pauses
RUN_MIN = 6


def _split_run(words: list[Word], a: int, b: int) -> list[tuple[int, int]]:
    """[a, b) as one piece, or split at the longest gap between words (the middle one on a tie) until every
    piece has at most RUN_MAX words."""
    if b - a <= RUN_MAX:
        return [(a, b)]
    middle = (a + b) / 2
    cut = max(range(a + RUN_MIN, b - RUN_MIN + 1),
              key=lambda k: (round(words[k].start - words[k - 1].end, 2), -abs(k - middle)))
    return _split_run(words, a, cut) + _split_run(words, cut, b)

def numbered(found: list[Sentence]) -> str:
    """What the editor reads: one line per sentence with its length and the pause before it."""
    lines = []
    for n, s in enumerate(found):
        gap = s.start - found[n - 1].end if n else s.start
        unsure = sum(w.prob < 0.5 for w in s.words)
        lines.append(f"S{s.id} [{s.end - s.start:.1f}s, pause before {gap:.1f}s{f', {unsure} unclear words' if unsure else ''}] {s.text}")
    return "\n".join(lines)

def has_devanagari(words: list[Word]) -> bool:
    return any(DEVANAGARI.search(w.text) for w in words)
