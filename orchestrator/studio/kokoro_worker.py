"""Runs inside Kokoro's own virtual environment ($HERMES_HOME/venvs/kokoro), never in Hermes'.

Reads one JSON job on stdin and writes one 24 kHz mono 16-bit WAV:
  {"model": "...onnx", "voices": "...bin", "threads": 2, "out": "x.wav",
   "lines": [{"text": "...", "voice": "am_michael", "lang": "en-us", "speed": 1.05, "pause": 0.25}, ...]}
Prints one JSON line: {"seconds": 12.3, "sample_rate": 24000, "lines": [[start, end], ...]} (each
line's place in the file, for captions and cuts). Imports nothing from this repo: it only needs
kokoro-onnx, which only that environment has.
"""

import json
import sys
import wave


def main() -> int:
    import numpy as np
    import onnxruntime as ort
    from kokoro_onnx import Kokoro

    job = json.load(sys.stdin)
    options = ort.SessionOptions()
    options.intra_op_num_threads = int(job.get("threads", 2))
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(job["model"], options, providers=["CPUExecutionProvider"])
    kokoro = Kokoro.from_session(session, job["voices"])
    rate, parts, spans, at = 24000, [], [], 0.0
    for line in job["lines"]:
        samples, rate = kokoro.create(line["text"], voice=line["voice"], speed=float(line["speed"]), lang=line["lang"])
        spans.append([round(at, 3), round(at + len(samples) / rate, 3)])
        pause = np.zeros(int(rate * float(line.get("pause", 0))), dtype=samples.dtype)
        parts += [samples, pause]
        at += (len(samples) + len(pause)) / rate
    audio = np.concatenate(parts) if parts else np.zeros(0, dtype="float32")
    with wave.open(job["out"], "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    print(json.dumps({"seconds": round(len(audio) / rate, 3), "sample_rate": rate, "lines": spans}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
