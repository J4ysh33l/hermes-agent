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
  Built in: `default` (dev dark), `bold` (black/yellow, Anton, whip transitions), `paper` (warm paper, ink
  colours, soft). Yours go in `$HERMES_HOME/studio/profiles/<name>.yaml` and state only what differs
  (`extends: bold` + two colours is a whole profile). Pick one with `--profile`, the storyboard's
  `"profile"`, or `studio.profile`.
- **Motion is building blocks, not fixed clips** (`remotion/src/motion.tsx`): 3 spring feels × 6 entrances
  × 5 exits, a camera punch-in on `*emphasised*` words, slow drift, and optional 12 fps stepping
  (`motion.step: 12`; off everywhere: next to 30 fps captions it reads as dropped frames). The profile sets
  defaults; a storyboard scene can override `enter`/`exit`; scenes compose them for their parts.
- **Transitions overlap** (`motion.transition`, `transition_frames`): the next scene comes in while the last one
  is still moving: `push`, `whip` (with motion blur), `zoom`, `fade`, `flash` (white), `burn` (warm light
  sweeping across, film burn), or `none` (exit, then entrance) and `cut`. The scene starts on its first word
  as before; the outgoing one is drawn a few frames longer underneath. Default `push`, bold `whip`, paper
  `fade`; a scene can pick its own (`"transition": "burn"` for a jump in time).
- **Captions in phrases:** a page breaks at sentence ends, pauses and commas; inside a phrase the split is
  the one with no lone words, no page ending on "the/of/to", nothing far over `captions.words`. A word too
  wide for the screen shrinks its page (an estimate per font that errs wide); a stat's value is sized to fit
  one line.
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

Claude (`studio.writer: claude`, the default; `studio.claude_model`) writes the narration and directs the
scenes; `--gemini` uses Gemini's free models (`studio.script_models`) instead. Prompted
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

## The library is a fast track, not a menu

Quality beats speed. The 17 library scenes are ready-made, tested and quick to render, so the writer uses
one when it is genuinely the best picture for that moment. For anything else it writes a **custom scene**:
a `brief` an animator could work from, the data in `props`, and a `fallback` library scene. Claude then
writes that one scene as a Remotion component (`custom.py`), and it must pass, in order:

1. a static check: only the allowed imports, nothing that reaches outside the page or changes between
   renders (network, storage, timers, `Math.random`, dates, CSS animations);
2. TypeScript against the real scene types;
3. a probe render: three frames of the scene alone, drawn by the real renderer;
4. a review (`studio.custom_review: true`): Claude looks at those frames beside the brief and fixes
   what is off (a fix that breaks the checks is ignored).

A failure in 1–3 goes back to Claude with the error, twice at most; a scene that still fails, or that
cannot be built (no `ANTHROPIC_API_KEY`), is drawn as its fallback and the reason is printed. The video
is never lost. Passed components are cached in `$HERMES_HOME/studio/scenes/` and kept with each job
(`custom/`). A component can also be written by hand: `"component": "race.tsx"` next to the storyboard
(`tests/data/race.tsx` is one).

The only limits the writer is given are the pipeline's real ones (`custom.LIMITS`): Remotion draws
React/SVG/CSS in headless Chrome, frame by frame; no photoreal people or footage without a file; no true
3D; the fonts installed; the 2-core host's render time; what the voices can do; where captions and
platform buttons sit. **Wishes** are only for what is beyond even that (real footage, a specific sound):
logged in `$HERMES_HOME/studio/wishes.jsonl` and ranked by `python -m orchestrator.studio wishes`.

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

## Sound: effects on the cuts, music under the voice

Profile `elements.sfx` / `elements.music`: `off`, `auto` or `always`.

- **Effects are made, not downloaded** (`sound.py`, ffmpeg `aevalsrc` formulas, so no licence to track): a
  whoosh on push/whip/zoom transitions, a hit on a flash, a riser into a burn, a pop when an emoji lands,
  and with `always` a tick as each list item appears. Each peaks where the eye expects it (mid-overlap).
  Made once into `$HERMES_HOME/studio/sfx/`.
- **Music is yours, with its licence:** put tracks in `$HERMES_HOME/studio/music/` and list them in
  `music.yaml` (`file`, `licence`, `credit`, optional `profiles: [paper]`). A file not listed, or listed
  without a licence, is never used. The same video always gets the same track; it is looped or cut to
  the video, faded, and ducked under the voice (sidechain: it dips under words and comes back in pauses,
  measured >6 dB in the test). The credit goes into the job's notes, so it is in the Telegram message.
  No library: no music (`always` says so in the notes).
- The mix is brought to -14 LUFS as one track (`audio.py`).

## B-roll: stock footage for image scenes

With `PEXELS_API_KEY` and/or `PIXABAY_API_KEY` in `$HERMES_HOME/.env` (both free) and `elements.broll` not
`off`, the writer may use image scenes as footage: `"src": "stock:busy mumbai street at night"`. Before the
render, `broll.py` searches Pexels then Pixabay (portrait clips at least 1280 px tall and 3 s long first,
then photos), downloads the match once into `$HERMES_HOME/studio/broll/`, and credits it in the notes
("Video by … on Pexels (link)"). No key, b-roll off, or nothing found: the scene becomes a title card with
its caption, and the notes say why. Without a key the writer is not offered image scenes at all.

## A profile from a video you like

```
python -m orchestrator.studio profile from liked.mp4 --name mypage [--force]
```

Measures the reference with ffmpeg and writes `$HERMES_HOME/studio/profiles/mypage.yaml` (`extends: default`,
the measurements as comments): the cut rate sets the transition, its speed, punch-ins and drift (a shot
every <1.2 s → hard cuts; >5 s → fades and a soft feel); the most common dark colour becomes the background
and the most common vivid one (with 3:1 contrast) the accent, a second hue the "cool" colour; the length
becomes `writing.seconds` and the typical pause `voice.pause`. Nothing of the video is kept. Captions, fonts
and the voice stay the default's until you change them.

## Overnight queue: notes in, a checked video on Telegram and Drive out

```
/studio make <notes>          # adds a job (Claude writes it now through the API, or via the handoff repo)
/studio run                   # renders waiting jobs now instead of in the render window
/studio pick <job> <n>        # re-renders the job with hook n
/studio queue                 # lists the jobs and their state
python -m orchestrator.studio queue add|run|pick|list   # the same on the host
```

A job is a folder `$HERMES_HOME/studio/queue/<id>/`: `writing` (Claude answering through the handoff repo)
→ `ready` → `rendered` → `done`, or `failed` with the reason sent to you. The `studio` cron
(`install.sh` prints the line; every 30 minutes) collects handoff answers and renders inside
`studio.render_window`, one run at a time.

- **Who writes:** `studio.claude_via` — `api` needs `ANTHROPIC_API_KEY`; `handoff` uses your Claude plan:
  Hermes commits `studio/<job>/request.md` to the handoff repo and opens an issue, the Claude scheduled task
  commits `storyboard.json` (and a `sceneNN.tsx` per custom scene) following `studio/HANDOFF.md`; any check
  that fails goes back once as `fix-1.md`. `auto` = the API when the key is set.
- **What renders:** the video with hook 1, and (`hook_clips`) hooks 2 and 3 as clips of the hook scene alone,
  plus the cover the writer chose.
- **Sound:** the voice is brought to -14 LUFS (what platforms play shorts at; Kokoro speaks near -18) with
  peaks held under -1.5 dBTP by a limiter.
- **Quality check** (`qc.py`, ffprobe/ffmpeg on the finished file). Blocking: H.264 1080×1920 at 30 fps
  yuv420p, AAC audio, the expected length, true peak under -0.5 dBTP. Warnings: loudness outside -17…-11 LUFS,
  silence longer than the longest scripted pause, black or frozen picture, over 50 MB.
- **Delivery:** Telegram gets the video (a 720p copy when over 48 MB), the hook clips, the cover and a message
  with the QC summary and the script. Drive (`python -m orchestrator.studio auth drive` once; scope
  `drive.file`, folder "Hermes Studio") gets the full video only when QC passed.

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

- **B-roll** (`tests/test_broll.py`, fake Pexels/Pixabay): the right file is fetched once and credited; Pixabay
  when Pexels is down; a title card (and the reason) without footage; the writer offers footage only with a key.
- **Reference profiles** (`tests/test_reference.py`, ffmpeg-made videos): fast cutting → hard cuts, slow → fades;
  the dark background and vivid accent carry over; the written profile loads and is not overwritten.

- **Sound** (`tests/test_sound.py`, real ffmpeg): effects land on the cuts, the emoji and (always) the items;
  only licensed music for the profile is used and credited; the mix lasts the video, the music is there in
  pauses, ducked under words and faded at the end.

- **Queue** (`tests/test_queue.py`): a job goes notes → storyboard → render → Telegram/Drive with fake
  tools; a handoff answer is collected and a failing one gets one fix round; pick re-renders; the lock and the
  window hold; QC and loudness run on real ffmpeg-made files (a quiet tone comes out at -14 LUFS).

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
