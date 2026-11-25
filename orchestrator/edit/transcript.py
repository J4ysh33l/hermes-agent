"""Your words with their times: faster-whisper in the studio venv (asr_worker.py) → transcript.json.
Grouping into sentences is in words.py."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from orchestrator.studio.settings import Settings as StudioSettings
from orchestrator.studio.voice import _paths

from .settings import Settings
from .words import Sentence, Word, has_devanagari, load, numbered, sentences

TIMEOUT = 7200
WORKER = Path(__file__).with_name("asr_worker.py")


class TranscriptError(Exception):
    """Shown as it is; the job stops."""


def transcribe(edit: Settings, studio: StudioSettings, home: Path, audio16: Path, out: Path) -> list[Word]:
    python, _models = _paths(studio, home)
    if not python.is_file():
        raise TranscriptError(f"The studio is not installed ({python} missing): run orchestrator/studio/install.sh --omnivoice")
    job = {"audio": str(audio16), "model": edit.asr_model, "language": edit.asr_language, "prompt": edit.asr_prompt,
           "threads": edit.threads}
    try:
        done = subprocess.run([str(python), "-I", str(WORKER)], input=json.dumps(job), capture_output=True, text=True,
                              timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise TranscriptError(f"transcription took over {TIMEOUT // 60} minutes") from None
    if done.returncode != 0:
        tail = (done.stderr or "").strip().splitlines()[-1:] or ["no error text"]
        raise TranscriptError(f"transcription failed: {tail[0][:300]}")
    result = json.loads(done.stdout.strip().splitlines()[-1])
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return load(out)
