# Studio (`/studio`): video, audio, b-roll and images

Made on your server; posting them is another workflow's job. Built so far: **voice** (Kokoro, Edge TTS)
**video from a storyboard** (Remotion, 17 scene types, word captions) and **notes → storyboard** with 3
hooks (Gemini). Next: music/SFX, stock b-roll, thumbnails, edits of your own raw clips. Style reference:
`PLAYBOOK.md`. Plan and decisions: the checkpoint notes and the conversation log.

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
  with `studio.pause` seconds after it (the silence each engine leaves around a line is trimmed first, so
  the pause alone sets the gap). Defaults `speed 1.0`, `pause 0.15`: 196 words a minute measured
  (`1.15`/`0.12` gives 217, Fireship's pace; your pick was ~198). Each line's start and end come back, for captions and cuts.
  (Whisper on a mixed clip dropped the Hindi lines, so captions for generated voiceovers come from
  the known script and these times, not from a fresh transcript.)
- **Kokoro model:** fp16 (`kokoro-v1.0.fp16.onnx`, 169 MB) by default, at your request. It was faster
  than int8 here (a CPU with AVX-512 FP16) for ~110 MB more memory; on a CPU without FP16 support
  onnxruntime converts as it goes and it may be slower, so measure on the host. int8
  (`kokoro-v1.0.int8.onnx`, 88 MB; `KOKORO_INT8=1 install.sh`) is the low-memory fallback; full
  precision (`kokoro-v1.0.onnx`, 310 MB; `KOKORO_FP32=1 install.sh`) sounded no different from int8. **Voice:** `am_puck` (your pick), then `am_fenrir`.

### Measured (2026-11-24, x86 container, 2 threads)

| Engine | Speed | Peak memory | Notes |
|---|---|---|---|
| Kokoro-82M int8 | 38 s of speech in 19 s | 586 MB | English and Devanagari read back word for word by Whisper |
| Kokoro-82M fp16 vs int8, same 10 s text, 3 runs (am_puck) | 2.6–3.4× vs 2.0–2.1× real time | 522 vs 410 MB | load 0.9 s vs 0.5 s; files 169 vs 88 MB |
| Kokoro-82M int8 vs fp32, same text, separate runs | 16.8 s in 7.6 s vs 7.0 s | 889 vs 1,139 MB | load 0.7 s vs 2.7 s; files 88 vs 310 MB |
| Chatterbox 0.5B (Resemble AI, MIT, cloning) | 9.6 s in 78 s (0.12× real time) | 6.8 GB | words all correct; **too heavy for the 4 GB host**: needs a GPU |
| Edge TTS | not testable here | — | this container's proxy blocks WebSockets; test on the host |

Bigger open voices (Chatterbox, Orpheus, Indic Parler-TTS, VibeVoice) need a GPU to be usable; see the
options in the conversation log before adding one. ElevenLabs can be added later as a paid engine.

## Video: storyboard → vertical short (Remotion)

```
python -m orchestrator.studio video storyboard.json --out short.mp4
```

A storyboard is a list of scenes; each has `say` (the narration) and what is on screen. The format is
at the top of `storyboard.py`. Types: **title** (punch line landing word by word), **bullets** (a list,
each item appearing when its sentence starts), **code** (an editor typing itself out), **stat** (a big
number counting up), **image** (a full-screen image or clip with a slow push and a caption card),
**compare** (two cards with VS), **terminal** (commands type, output prints), **chart** (bars grow or a
line draws; the largest lit), **diagram** (boxes and arrows, top to bottom), **quote**, **timeline**,
**clipping** (a newspaper headline rebuilt as a card, a highlighter sweeping over the key words), **post**
(a generic social post card), **meme** (your CC0 image, top/bottom text), **beforeafter** (a wipe from
before to after), **logo** (the subject named big), **map** (the camera flies from the world to the
countries, they fill in, a route draws itself, names pop; Natural Earth data, no API key). Any scene can
add `"emoji": "🔥"`, which pops on its first emphasised word. Every scene punches in and keeps a slow
push; captions are 2–3 words at a time, the word being said in the accent; a progress bar runs along
the top. Parts of a scene (list items, bars, boxes, events, "after") arrive on the sentence that says them.

- **Page profiles** (`profile.py`, one YAML per page): theme (colours, fonts, background), motion
  (spring feel, default entrance and exit, punch-in strength, drift, optional 12 fps handmade look),
  captions, voice, writing (format, hooks, humour, tone, words to avoid, example scripts) and allowed
  elements (music, sound effects, b-roll, memes: `off`, `auto` = only where it helps, or `always`).
  Built in: `default` (dev dark), `bold` (black/yellow, Anton, whip cuts), `paper` (warm paper, ink
  colours, soft). Yours go in `$HERMES_HOME/studio/profiles/<name>.yaml` and state only what differs
  (`extends: bold` + two colours is a whole profile). Pick one with `--profile`, the storyboard's
  `"profile"`, or `studio.profile`.
- **Motion is building blocks, not fixed clips** (`remotion/src/motion.tsx`): 3 spring feels × 6 entrances
  × 5 exits, a camera punch-in on `*emphasised*` words, slow drift, and optional 12 fps stepping
  (`motion.step: 12`; off everywhere: next to 30 fps captions it reads as dropped frames). The profile sets
  defaults; a storyboard scene can override `enter`/`exit`; scenes compose them for their parts.
- **Timing comes from the voice.** All narration goes to the voice in one job; each scene starts when its
  first sentence starts. Captions are the script as written, its time split over the words by length
  (not Whisper, which drops Hindi in mixed clips).
- **Quality** (all under `studio:` in brief.yaml): 1080×1920 at 30 fps, H.264 `crf 17` with x264 `slow`,
  JPEG frames at 95, yuv420p, AAC 320k. One frame at a time (`video_concurrency: 1`) for the 4 GB host.
- **Each job keeps its folder** in `$HERMES_HOME/studio/video/<time>/`: voice.wav, props.json, assets,
  render.log. To preview templates live: `cd orchestrator/studio/remotion && npx remotion studio`.
- **Versions:** Remotion 4.0.542, React 19.2.9 (exact pins in `remotion/package.json`). Remotion is free
  for individuals and companies of up to 3 people; above that it needs a company licence.

### Measured (2026-11-24, x86 container, 4 cores, defaults above)

| Job | Voice | Render | Peak memory | File |
|---|---|---|---|---|
| 6 scenes, 29.8 s (`crf 17`, `slow`) | 13 s (Kokoro fp16) | 138 s (4.6 s per s of video) | ~1.9 GB over idle | 11.4 MB, 2.7 Mb/s video |
| 10 newer scenes, 38.5 s | 19 s | 172 s (4.5 s per s) | — | — |
| 3 scenes with 2 maps, 10.5 s | 5 s | 88 s (8.4 s per s: maps draw 241 country outlines a frame) | — | — |
| 3 scenes, 2 maps, 8.5 s, before / after coarse outlines + clipping | 4 s | 53 s → 36 s (6.2 → 4.2 s per s) | ~0.8 GB | — |

On the 2-core host expect roughly twice the render time; renders are meant for the overnight queue.

## Writing: notes → storyboard with 3 hooks

```
python -m orchestrator.studio write "Bun: a JS runtime in Zig, 25x faster installs ..." --out bun.json [--notes notes.txt] [--profile bold] [--seconds 45]
python -m orchestrator.studio video bun.json --out bun.mp4          # or bun.hook2.json / bun.hook3.json
```

Gemini (`studio.script_models`, tried in order) writes the narration and picks the scenes, prompted
from the page profile's `writing:` (format, hooks, humour, tone, words to avoid, example scripts,
length) and `PLAYBOOK.md` (the ten rules, the format's beats, the hook bank). It writes **3 hooks from 3
different families**; `bun.json` opens with hook 1, `bun.hook2.json`/`bun.hook3.json` with the others, and
`bun.txt` is the script to read over. The answer is checked in code; problems go back to the same model
once as a list ("fix these"), then the next model starts fresh:

- **Evidence comes only from your notes:** a stat's or chart's numbers, a quote, a headline, a post's
  text must appear in them, so give it the facts you want on screen.
- Length within 20% of the target (196 wpm × voice speed); sentences ≤ 24 words; a picture says at most
  ~6 s unless it has parts, one sentence per part; the hook's first sentence ≤ 12 words, no greeting.
- None of the profile's `avoid` phrases (plus "in this video", "welcome back" …); only scene types the
  profile allows; no image/meme scenes until b-roll exists; maps name countries only.

The models are the free flash-lite ones by default; a stronger model writes better scripts (set
`script_models` in brief.yaml). `--claude` (or `/studio write claude …` in Telegram) writes with
Claude instead (`studio.claude_model`, default `claude-opus-5-5` at `claude_effort: medium`; needs
`ANTHROPIC_API_KEY`; paid, roughly $0.10–0.25 a storyboard; a declined request is retried on a
fallback model by the API). Same prompt, same checks. **Neither has been run against the real API yet.**

In Telegram: `/studio write <notes>` answers with the hooks and the script and saves the storyboards in
`$HERMES_HOME/studio/write/<time>/`; rendering from chat comes with the overnight queue.

**Wishes: the library is a menu, never a checklist.** The writer picks only scenes that fit; nothing has
to be used. When a scene would be clearly better with a visual we cannot make yet, it still picks the
best available scene and adds a wish ("a 3D bun bouncing out of an oven"). Wishes are logged in
`$HERMES_HOME/studio/wishes.jsonl`; `python -m orchestrator.studio wishes` ranks them, most wanted first,
which is the backlog for new scenes and assets.

## Voice directions

Written in `say`, obeyed by the voice, never shown in captions (`direction.py`):

| Write | Effect |
|---|---|
| `And the winner is [beat] India.` | a 0.4 s pause there (captions stay silent through it too) |
| `[pause 1.2] Three years later…` | an exact pause, up to 3 s |
| `[slow] This is the part that matters.` | the rest of the sentence at 0.9× the page's speed (`[fast]`: 1.1×) |

`...`, `—`, `?` and `!` already shape the reading. Neither engine can stress a single word (`*emphasis*`
is visual), so wording carries the delivery. Measured with Kokoro: `[beat]` left 0.46 s of silence,
`[pause 1.2]` 1.41 s with the usual 0.15 s gap. In a Hinglish line typed in Latin script, directions
inside the sentence are dropped (the Devanagari rewrite returns whole sentences); between sentences they work.

## Covers

```
python -m orchestrator.studio cover bun.json --out cover.png [--scene 2] [--words "npm is too slow"] [--profile bold]
```

One scene of the storyboard, fully arrived, under 2–5 huge words in the page's caption font, the last
word in the accent; any emoji on the scene included. Rendered with Remotion's still renderer from the same
scene code as the video (~6 s, no voice needed), so it always matches. PLAYBOOK § 9: the words should add
to the title, not repeat it.

## Maps

Countries only (Natural Earth; narration may name cities freely, the map lights their countries). The
camera frames each country on its main landmass (the USA without Alaska and Hawaii, France without French
Guiana); labels and route ends sit on its largest piece. Zoomed out, the map draws the coarse 110 m
outlines and skips countries off screen: the 2-map test went from 53 s to 36 s of render (8.5 s video).

## Setup

1. `orchestrator/studio/install.sh` (once): a separate environment `$HERMES_HOME/venvs/studio`
   (kokoro-onnx 0.6.1, onnxruntime, edge-tts 7.3.1; no PyTorch; ~180 MB) and Kokoro's model files in
   `$HERMES_HOME/studio/models` (~200 MB, SHA-256 checked). Hermes' own environment is not touched.
2. `studio:` in `brief.yaml` (see `brief.example.yaml`): engine, voices, speed, pause, threads.
3. `ffmpeg` on the host: Edge's audio is decoded with it, and clips go to Telegram as voice messages.
4. Videos: Node 18+ on the host and an emoji font (`sudo apt install fonts-noto-color-emoji`), then
   `install.sh` again (it installs `remotion/` and Chrome's headless
   shell, ~100 MB). Chrome also needs the usual shared libraries (`npx remotion browser ensure` names any missing).

## Tested

- **Video** (`tests/test_video.py`): bad storyboards refused before anything runs; scenes start with
  their first sentence; captions show the script as written (Hinglish stays Latin) in order; list items
  get their sentences' times; assets travel with the job; the configured quality reaches the render;
  and a **live render** (real Kokoro + Remotion, opt-in like the voice test) checked as 1080×1920, 30 fps,
  with audio.

- **Fakes** (`tests/test_studio.py`): Hinglish told apart from English and Devanagari; each sentence
  routed to its engine's voice (Kokoro or Edge, per message or by default); Gemini's Devanagari rewrite used, and a rewrite with missing lines or Latin
  script refused before anything is spoken; English needs no model; the clip goes out as a Telegram
  voice message; a missing Kokoro says how to install it.
- **Live** (opt-in `RealKokoro` test with `STUDIO_KOKORO_PYTHON`/`STUDIO_KOKORO_MODELS`, and the CLI): real
  Kokoro, English + Hindi in one 24 kHz file with line times. **Not run yet:** Edge TTS (blocked here),
  the installer on the host, the Gemini rewrite against the real API, Telegram for real.
