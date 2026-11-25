"""Runs inside the studio's own virtual environment ($HERMES_HOME/venvs/studio), never in Hermes'.

Reads one JSON job on stdin and writes one 24 kHz mono 16-bit WAV:
  {"engine": "kokoro" | "edge", "out": "x.wav", "threads": 2,
   "model": "...onnx", "voices": "...bin",                       (kokoro)
   "lines": [{"text": "...", "voice": "am_michael", "lang": "en-us", "speed": 1.05, "pause": 0.25}, ...]}
Prints one JSON line: {"seconds": 12.3, "sample_rate": 24000, "lines": [[start, end], ...]} (each
line's place in the file, for captions and cuts). Silence around each line is trimmed, so "pause" alone
sets the gap between sentences.

- kokoro: Kokoro-82M ONNX on the CPU (kokoro-onnx).
- edge: Microsoft Edge's online read-aloud voices (edge-tts; unofficial, needs the internet). Each line
  comes back as MP3 and is decoded with ffmpeg.
- omnivoice: k2-fsa OmniVoice (0.6B, CPU) in your cloned voice ("voice": a prompt file made once by
  "clone" below) or a described one ("instruct"). Extra keys: "steps" (16 fast, 32 best), "dtype" (bf16
  halves the weights' memory), "check" (a faster-whisper model name, "" = no check), "retries".
  Paragraphs: consecutive lines of the same language and speed (up to ~45 words) are spoken in one
  call and checked in one Whisper pass; Whisper's word times cut them back into lines (at the quietest
  moment between them), so captions and pauses still work per line.
  Memory: OmniVoice and Whisper are never loaded together. All paragraphs are spoken, OmniVoice is
  freed, Whisper listens to each, is freed, and only misheard paragraphs are spoken again (new seed).
  Peak = the larger of the two, not their sum. The output gains "misheard":
  [[first line, last line, what Whisper heard], ...] for paragraphs still wrong at the end.

  {"engine": "convert", "out": "<models>/omnivoice-bf16"} makes the half-size copy (install.sh does it).
  {"engine": "clone", "audio": "me.m4a", "text": "" or its exact words, "out": "me.pt", "seconds": 10}
  makes the voice file once: Whisper writes the transcript when "text" is empty (then is freed), the
  first whole sentences up to "seconds" are kept (OmniVoice clones best from 3–10 s), and OmniVoice
  encodes them. Prints {"seconds": ..., "text": ...}.

Imports nothing from this repo: only that environment has these packages.
"""

import asyncio
import json
import subprocess
import sys
import wave
from itertools import pairwise

RATE = 24000
EDGE_TIMEOUT = 120  # seconds for one line from Microsoft, and for decoding it


def _kokoro(job: dict, line: dict, state: dict):
    import numpy as np
    if "kokoro" not in state:
        import onnxruntime as ort
        from kokoro_onnx import Kokoro
        options = ort.SessionOptions()
        options.intra_op_num_threads = int(job.get("threads", 2))
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(job["model"], options, providers=["CPUExecutionProvider"])
        state["kokoro"] = Kokoro.from_session(session, job["voices"])
    samples, rate = state["kokoro"].create(line["text"], voice=line["voice"], speed=float(line["speed"]),
                                           lang=line["lang"])
    if rate != RATE:
        raise SystemExit(f"Kokoro returned {rate} Hz, expected {RATE}")
    return np.asarray(samples, dtype="float32")


def _edge(_job: dict, line: dict, _state: dict):
    import edge_tts
    import numpy as np

    async def fetch() -> bytes:
        percent = round((float(line["speed"]) - 1) * 100)
        talk = edge_tts.Communicate(line["text"], line["voice"], rate=f"{percent:+d}%")
        return b"".join([chunk["data"] async for chunk in talk.stream() if chunk["type"] == "audio"])

    mp3 = asyncio.run(asyncio.wait_for(fetch(), timeout=EDGE_TIMEOUT))
    if not mp3:
        raise SystemExit(f"Edge returned no audio for voice {line['voice']}")
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", str(RATE),
                          "pipe:1"], input=mp3, capture_output=True, check=True, timeout=EDGE_TIMEOUT).stdout
    return np.frombuffer(pcm, dtype="<i2").astype("float32") / 32767


def _collect() -> None:
    """After the caller's ``del``: give the freed model's memory back before the next one loads."""
    import ctypes
    import gc
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)  # glibc keeps freed memory otherwise
    except (OSError, AttributeError):
        pass


def _omni(job: dict):
    """bf16: the half-size copy ``convert`` made (~1.9 GB peak, ~3× faster on CPU); fp32: the original
    (~2.9 GB). Never bf16 cast at load time: that reads all fp32 weights into memory first (~4.2 GB)."""
    import torch
    from omnivoice import OmniVoice
    torch.set_num_threads(int(job.get("threads", 2)))
    half = job.get("dtype", "bf16") == "bf16" and job.get("omni_model")
    return OmniVoice.from_pretrained(job["omni_model"] if half else "k2-fsa/OmniVoice", device_map="cpu",
                                     dtype=torch.bfloat16 if half else torch.float32)


def convert(job: dict) -> dict:
    """The half-size (bf16) copy of OmniVoice, once, one tensor at a time: the fp32 file is only mapped
    (pages the system can drop), so this needs ~1.3 GB of real memory."""
    import os
    import shutil

    import torch
    from huggingface_hub import snapshot_download
    from safetensors import safe_open
    from safetensors.torch import save_file
    src, dst = snapshot_download("k2-fsa/OmniVoice"), job["out"]
    shutil.copytree(src, dst, dirs_exist_ok=True,  # the audio tokenizer stays as it is
                    ignore=lambda d, names: ["model.safetensors"] if os.path.samefile(d, src) else [])
    out = {}
    with safe_open(os.path.join(src, "model.safetensors"), "pt") as f:
        meta = f.metadata()
        for key in f.keys():
            t = f.get_tensor(key)
            out[key] = t.to(torch.bfloat16) if t.dtype == torch.float32 else t
    save_file(out, os.path.join(dst, "model.safetensors.part"), metadata=meta)
    os.replace(os.path.join(dst, "model.safetensors.part"), os.path.join(dst, "model.safetensors"))
    return {"ready": dst}


def _to16k(samples, rate: int = RATE):
    import numpy as np
    n = int(len(samples) * 16000 / rate)
    return np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples).astype("float32")


def _whisper(job: dict):
    from faster_whisper import WhisperModel
    return WhisperModel(job.get("check") or "small", device="cpu", compute_type="int8",
                        cpu_threads=int(job.get("threads", 2)))


def _words(text: str) -> list[str]:
    import re
    return re.findall(r"[\w']+", re.sub(r"\[[^\]]*\]|\*", " ", text).lower())


def _heard_right(want: str, heard: str) -> bool:
    """Whisper heard (nearly) the words that were meant: 85% of them in order."""
    import difflib
    a, b = _words(want), _words(heard)
    return not a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


PARAGRAPH_WORDS = 45  # ~15 s: one OmniVoice call and one Whisper pass per paragraph, not per line
SHORTEST = 10  # words: a shorter paragraph joins the one before it (same language and speed)
FILL = 1.3  # OmniVoice's own pauses inside a paragraph (cut out later): time asked = speaking time × this (measured)
PACE_SLACK = 0.12  # a paragraph whose speaking rate is further than this from the target is spoken again
SHORTEST_SAY = 1.2  # seconds: never ask for less


def _paragraphs(lines: list[dict], most: int = PARAGRAPH_WORDS) -> list[list[int]]:
    """Consecutive lines spoken in one go: same language and speed, up to ``most`` words."""
    groups: list[list[int]] = []
    for i, line in enumerate(lines):
        last = groups[-1] if groups else []
        if last and (lines[last[0]]["lang"], float(lines[last[0]]["speed"])) == (line["lang"], float(line["speed"])) \
                and sum(len(_words(lines[k]["text"])) for k in last) + len(_words(line["text"])) <= most:
            last.append(i)
        else:
            groups.append([i])
    merged: list[list[int]] = []
    for g in groups:  # a tail of a few words is too short to say well alone: it joins the paragraph before
        prev = merged[-1] if merged else []
        if prev and sum(len(_words(lines[k]["text"])) for k in g) < SHORTEST and \
                (lines[prev[0]]["lang"], float(lines[prev[0]]["speed"])) == (lines[g[0]]["lang"], float(lines[g[0]]["speed"])):
            prev.extend(g)
        else:
            merged.append(list(g))
    return merged


def _quietest(audio, start: float, end: float) -> int:
    """The sample in [start, end] s where the 20 ms around it is quietest: where one line ends."""
    import numpy as np
    a, b = max(0, int(start * RATE)), min(len(audio), int(end * RATE))
    if b - a < 480:
        return min(len(audio), max(0, int((start + end) / 2 * RATE)))
    frames = np.abs(audio[a:b])
    energy = np.convolve(frames, np.ones(480) / 480, mode="same")
    calm = np.flatnonzero(energy <= energy.min() + 1e-4)
    return a + int(calm[len(calm) // 2])  # the middle of the quiet stretch, not its edge


def _split(texts: list[str], heard: list[tuple[str, float, float]], audio) -> list | None:
    """A paragraph's audio cut back into its lines, using Whisper's word times; None when a line can't
    be placed (fewer than half its words heard)."""
    import difflib
    want = [(k, w) for k, text in enumerate(texts) for w in _words(text)]
    found = {}
    match = difflib.SequenceMatcher(None, [w for _k, w in want], [w for w, _a, _b in heard], autojunk=False)
    for a, b, n in match.get_matching_blocks():
        found.update({a + j: b + j for j in range(n)})
    placed = []
    for k, text in enumerate(texts):
        mine = [found[n] for n, (line, _w) in enumerate(want) if line == k and n in found]
        if not mine or 2 * len(mine) < len(_words(text)):
            return None
        placed.append((mine[0], mine[-1]))
    cuts = []
    for (_f, last), (first, _l) in pairwise(placed):
        end, start = heard[last][2], heard[first][1]
        cuts.append(_quietest(audio, min(end, start) - 0.05, max(end, start) + 0.05))
    if cuts != sorted(cuts):
        return None
    bounds = [0, *cuts, len(audio)]
    # Each line keeps its words only: the breath the model takes before a line (and any after it) sits
    # outside them and is dropped; a short fade keeps the edges click-free.
    pieces = []
    for (a, b), (first, last) in zip(pairwise(bounds), placed):
        start = max(a, int((heard[first][1] - LEAD) * RATE))
        end = min(b, int((heard[last][2] + TAIL) * RATE))
        pieces.append(_fade(audio[start:end] if end > start else audio[a:b]))
    return pieces


LEAD, TAIL, FADE = 0.06, 0.12, 0.025  # seconds kept before a line's first word and after its last; fade length
GATE_DB = 30  # at a line's edges, 10 ms this far below its loudest is breath or room, not speech


def _fade(samples):
    """Edges below the line's own level (breath, room) off, then a short fade."""
    import numpy as np
    frame = int(0.01 * RATE)
    if len(samples) > 4 * frame:
        rms = np.sqrt((samples[: len(samples) // frame * frame].reshape(-1, frame) ** 2).mean(1)) + 1e-9
        loud = np.flatnonzero(20 * np.log10(rms / rms.max()) > -GATE_DB)
        if loud.size:
            keep = int(0.03 * RATE)
            samples = samples[max(0, loud[0] * frame - keep):min(len(samples), (loud[-1] + 1) * frame + keep)]
    n = min(int(FADE * RATE), len(samples) // 4)
    if n:
        samples = samples.copy()
        ramp = np.linspace(0.0, 1.0, n, dtype="float32")
        samples[:n] *= ramp
        samples[-n:] *= ramp[::-1]
    return samples


def _omnivoice_all(job: dict) -> tuple[list, list]:
    """Every line in the cloned voice, spoken and checked a paragraph at a time; see the module's docstring
    for the memory plan. A misheard paragraph is spoken again whole; one that still can't be cut into its
    lines is finally spoken line by line, so captions always get each line's time."""
    import numpy as np
    import torch
    from omnivoice.models.omnivoice import VoiceClonePrompt
    lines = job["lines"]
    groups = _paragraphs(lines) if job.get("check") else [[i] for i in range(len(lines))]  # no ears: no cutting
    clips: list = [None] * len(lines)
    todo, wrong, attempt = list(range(len(groups))), {}, 0
    stretch = dict.fromkeys(range(len(groups)), FILL)  # per paragraph: time asked ÷ speaking time wanted
    while todo:
        model = _omni(job)
        prompts = {lang: VoiceClonePrompt.load(job[key]) for lang, key in (("en", "voice"), ("hi", "voice_hi"))
                   if job.get(key)}  # a Hindi recording, when given, for Hindi lines (cross-language clones carry an accent)
        spoken = {}
        for g in todo:
            first = lines[groups[g][0]]
            torch.manual_seed(1000 * attempt + g)
            prompt = prompts.get(first["lang"][:2]) or prompts.get("en")
            extra = {"voice_clone_prompt": prompt} if prompt else {"instruct": job.get("instruct") or None}
            said = " ".join(lines[i]["text"] for i in groups[g])
            pace = {"speed": float(first["speed"])}
            if job.get("wpm"):  # a set speaking rate: so many words a minute × the line's speed, whatever the clip's own
                wanted = len(_words(said)) * 60 / (float(job["wpm"]) * float(first["speed"]))
                pace = {"duration": round(max(SHORTEST_SAY, wanted * stretch[g]), 2)}
            out = model.generate(text=said, language=first["lang"][:2], num_step=int(job.get("steps", 32)),
                                 guidance_scale=float(job.get("guidance", 2.0)), **pace, **extra)
            spoken[g] = np.asarray(torch.as_tensor(out[0]).float().reshape(-1))
        del model, prompts
        _collect()
        if not job.get("check"):
            for g, audio in spoken.items():
                clips[groups[g][0]] = audio
            return clips, []
        ear = _whisper(job)
        wrong = {}
        for g in todo:
            texts = [lines[i]["text"] for i in groups[g]]
            heard = [(w, word.start, word.end) for seg in ear.transcribe(
                _to16k(spoken[g]), language=lines[groups[g][0]]["lang"][:2], word_timestamps=True)[0]
                for word in seg.words for w in _words(word.word)]
            said = " ".join(w for w, _a, _b in heard)
            pieces = _split(texts, heard, spoken[g]) if _heard_right(" ".join(texts), said) else None
            if pieces and job.get("wpm"):  # the pace it came out at, speaking time only (pauses cut)
                rate = len(_words(" ".join(texts))) * 60 / max(0.1, sum(len(x) for x in pieces) / RATE)
                target = float(job["wpm"]) * float(lines[groups[g][0]]["speed"])
                if abs(rate / target - 1) > PACE_SLACK and attempt < int(job.get("retries", 2)):
                    stretch[g] *= rate / target  # too fast: ask for more time next round
                    wrong[g] = f"pace {rate:.0f} words/min, wanted {target:.0f}"
                    continue
            if pieces:
                for i, piece in zip(groups[g], pieces):
                    clips[i] = piece
            else:
                wrong[g] = said
                for i, piece in zip(groups[g], _split(texts, heard, spoken[g]) or []):
                    clips[i] = piece  # the best so far, kept in case the retries run out
        del ear
        _collect()
        attempt += 1
        todo = list(wrong) if attempt <= int(job.get("retries", 2)) else []
    uncut = [g for g in wrong if any(clips[i] is None for i in groups[g])]
    if uncut:  # last resort: line by line, unchecked, so every line has its own clip
        single = _omnivoice_all({**job, "check": "", "lines": [lines[i] for g in uncut for i in groups[g]]})[0]
        for i, clip in zip([i for g in uncut for i in groups[g]], single):
            clips[i] = clip
    return clips, [[groups[g][0], groups[g][-1], said] for g, said in sorted(wrong.items())]


REF_GAP = 0.2  # seconds: longer pauses (and the breaths in them) in your recording are shortened to this


def _tighten(audio, words) -> object:
    """Your clip with every pause between words cut to REF_GAP: the clone copies the recording's pauses
    and breaths, so they are taken out of the clip it learns from."""
    import numpy as np
    keep, at = [], 0
    for w, nxt in pairwise(words):
        if nxt.start - w.end > REF_GAP:
            stop = int((w.end + REF_GAP / 2) * RATE)
            keep.append(_fade(audio[at:stop]) if stop > at else audio[at:at])
            at = int((nxt.start - REF_GAP / 2) * RATE)
    keep.append(audio[at:])
    return np.concatenate(keep)


def clone(job: dict) -> dict:
    """The voice file, made once from your recording: Whisper times its words (and writes them when "text"
    is empty, cutting after the last sentence or clause inside the limit), long pauses and breaths are
    taken out, and OmniVoice encodes the rest."""
    import numpy as np
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", job["audio"], "-f", "s16le", "-ac", "1", "-ar", str(RATE),
                          "pipe:1"], capture_output=True, check=True, timeout=EDGE_TIMEOUT).stdout
    audio = np.frombuffer(pcm, dtype="<i2").astype("float32") / 32767
    longest, text = float(job.get("seconds", 10)), job.get("text", "").strip()
    ear = _whisper({**job, "check": job.get("check") or "small"})
    words = [w for seg in ear.transcribe(_to16k(audio), language=job.get("lang") or None, word_timestamps=True)[0]
             for w in seg.words]
    del ear
    _collect()
    before = len(audio) / RATE
    if not text:
        inside = [w for w in words if w.end <= longest] or words[:1]
        stops = [n for n, w in enumerate(inside) if w.word.strip()[-1:] in ".!?,;:"]
        kept = inside[:stops[-1] + 1] if stops and stops[-1] >= len(inside) // 2 else inside
        end = min(kept[-1].end + 0.25, len(audio) / RATE, (words[len(kept)].start if len(words) > len(kept) else 1e9))
        text, audio, words = "".join(w.word for w in kept).strip(), audio[:int(end * RATE)], kept
    if words:
        audio = _tighten(audio, words)
    peak = float(np.abs(audio).max()) or 1.0
    audio = audio * min(4.0, 0.7 / peak)  # a quiet recording brought up to a usual level (never clipped)
    import torch
    model = _omni(job)
    prompt = model.create_voice_clone_prompt(ref_audio=(torch.from_numpy(audio).unsqueeze(0), RATE), ref_text=text)
    prompt.save(job["out"])
    wpm = round(len(_words(text)) / (len(audio) / RATE) * 60)
    return {"seconds": round(len(audio) / RATE, 2), "text": text, "removed": round(before - len(audio) / RATE, 2),
            "wpm": wpm}


ENGINES = {"kokoro": _kokoro, "edge": _edge}
QUIET = 0.01  # below this (about -40 dB) a sample counts as silence
KEEP = 0.03  # seconds of the line's own lead-in and tail kept, so consonants are not clipped


def _trim(samples):
    """Drop the silence an engine leaves around a line (Kokoro adds ~0.2 s), so studio.pause alone sets
    the gap between sentences."""
    import numpy as np
    loud = np.flatnonzero(np.abs(samples) > QUIET)
    if not loud.size:
        return samples
    keep = int(RATE * KEEP)
    return samples[max(0, loud[0] - keep):loud[-1] + 1 + keep]


def main() -> int:
    import numpy as np

    job = json.load(sys.stdin)
    if job.get("engine") in ("clone", "convert"):
        print(json.dumps((clone if job["engine"] == "clone" else convert)(job), ensure_ascii=False))
        return 0
    misheard: list = []
    if job.get("engine") == "omnivoice":
        clips, misheard = _omnivoice_all(job)
    else:
        make, state = ENGINES[job.get("engine", "kokoro")], {}
        clips = [make(job, line, state) for line in job["lines"]]
    parts, spans, at = [], [], 0.0
    for line, raw in zip(job["lines"], clips):
        samples = _trim(raw)
        spans.append([round(at, 3), round(at + len(samples) / RATE, 3)])
        pause = np.zeros(int(RATE * float(line.get("pause", 0))), dtype="float32")
        parts += [samples, pause]
        at += (len(samples) + len(pause)) / RATE
    audio = np.concatenate(parts) if parts else np.zeros(0, dtype="float32")
    with wave.open(job["out"], "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    print(json.dumps({"seconds": round(len(audio) / RATE, 3), "sample_rate": RATE, "lines": spans,
                      "misheard": misheard}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
