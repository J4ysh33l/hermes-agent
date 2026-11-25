"""Captions burned in by ffmpeg (libass): your words as transcribed, in Latin letters, a few at a time, on
the times they are said in the edited video. Cheap to render, and the style sets every part of the look.

A page breaks at a sentence end, a comma or a pause, never leaves a lone word when it can join one, and
steps aside while a card graphic shows (the card carries the message). The soft shadow is a blurred copy
underneath, which reads cleaner than a hard outline.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .cuts import CutList
from .words import Word

if TYPE_CHECKING:
    from .style import Style

W, H = 1080, 1920
REMOTION = Path(__file__).resolve().parents[1] / "studio" / "remotion" / "node_modules" / "@fontsource"
# style font → (family name inside the file, as libass matches it; fontsource file; ask for bold)
FONT_FILES = {
    "manrope": ("Manrope ExtraBold", "manrope/files/manrope-latin-800-normal.woff", True),
    "inter": ("Inter", "inter/files/inter-latin-700-normal.woff", True),
    "poppins": ("Poppins", "poppins/files/poppins-latin-700-normal.woff", True),
    "intertight": ("Inter Tight", "inter-tight/files/inter-tight-latin-700-normal.woff", True),
    "montserrat": ("Montserrat", "montserrat/files/montserrat-latin-700-normal.woff", True),
    "anton": ("Anton", "anton/files/anton-latin-400-normal.woff", False),
    "newsreader": ("Newsreader SemiBold", "newsreader/files/newsreader-latin-600-normal.woff", True),
}
BREAK = re.compile(r"[.!?,;:…]$")
PAUSE = 0.3  # seconds of silence (after the cut) that end a page
HOLD = 0.15  # a page stays this long after its last word when nothing follows at once


@dataclass(frozen=True)
class Page:
    start: float
    end: float
    words: tuple[tuple[str, float, float], ...]  # (text, start, end) in output time


def _clean(text: str, case: str) -> str:
    text = re.sub(r"[^\w'%₹$?!&+\-×/]", "", text) or text
    text = text.rstrip("!") if case != "upper" else text
    return text.lower() if case == "lower" else text.upper() if case == "upper" else text


def pages(words: list[Word], cut: CutList, look: Style, hidden: list[tuple[float, float]] = ()) -> list[Page]:
    c = look["captions"]
    size = int(c["words"])
    timed = [(words[n].text, cut.to_output(words[n].start), cut.to_output(words[n].end)) for n in cut.kept_words]
    groups: list[list[tuple[str, float, float]]] = [[]]
    for k, (text, a, b) in enumerate(timed):
        groups[-1].append((text, a, b))
        nxt = timed[k + 1] if k + 1 < len(timed) else None
        if nxt is None or len(groups[-1]) >= size or BREAK.search(text) or nxt[1] - b > PAUSE:
            groups.append([])
    groups = [g for g in groups if g]
    merged: list[list[tuple[str, float, float]]] = []
    for g in groups:  # a lone word joins the page before it when that page ended without a stop
        if merged and len(g) == 1 and len(merged[-1]) <= size and not re.search(r"[.!?…]$", merged[-1][-1][0]) \
                and g[0][1] - merged[-1][-1][2] <= PAUSE:
            merged[-1] = merged[-1] + g
        else:
            merged.append(g)
    out = []
    for k, g in enumerate(merged):
        start = g[0][1]
        follow = merged[k + 1][0][1] if k + 1 < len(merged) else None
        end = follow if follow is not None and follow - g[-1][2] <= 0.35 else g[-1][2] + HOLD
        shown = [(_clean(t, c["case"]), a, b) for t, a, b in g]
        shown = [w for w in shown if w[0]]
        if shown and not any(h0 - 0.1 < end and start < h1 + 0.25 for h0, h1 in hidden):  # never over a card, even leaving
            out.append(Page(start, end, tuple(shown)))
    return out


def _ass_colour(hex_colour: str, alpha: float = 0.0) -> str:
    r, g, b = hex_colour[1:3], hex_colour[3:5], hex_colour[5:7]
    return f"&H{round(alpha * 255):02X}{b}{g}{r}".upper()


def _time(t: float) -> str:
    t = max(0.0, t)
    cs = round(t * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


SEAM_Y = 960  # during a split screen the captions sit on the seam between picture and face


def ass(found: list[Page], look: Style, seam: list[tuple[float, float]] = ()) -> str:
    c = look["captions"]
    family = FONT_FILES[c["font"]][0]
    normal_y = round(c["y"] * H)
    boxed = c["box"] != "none"
    style = ("Style: Cap,{font},{size},{fill},{fill},{outline},{back},{bold},0,0,0,100,100,0,0,{border},{outw},0,5,40,40,0,1"
             .format(font=family, bold=-1 if FONT_FILES[c["font"]][2] else 0, size=round(c["size"] * 1.33), fill=_ass_colour(c["colour"]),
                     outline=_ass_colour(c["box"] if boxed else "#000000", 1 - c["box_opacity"] if boxed else 0),
                     back=_ass_colour(c["box"] if boxed else "#000000", 1 - c["box_opacity"] if boxed else 1),
                     border=3 if boxed else 1, outw=max(8, c["outline"]) if boxed else c["outline"]))
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
             "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
             "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
             "MarginR, MarginV, Encoding", style, "", "[Events]",
             "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    shadow = int(c["shadow"])
    for page in found:
        text = " ".join(w for w, _a, _b in page.words)
        y = SEAM_Y if any(a - 0.05 <= page.start < b for a, b in seam) else normal_y
        if shadow and not boxed:
            lines.append(f"Dialogue: 0,{_time(page.start)},{_time(page.end)},Cap,,0,0,0,,"
                         f"{{\\pos({W // 2 + shadow // 2},{y + shadow})\\c&H000000&\\3c&H000000&\\alpha&H70&\\blur{shadow * 2}}}{text}")
        if c["active"] == "none":
            lines.append(f"Dialogue: 1,{_time(page.start)},{_time(page.end)},Cap,,0,0,0,,{{\\pos({W // 2},{y})}}{text}")
            continue
        active = _ass_colour(c["active"])[4:]
        for k, (_w, a, _b) in enumerate(page.words):  # one event per spoken word, that word in the accent
            end = page.words[k + 1][1] if k + 1 < len(page.words) else page.end
            parts = [f"{{\\c&H{active}&}}{w}{{\\r}}" if j == k else w for j, (w, _x, _y) in enumerate(page.words)]
            lines.append(f"Dialogue: 1,{_time(a if k else page.start)},{_time(end)},Cap,,0,0,0,,{{\\pos({W // 2},{y})}}" + " ".join(parts))
    return "\n".join(lines) + "\n"


def write(found: list[Page], look: Style, folder: Path, seam: list[tuple[float, float]] = ()) -> tuple[Path, Path]:
    """captions.ass and the fonts folder libass reads it with."""
    fonts = folder / "fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    source = REMOTION / FONT_FILES[look["captions"]["font"]][1]
    if not source.is_file():
        raise FileNotFoundError(f"caption font missing: {source} (cd orchestrator/studio/remotion && npm ci)")
    shutil.copy(source, fonts / source.name)
    path = folder / "captions.ass"
    path.write_text(ass(found, look, seam), encoding="utf-8")
    return path, fonts
