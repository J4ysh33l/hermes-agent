# Studio (`/studio`): video, audio, b-roll and images

Made on your server; posting them is another workflow's job. Built so far: **voice** (Kokoro).
Next: automated videos (faceless, Fireship-style), b-roll from images, cards and motion graphics, and
edits of your own raw clips. Plan and decisions: the checkpoint notes and the conversation log.

## Voice: Kokoro

```
/studio voice Here's the thing nobody tells you about AI agents. They are loops.
/studio voices
python -m orchestrator.studio voice "text" --out speech.wav     # on the host, prints each line's time
```

- **Free and local:** Kokoro-82M (int8 ONNX, Apache-2.0) on the CPU; no API, no daily limit, no key.
- **Measured here (2026-11-24, x86 container limited to 2 threads):** 38 s of speech in 19 s
  including model load (about 2× real time); 586 MB peak memory. The t4g host (ARM) is likely somewhat
  slower; measure there before sizing batch jobs.
- **Checked by ear-proxy:** Whisper `small` read the English output back word for word, and Hindi
  written in Devanagari back word for word (as Hinglish in Latin script, thanks to the romanised hint).
- **Languages:** English (US and UK voices) and Hindi. **Hinglish typed in Latin script garbles**
  (Whisper heard nonsense), so `voice` asks Gemini to rewrite such sentences in Devanagari first (one
  call; English words keep their sound: product → प्रोडक्ट). The rewrite must return the same number
  of lines, all in Devanagari, or nothing is spoken.
- **Each sentence goes to its script's voice** (`studio.voice_en` for Latin, `studio.voice_hi` for
  Devanagari), with `studio.pause` seconds after it. The worker returns each line's start and end, for
  captions and cuts. (Whisper on a mixed clip dropped the Hindi lines, so captions for generated
  voiceovers come from the known script and these times, not from a fresh transcript.)
- **No cloning:** Kokoro has fixed voices. ElevenLabs can be added later as a second voice engine.

## Setup

1. `orchestrator/studio/install_kokoro.sh` (once): a separate environment `$HERMES_HOME/venvs/kokoro`
   (kokoro-onnx 0.6.1, onnxruntime, no PyTorch; ~170 MB) and the model files in
   `$HERMES_HOME/studio/models` (~120 MB, SHA-256 checked). Hermes' own environment is not touched.
2. `studio:` in `brief.yaml` (see `brief.example.yaml`): voices, speed, pause, threads.
3. `ffmpeg` on the host, to send clips as Telegram voice messages (else they go as WAV files).

## Tested

- **Fakes** (`tests/test_studio.py`): Hinglish told apart from English and Devanagari; each sentence
  routed to its voice; Gemini's Devanagari rewrite used, and a rewrite with missing lines or Latin
  script refused before anything is spoken; English needs no model; the clip goes out as a Telegram
  voice message; a missing Kokoro says how to install it.
- **Live** (opt-in `RealKokoro` test with `STUDIO_KOKORO_PYTHON`/`STUDIO_KOKORO_MODELS`, and the CLI): real
  Kokoro, English + Hindi in one 24 kHz file with line times. **Not run yet:** the installer on the host,
  the Gemini rewrite against the real API, Telegram for real.
