# Studio (`/studio`): video, audio, b-roll and images

Made on your server; posting them is another workflow's job. Built so far: **voice** (Kokoro, Edge TTS).
Next: automated videos (faceless, Fireship-style), b-roll from images, cards and motion graphics, and
edits of your own raw clips. Plan and decisions: the checkpoint notes and the conversation log.

## Voice: Kokoro (default) or Edge TTS

```
/studio voice Here's the thing nobody tells you about AI agents. They are loops.
/studio voice edge Here's the thing nobody tells you about AI agents.
/studio voices · /studio voices edge
python -m orchestrator.studio voice "text" --out speech.wav     # on the host, prints each line's time
```

| | Kokoro (`studio.engine: kokoro`) | Edge TTS (`edge`) |
|---|---|---|
| Where | the server's CPU, offline | Microsoft's read-aloud service, online |
| Cost, limits | free, none | free, none published |
| Quality | good English; Hindi fair; no cloning | natural Indian English and Hindi voices (Prabhat, Neerja, Madhur, Swara) |
| Risk | none: the model never changes | **unofficial**: Microsoft can change or block it; commercial use unclear |
| Speed (measured) | ~2.2× real time on 2 threads, ~600 MB | network-bound; no CPU |

- **Both read English, and Hindi written in Devanagari.** Hinglish typed in Latin script garbles in
  Kokoro (tested: Whisper heard nonsense), so `voice` asks Gemini to rewrite such sentences in
  Devanagari first (one call; English words keep their sound: product → प्रोडक्ट). The rewrite must
  return the same number of lines, all in Devanagari, or nothing is spoken.
- **Each sentence goes to its script's voice** (`voice_en`/`voice_hi`, or `edge_voice_en`/`edge_voice_hi`),
  with `studio.pause` seconds after it. Each line's start and end come back, for captions and cuts.
  (Whisper on a mixed clip dropped the Hindi lines, so captions for generated voiceovers come from
  the known script and these times, not from a fresh transcript.)
- **Kokoro model:** int8 (`kokoro-v1.0.int8.onnx`, 88 MB) by default. Full precision (`kokoro-v1.0.onnx`,
  310 MB; `KOKORO_FP32=1 install.sh`) sounded no different in your listening test and needs 250 MB more
  memory, which video rendering needs more. **Voice:** `am_puck` (your pick), then `am_fenrir`.

### Measured (2026-11-24, x86 container, 2 threads)

| Engine | Speed | Peak memory | Notes |
|---|---|---|---|
| Kokoro-82M int8 | 38 s of speech in 19 s | 586 MB | English and Devanagari read back word for word by Whisper |
| Kokoro-82M int8 vs fp32, same text, separate runs | 16.8 s in 7.6 s vs 7.0 s | 889 vs 1,139 MB | load 0.7 s vs 2.7 s; files 88 vs 310 MB |
| Chatterbox 0.5B (Resemble AI, MIT, cloning) | 9.6 s in 78 s (0.12× real time) | 6.8 GB | words all correct; **too heavy for the 4 GB host**: needs a GPU |
| Edge TTS | not testable here | — | this container's proxy blocks WebSockets; test on the host |

Bigger open voices (Chatterbox, Orpheus, Indic Parler-TTS, VibeVoice) need a GPU to be usable; see the
options in the conversation log before adding one. ElevenLabs can be added later as a paid engine.

## Setup

1. `orchestrator/studio/install.sh` (once): a separate environment `$HERMES_HOME/venvs/studio`
   (kokoro-onnx 0.6.1, onnxruntime, edge-tts 7.3.1; no PyTorch; ~180 MB) and Kokoro's model files in
   `$HERMES_HOME/studio/models` (~120 MB, SHA-256 checked). Hermes' own environment is not touched.
2. `studio:` in `brief.yaml` (see `brief.example.yaml`): engine, voices, speed, pause, threads.
3. `ffmpeg` on the host: Edge's audio is decoded with it, and clips go to Telegram as voice messages.

## Tested

- **Fakes** (`tests/test_studio.py`): Hinglish told apart from English and Devanagari; each sentence
  routed to its engine's voice (Kokoro or Edge, per message or by default); Gemini's Devanagari rewrite used, and a rewrite with missing lines or Latin
  script refused before anything is spoken; English needs no model; the clip goes out as a Telegram
  voice message; a missing Kokoro says how to install it.
- **Live** (opt-in `RealKokoro` test with `STUDIO_KOKORO_PYTHON`/`STUDIO_KOKORO_MODELS`, and the CLI): real
  Kokoro, English + Hindi in one 24 kHz file with line times. **Not run yet:** Edge TTS (blocked here),
  the installer on the host, the Gemini rewrite against the real API, Telegram for real.
