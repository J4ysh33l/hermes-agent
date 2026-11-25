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
  Memory: OmniVoice and Whisper are never loaded together. All lines are spoken, OmniVoice is freed,
  Whisper listens to every line, is freed, and only the lines it misheard are spoken again (new seed).
  Peak = the larger of the two, not their sum. The output gains "misheard": [[line, what Whisper heard], ...] still wrong at the end.

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


def _omnivoice_all(job: dict) -> tuple[list, dict[int, str]]:
    """Every line in the cloned voice, checked by Whisper; see the module's docstring for the memory plan."""
    import numpy as np
    import torch
    from omnivoice.models.omnivoice import VoiceClonePrompt
    lines, clips = job["lines"], [None] * len(job["lines"])
    todo, wrong, attempt = list(range(len(lines))), {}, 0
    while todo:
        model = _omni(job)
        prompts = {lang: VoiceClonePrompt.load(job[key]) for lang, key in (("en", "voice"), ("hi", "voice_hi"))
                   if job.get(key)}  # a Hindi recording, when given, for Hindi lines (cross-language clones carry an accent)
        for i in todo:
            torch.manual_seed(1000 * attempt + i)
            prompt = prompts.get(lines[i]["lang"][:2]) or prompts.get("en")
            extra = {"voice_clone_prompt": prompt} if prompt else {"instruct": job.get("instruct") or None}
            out = model.generate(text=lines[i]["text"], language=lines[i]["lang"][:2], speed=float(lines[i]["speed"]),
                                 num_step=int(job.get("steps", 32)), **extra)
            clips[i] = np.asarray(torch.as_tensor(out[0]).float().reshape(-1))
        del model, prompts
        _collect()
        if not job.get("check"):
            return clips, {}
        ear = _whisper(job)
        wrong = {}
        for i in todo:
            said = " ".join(s.text for s in ear.transcribe(_to16k(clips[i]), language=lines[i]["lang"][:2])[0])
            if not _heard_right(lines[i]["text"], said):
                wrong[i] = said.strip()
        del ear
        _collect()
        attempt += 1
        todo = list(wrong) if attempt <= int(job.get("retries", 2)) else []
    return clips, wrong


def clone(job: dict) -> dict:
    """The voice file, made once from your recording."""
    import numpy as np
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", job["audio"], "-f", "s16le", "-ac", "1", "-ar", str(RATE),
                          "pipe:1"], capture_output=True, check=True, timeout=EDGE_TIMEOUT).stdout
    audio = np.frombuffer(pcm, dtype="<i2").astype("float32") / 32767
    longest, text = float(job.get("seconds", 10)), job.get("text", "").strip()
    if not text:  # Whisper writes the transcript; cut after the last sentence or clause inside the limit
        ear = _whisper({**job, "check": job.get("check") or "small"})
        words = [w for seg in ear.transcribe(_to16k(audio), language=job.get("lang") or None, word_timestamps=True)[0]
                 for w in seg.words]
        del ear
        _collect()
        inside = [w for w in words if w.end <= longest] or words[:1]
        stops = [n for n, w in enumerate(inside) if w.word.strip()[-1:] in ".!?,;:"]
        kept = inside[:stops[-1] + 1] if stops and stops[-1] >= len(inside) // 2 else inside
        end = min(kept[-1].end + 0.25, len(audio) / RATE, (words[len(kept)].start if len(words) > len(kept) else 1e9))
        text, audio = "".join(w.word for w in kept).strip(), audio[:int(end * RATE)]
    import torch
    model = _omni(job)
    prompt = model.create_voice_clone_prompt(ref_audio=(torch.from_numpy(audio).unsqueeze(0), RATE), ref_text=text)
    prompt.save(job["out"])
    return {"seconds": round(len(audio) / RATE, 2), "text": text}


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
    misheard: dict[int, str] = {}
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
                      "misheard": [[i, heard] for i, heard in sorted(misheard.items())]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
