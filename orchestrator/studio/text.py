"""Narration as text: sentences, what the voice actually says, and how many words that is.

Standard library only (with ``direction``), like ``storyboard`` and ``rules``: these modules are also
committed to the handoff repo, where Claude runs the same checks on its own answer (``rules``).
"""

from __future__ import annotations

import re

from . import direction

SENTENCE = re.compile(r"(?<=[.!?।])\s+|\n+")
NUMERAL = re.compile(r"^\d[\d,]*(?:\.\d+)?(?:st|nd|rd|th|s)?$")
YEAR = re.compile(r"^1[1-9]\d\d$|^20\d\d$")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE.split(text or "") if s.strip()]


def spoken(say: object) -> str:
    """What the voice says: no *emphasis* marks, no [directions]."""
    return direction.strip(str(say).replace("*", ""))


def _under_thousand(n: int) -> int:
    """Words in 1–999 read aloud: "three hundred thirty" = 3."""
    hundreds, rest = divmod(n, 100)
    return (2 if hundreds else 0) + (0 if not rest else 1 if rest < 20 or rest % 10 == 0 else 2)


def _numeral_words(token: str) -> int:
    """How many words a voice says for a written number: 1887 → "eighteen eighty-seven" (3)."""
    bare = re.sub(r"(st|nd|rd|th|s)$", "", token).replace(",", "")
    whole, _dot, decimals = bare.partition(".")
    if YEAR.match(whole) and not decimals:
        return 3
    n = int(whole or 0)
    words = 0
    for scale in range(4):  # ones, thousand, million, billion
        group = n // 1000 ** scale % 1000
        words += _under_thousand(group) + (1 if group and scale else 0)
    return max(1, words) + (1 + len(decimals) if decimals else 0)  # "point five"


def said_words(say: object) -> int:
    """Words as the voice says them: a number counts as the words it is read as, so a script full of
    years and figures is budgeted for the time it really takes (1887 is three spoken words, not one)."""
    tokens = (w.strip(".,") for w in re.sub(r"[^\w\s.,'’]", " ", spoken(say)).split())
    return sum(_numeral_words(w) if NUMERAL.match(w) else 1 for w in tokens if re.search(r"\w", w))
