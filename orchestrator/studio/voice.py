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
from dataclasses import dataclass, replace
from pathlib import Path

from orchestrator import llm
from orchestrator.brief.net import Http, HttpError

from . import direction
from .settings import Settings
from .text import sentences

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# Common Hindi words as they are typed in Latin script; a sentence with several is Hinglish.
HINGLISH = re.compile(r"\b(hai|hain|kya|nahi|nahin|aur|mein|main|hum|kaise|toh|yeh|ye|woh|wo|kar|karo|karna|ke|ki|"
                      r"ka|ko|se|bhi|tha|thi|hota|hoti|kyun|kyunki|aap|apna|apni|matlab|bahut|accha|achha|dekho|"
                      r"chalo|abhi|sab|koi|kuch|wala|wali|doston|yaar|bas|lekin|agar|jab|tak)\b", re.IGNORECASE)
TIMEOUT = 900  # seconds for one job (about 15 minutes of speech on 2 threads)
SLOW_TIMEOUT = 4 * 3600  # OmniVoice on a small CPU, with Whisper's check and retries: an overnight job

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
    sentence: int = 0  # which sentence this part belongs to (a direction can split one into parts)
    speed: float = 1.0  # × the page's speed ([slow] / [fast])
    pause: float = 0.0  # extra silence after it ([beat], [pause 0.8])
    last: bool = True  # the sentence's last part: the usual pause between sentences follows


@dataclass(frozen=True)
class Speech:
    path: Path
    seconds: float
    lines: tuple[tuple[str, float, float], ...]  # (text spoken, start, end) per sentence, for captions and cuts
    rewritten: int  # Hinglish sentences put into Devanagari by Gemini
    parts: tuple[tuple[tuple[float, float], ...], ...] = ()  # per sentence: each part's (start, end)
    misheard: tuple[str, ...] = ()  # OmniVoice: lines Whisper still heard wrong after the retries


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
    if engine == "omnivoice":
        return "clone", "clone"  # one voice, both languages
    return (settings.voice_en, settings.voice_hi) if engine == "kokoro" else \
        (settings.edge_voice_en, settings.edge_voice_hi)


def plan(http: Http, key: str, settings: Settings, text: str, engine: str = "") -> tuple[list[Line], int]:
    said = sentences(text)
    if not said:
        raise VoiceError("Nothing to say.")
    if sum(map(len, said)) > settings.max_chars:
        raise VoiceError(f"That's over {settings.max_chars} characters; split it (studio.max_chars).")
    for n, s in enumerate(said):
        wrong = direction.problems(s)
        if wrong:
            raise VoiceError(f"Sentence {n + 1}: {wrong[0]}")
    directed = [direction.parse(s) for s in said]
    hinglish = [n for n, d in enumerate(directed) if is_hinglish(d.text)]
    if hinglish:
        # The rewrite returns plain sentences: a Hinglish line keeps its pause before and after, not inside.
        for n, fixed in zip(hinglish, to_devanagari(http, key, settings, [directed[n].text for n in hinglish])):
            d = directed[n]
            directed[n] = direction.Directed(d.lead, (direction.Part(fixed, d.parts[0].speed, d.parts[-1].pause),))
    en, hi = _voices_for(settings, engine or settings.engine)
    lines: list[Line] = []
    for n, d in enumerate(directed):
        if lines and d.lead:
            lines[-1] = replace(lines[-1], pause=lines[-1].pause + d.lead)
        for k, part in enumerate(d.parts):
            voice, lang = (hi, "hi") if DEVANAGARI.search(part.text) else (en, "en-us")
            lines.append(Line(part.text, voice, lang, n, part.speed, part.pause, k == len(d.parts) - 1))
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
           "threads": settings.threads, "out": str(out), **_omni_job(settings, home),
           "lines": [{"text": ln.text, "voice": ln.voice, "lang": ln.lang,
                      "speed": round(min(2.0, settings.speed * ln.speed), 3),
                      "pause": round((settings.pause if ln.last else 0.0) + ln.pause, 3)} for ln in lines]}
    worker = Path(__file__).with_name("voice_worker.py")
    try:
        # -I: isolated, so the worker's folder is not on its path (the studio's queue.py and profile.py
        # would shadow the standard library's there)
        limit = SLOW_TIMEOUT if engine == "omnivoice" else TIMEOUT
        done = subprocess.run([str(python), "-I", str(worker)], input=json.dumps(job), capture_output=True, text=True,
                              timeout=limit, check=False)
    except subprocess.TimeoutExpired:
        raise VoiceError(f"{engine} took over {limit // 60} minutes; split the text.") from None
    if done.returncode != 0:
        tail = (done.stderr or "").strip().splitlines()[-1:] or ["no error text"]
        raise VoiceError(f"{engine} failed: {tail[0][:200]}")
    result = json.loads(done.stdout.strip().splitlines()[-1])
    lines_, parts = _sentences(lines, result["lines"])
    misheard = tuple(f"{' '.join(ln.text for ln in lines[a:b + 1])} (heard: {heard})"
                     for a, b, heard in result.get("misheard") or ())
    return Speech(out, float(result["seconds"]), lines_, rewritten, parts, misheard)


def voice_file(settings: Settings, home: Path) -> Path:
    return Path(settings.omni_voice) if settings.omni_voice else home / "studio/voices/me.pt"


OMNI_HALF = "omnivoice-bf16"  # in the models folder (install.sh --omnivoice)


def _omni_job(settings: Settings, home: Path) -> dict:
    found, half = voice_file(settings, home), _paths(settings, home)[1] / OMNI_HALF
    hindi = found.with_name(found.stem + "-hi" + found.suffix)
    return {"voice": str(found) if found.is_file() else "", "voice_hi": str(hindi) if hindi.is_file() else "",
            "omni_model": str(half) if half.is_dir() else "", "instruct": settings.omni_instruct,
            "steps": settings.omni_steps, "dtype": settings.omni_dtype, "check": settings.voice_check,
            "check_hi": settings.voice_check_hi if settings.voice_check else "", "wpm": settings.omni_wpm, "guidance": settings.omni_guidance,
            "retries": settings.voice_retries}


def clone(settings: Settings, home: Path, audio: Path, text: str = "", lang: str = "en") -> tuple[Path, str, float]:
    """Your recording → the OmniVoice voice file (once). ``text``: its exact words; "" = Whisper writes them
    and the first whole sentences up to 10 s are kept. Returns (file, the words it used, seconds)."""
    python, _models = _paths(settings, home)
    if not python.is_file():
        raise VoiceError(f"The studio's voices are not installed ({python} missing): run orchestrator/studio/install.sh --omnivoice")
    out = voice_file(settings, home)
    if lang == "hi":  # used for Hindi lines; English lines keep the English clip
        out = out.with_name(out.stem + "-hi" + out.suffix)
    out.parent.mkdir(parents=True, exist_ok=True)
    job = {"engine": "clone", "audio": str(audio), "text": text, "out": str(out), "seconds": 10, "lang": lang,
           "threads": settings.threads, "omni_model": _omni_job(settings, home)["omni_model"], "dtype": settings.omni_dtype, "check": settings.voice_check or "small"}
    worker = Path(__file__).with_name("voice_worker.py")
    try:
        done = subprocess.run([str(python), "-I", str(worker)], input=json.dumps(job), capture_output=True, text=True,
                              timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise VoiceError(f"cloning took over {TIMEOUT // 60} minutes") from None
    if done.returncode != 0:
        tail = (done.stderr or "").strip().splitlines()[-1:] or ["no error text"]
        raise VoiceError(f"cloning failed: {tail[0][:200]}")
    result = json.loads(done.stdout.strip().splitlines()[-1])
    return out, str(result["text"]), float(result["seconds"])


def _sentences(lines: list[Line], spans: list[list[float]]) -> tuple[tuple, tuple]:
    """Parts back into sentences: (text, start, end) each, and each sentence's parts' times."""
    joined: list[tuple[str, float, float]] = []
    parts: list[tuple[tuple[float, float], ...]] = []
    for ln, (a, b) in zip(lines, spans):
        if parts and len(parts) > ln.sentence:
            text, start, _end = joined[-1]
            joined[-1] = (f"{text} {ln.text}", start, float(b))
            parts[-1] += ((float(a), float(b)),)
        else:
            joined.append((ln.text, float(a), float(b)))
            parts.append(((float(a), float(b)),))
    return tuple(joined), tuple(parts)


VOICE_LISTS = {
    "omnivoice": "print('clone')",
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
