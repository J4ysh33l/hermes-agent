"""Runs in the studio venv (faster-whisper): one job as JSON on stdin, the words as JSON on stdout.

    {"audio": "voice16.wav", "model": "large-v3-turbo", "language": "en", "prompt": "...", "threads": 2}
    → {"language": "en", "words": [{"w": "Okay,", "s": 1.2, "e": 1.8, "p": 0.91}, ...]}

Standard library + faster-whisper only; started with ``python -I`` so nothing from the job folder is imported.
"""

import json
import sys
import wave


def main() -> int:
    job = json.loads(sys.stdin.read())
    import numpy as np
    from faster_whisper import WhisperModel

    with wave.open(job["audio"]) as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1:
            raise SystemExit("audio must be 16 kHz mono")
        audio = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype("float32") / 32767
    model = WhisperModel(job.get("model") or "large-v3-turbo", device="cpu", compute_type="int8",
                         cpu_threads=int(job.get("threads", 2)))
    segments, info = model.transcribe(
        audio, language=job.get("language") or None, initial_prompt=job.get("prompt") or None,
        word_timestamps=True, beam_size=5, condition_on_previous_text=False,
        suppress_tokens=[],  # keeps "umm", "uh" that Whisper otherwise drops
        vad_filter=False)
    words = []
    for seg in segments:
        for x in seg.words or []:
            text = x.word.strip()
            if text:
                words.append({"w": text, "s": round(x.start, 3), "e": round(x.end, 3), "p": round(x.probability, 3)})
    print(json.dumps({"language": info.language, "words": words}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
