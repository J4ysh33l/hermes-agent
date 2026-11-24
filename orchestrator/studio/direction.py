"""Voice directions written inside the narration: pauses and pace. The voice obeys them; captions never
show them.

    And the winner is [beat] India.          a 0.4 s pause at that point
    [pause 1.2] Three years later...         an exact pause (0 to 3 s), here before the sentence
    [slow] This is the part that matters.    the rest of the sentence at 0.9× the page's speed
    [fast] Faster, cheaper, smaller.         the rest at 1.1×

A direction inside a sentence splits it into parts the voice reads one after another; the sentence is
still one sentence for scenes and captions, and each part keeps its own time so a caption never shows a
word before it is said. ``...`` and ``—`` need no direction: the voices already read them as a pause.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TOKEN = re.compile(r"\[\s*(beat|slow|fast|pause\s+(\d+(?:\.\d+)?))\s*\]", re.IGNORECASE)
BRACKET = re.compile(r"\[[^\]]*\]")
WORD = re.compile(r"\w")
BEAT = 0.4
MAX_PAUSE = 3.0
PACE = {"slow": 0.9, "fast": 1.1}


@dataclass(frozen=True)
class Part:
    text: str
    speed: float  # × the page's speed
    pause: float  # extra silence after this part, in seconds


@dataclass(frozen=True)
class Directed:
    lead: float  # silence asked for before the sentence (goes after the previous one)
    parts: tuple[Part, ...]

    @property
    def text(self) -> str:
        return " ".join(p.text for p in self.parts)


def strip(text: str) -> str:
    """The narration without directions (for captions, word counts and checks)."""
    return re.sub(r"\s+([,.!?;:।])", r"\1", re.sub(r"[ \t]{2,}", " ", TOKEN.sub(" ", text))).strip()


def problems(text: str) -> list[str]:
    found = []
    for raw in BRACKET.findall(text):
        match = TOKEN.fullmatch(raw)
        if not match:
            found.append(f"{raw} is not a direction (use [beat], [pause 0.8], [slow] or [fast])")
        elif match.group(2) and float(match.group(2)) > MAX_PAUSE:
            found.append(f"{raw}: at most {MAX_PAUSE:g} s")
    return found


def parse(sentence: str) -> Directed:
    lead, speed, parts = 0.0, 1.0, []
    pieces = TOKEN.split(sentence)  # text, word, number, text, word, number, ...
    for n in range(0, len(pieces), 3):
        text = pieces[n].strip()
        if WORD.search(text):
            parts.append(Part(text, speed, 0.0))
        elif text and parts:  # punctuation after a direction: "India [beat]."
            parts[-1] = Part(f"{parts[-1].text}{text}", parts[-1].speed, parts[-1].pause)
        if n + 1 >= len(pieces):
            break
        word, number = pieces[n + 1].lower(), pieces[n + 2]
        if word in PACE:
            speed = PACE[word]
            continue
        pause = min(MAX_PAUSE, float(number)) if number else BEAT
        if parts:
            parts[-1] = Part(parts[-1].text, parts[-1].speed, parts[-1].pause + pause)
        else:
            lead += pause
    return Directed(lead, tuple(parts))
