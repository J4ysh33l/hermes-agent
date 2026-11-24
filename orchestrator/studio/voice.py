"""Text → speech with Kokoro (on the host CPU, free, no limits) or Edge TTS (Microsoft's online
read-aloud voices: unofficial, needs the internet, no CPU). ``studio.engine`` picks the default.

Both read English, and Hindi **written in Devanagari**. Hinglish written in Latin script comes out
garbled from its Hindi voice (tested: Whisper heard nonsense), so such sentences are first rewritten
in Devanagari by Gemini (one call for the whole text; English words keep their sound, e.g.
"product" → "प्रोडक्ट"). The rewrite is checked: same number of sentences, and Devanagari where
Hinglish was; otherwise nothing is spoken and you are told why.

Each sentence goes to the voice for its script (``voice_en``/``voice_hi`` for Kokoro,
``edge_voice_en``/``edge_voice_hi`` for Edge). Both engines run in the studio's own environment
(``install.sh``) through ``voice_worker.py``.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from orchestrator import llm
from orchestrator.brief.net import Http, HttpError

from .settings import Settings

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
SENTENCE = re.compile(r"(?<=[.!?।])\s+|\n+")
# Common Hindi words as they are typed in Latin script; a sentence with several is Hinglish.
HINGLISH = re.compile(r"\b(hai|hain|kya|nahi|nahin|aur|mein|main|hum|kaise|toh|yeh|ye|woh|wo|kar|karo|karna|ke|ki|"
                      r"ka|ko|se|bhi|tha|thi|hota|hoti|kyun|kyunki|aap|apna|apni|matlab|bahut|accha|achha|dekho|"
                      r"chalo|abhi|sab|koi|kuch|wala|wali|doston|yaar|bas|lekin|agar|jab|tak)\b", re.IGNORECASE)
TIMEOUT = 900  # seconds for one job (about 15 minutes of speech on 2 threads)

REWRITE = """Rewrite each line below in Devanagari script, keeping every word and its meaning: Hindi words in
Hindi spelling, English words written as they sound in Devanagari (product → प्रोडक्ट, startup →
स्टार्टअप). Keep numbers as digits. Do not translate, add or drop anything. Answer JSON only:
{{"lines": ["...", "..."]}} with exactly {count} lines, in the same order.

{lines}"""


class VoiceError(Exception):
    """Shown as it is; nothing was spoken."""


@dataclass(frozen=True)
class Line:
    text: str
    voice: str
    lang: str


@dataclass(frozen=True)
class Speech:
    path: Path
    seconds: float
    lines: tuple[tuple[str, float, float], ...]  # (text spoken, start, end) for captions and cuts
    rewritten: int  # Hinglish sentences put into Devanagari by Gemini


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE.split(text or "") if s.strip()]


def is_hinglish(sentence: str) -> bool:
    words = re.findall(r"[A-Za-z]+", sentence)
    return not DEVANAGARI.search(sentence) and len(words) >= 2 and \
        len(HINGLISH.findall(sentence)) >= max(2, len(words) // 6)


def to_devanagari(http: Http, key: str, settings: Settings, lines: list[str]) -> list[str]:
    if not key:
        raise VoiceError("Hinglish in Latin script needs GEMINI_API_KEY to be put into Devanagari first "
                         "(or write those lines in Devanagari yourself).")
    prompt = REWRITE.format(count=len(lines), lines="\n".join(f"{n}. {s}" for n, s in enumerate(lines, 1)))
    schema = {"type": "object", "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
              "required": ["lines"]}
    problems = []
    for model in settings.text_models:
        try:
            raw = llm.gemini(http, key, model.id, prompt, workflow="studio", step="devanagari",
                             json_mode=model.json_mode, schema=schema if model.json_mode else None,
                             max_output_tokens=200 + 80 * sum(len(s.split()) for s in lines))
            found = json.loads(re.search(r"\{.*\}", raw, re.DOTALL).group(0))["lines"]
        except (HttpError, ValueError, AttributeError, KeyError, TypeError) as exc:
            problems.append(f"{model.id}: {str(exc)[:80]}")
            continue
        found = [re.sub(r"^\d+\.\s*", "", str(s)).strip() for s in found]
        if len(found) == len(lines) and all(DEVANAGARI.search(s) for s in found):
            return found
        problems.append(f"{model.id}: gave {len(found)} lines for {len(lines)}, or not in Devanagari")
    raise VoiceError("Could not put the Hinglish lines into Devanagari: " + "; ".join(problems))


def _voices_for(settings: Settings, engine: str) -> tuple[str, str]:
    return (settings.voice_en, settings.voice_hi) if engine == "kokoro" else \
        (settings.edge_voice_en, settings.edge_voice_hi)


def plan(http: Http, key: str, settings: Settings, text: str, engine: str = "") -> tuple[list[Line], int]:
    said = sentences(text)
    if not said:
        raise VoiceError("Nothing to say.")
    if sum(map(len, said)) > settings.max_chars:
        raise VoiceError(f"That's over {settings.max_chars} characters; split it (studio.max_chars).")
    hinglish = [n for n, s in enumerate(said) if is_hinglish(s)]
    if hinglish:
        for n, fixed in zip(hinglish, to_devanagari(http, key, settings, [said[n] for n in hinglish])):
            said[n] = fixed
    en, hi = _voices_for(settings, engine or settings.engine)
    lines = [Line(s, hi, "hi") if DEVANAGARI.search(s) else Line(s, en, "en-us") for s in said]
    return lines, len(hinglish)


def _paths(settings: Settings, home: Path) -> tuple[Path, Path]:
    python = Path(settings.studio_python) if settings.studio_python else home / "venvs/studio/bin/python"
    models = Path(settings.models_dir) if settings.models_dir else home / "studio/models"
    return python, models


def speak(http: Http, key: str, settings: Settings, home: Path, text: str, out: Path, engine: str = "") -> Speech:
    engine = engine or settings.engine
    lines, rewritten = plan(http, key, settings, text, engine)
    python, models = _paths(settings, home)
    if not python.is_file():
        raise VoiceError(f"The studio's voices are not installed ({python} missing): run orchestrator/studio/install.sh")
    out.parent.mkdir(parents=True, exist_ok=True)
    job = {"engine": engine, "model": str(models / settings.kokoro_model), "voices": str(models / "voices-v1.0.bin"),
           "threads": settings.threads, "out": str(out),
           "lines": [{"text": ln.text, "voice": ln.voice, "lang": ln.lang, "speed": settings.speed,
                      "pause": settings.pause} for ln in lines]}
    worker = Path(__file__).with_name("voice_worker.py")
    try:
        done = subprocess.run([str(python), str(worker)], input=json.dumps(job), capture_output=True, text=True,
                              timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise VoiceError(f"{engine} took over {TIMEOUT // 60} minutes; split the text.") from None
    if done.returncode != 0:
        tail = (done.stderr or "").strip().splitlines()[-1:] or ["no error text"]
        raise VoiceError(f"{engine} failed: {tail[0][:200]}")
    result = json.loads(done.stdout.strip().splitlines()[-1])
    spans = tuple((ln.text, float(a), float(b)) for ln, (a, b) in zip(lines, result["lines"]))
    return Speech(out, float(result["seconds"]), spans, rewritten)


VOICE_LISTS = {
    "kokoro": "import numpy, sys; print(' '.join(sorted(numpy.load(sys.argv[1]).files)))",
    "edge": ("import asyncio, edge_tts; print(' '.join(sorted(v['ShortName'] for v in asyncio.run(edge_tts.list_voices()) "
             "if v['Locale'] in ('en-IN', 'hi-IN', 'en-US', 'en-GB'))))"),
}


def voices(settings: Settings, home: Path, engine: str = "") -> list[str]:
    """The engine's voice names: Kokoro's from its voices file; Edge's Indian, US and UK ones online."""
    python, models = _paths(settings, home)
    done = subprocess.run([str(python), "-c", VOICE_LISTS[engine or settings.engine], str(models / "voices-v1.0.bin")],
                          capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise VoiceError("Could not list the voices: run orchestrator/studio/install.sh (Edge also needs the internet)")
    return done.stdout.split()
