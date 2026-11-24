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
    make = ENGINES[job.get("engine", "kokoro")]
    state, parts, spans, at = {}, [], [], 0.0
    for line in job["lines"]:
        samples = _trim(make(job, line, state))
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
    print(json.dumps({"seconds": round(len(audio) / RATE, 3), "sample_rate": RATE, "lines": spans}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
