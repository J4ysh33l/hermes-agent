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


# Years read the way people say them. A voice engine reads "1880s" as a quantity ("one thousand eight
# hundred eighties"), so the text sent to it says "eighteen eighties". Captions keep the digits.
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
YEAR_CUE = r"(?:in|since|by|from|until|till|before|after|around|circa|c\.|year|of|during|early|late|mid|between|and|to|or)"
DECADE_AT = re.compile(r"(?<![\w,.])(1[1-9]\d0|20\d0)s\b")


def _two(n: int) -> str:
    return ONES[n] if n < 20 else TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")


def year_words(year: int) -> str:
    """1887 → "eighteen eighty-seven", 1905 → "nineteen oh five", 1900 → "nineteen hundred",
    2000 → "two thousand", 2007 → "two thousand and seven", 2024 → "twenty twenty-four"."""
    high, low = divmod(year, 100)
    if 2000 <= year <= 2009:
        return "two thousand" + (f" and {ONES[low]}" if low else "")
    return f"{_two(high)} " + ("hundred" if low == 0 else f"oh {ONES[low]}" if low < 10 else _two(low))


def _plural(words: str) -> str:
    last = words.rsplit(" ", 1)[-1]
    return words[: len(words) - len(last)] + (last[:-1] + "ies" if last.endswith("y") else last + "s")


def years_aloud(text: str) -> str:
    """Decades always ("1880s" → "eighteen eighties"); a bare year only after a word that marks a date
    ("in 1887", "since 2019", "from 1880 to 1885"), so "1500 people" stays a number."""
    text = DECADE_AT.sub(lambda m: _plural(year_words(int(m.group(1)))), text)
    span = re.compile(r"(?<![\w,.])(1[1-9]\d\d|20\d\d)(\s*(?:[–-]|to)\s*)(1[1-9]\d\d|20\d\d)\b(?![,.]\d)")
    text = span.sub(lambda m: year_words(int(m.group(1))) + (" to " if m.group(2).strip() in "–-" else m.group(2))
                    + year_words(int(m.group(3))), text)
    cued = re.compile(r"(\b" + YEAR_CUE + r"\s+|[–-]\s*)(1[1-9]\d\d|20\d\d)\b(?![,.]\d|s\b)", re.IGNORECASE)
    return cued.sub(lambda m: m.group(1) + year_words(int(m.group(2))), text)

