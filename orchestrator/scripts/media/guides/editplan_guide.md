# Writing plan.json (editplan.py)

You write one JSON file. Scripts do the rest, so never run ffmpeg yourself and never read the whole transcript.

## Steps
1. `editplan.py transcribe VIDEO --out t.json` (once per video; skip if t.json exists)
2. `editplan.py brief t.json` reads as `start-end text` lines. If it ends with `# truncated at N`, run again with `--from N`.
3. Write `plan.json` next to the video (see below).
4. `editplan.py validate plan.json` — fix every ERROR. A `warn: overlap` means repeated footage; keep it only if intended.
5. `editplan.py render plan.json --out out.mp4 --transcript t.json` (the `--transcript` is needed for captions)
6. `editplan.py qc out.mp4 --plan plan.json` — all lines must PASS before you deliver. On FAIL, change the plan, not the output.

## Plan
```json
{
  "source": "input.mp4",
  "output": {"width": 1080, "height": 1920, "fps": 30, "fit": "crop"},
  "segments": [
    {"start": 12.0, "end": 18.5, "note": "hook"},
    {"start": 40.2, "end": 55.0, "speed": 1.25, "note": "demo"}
  ],
  "captions": {"enabled": true, "words_per_line": 5},
  "music": {"path": "bed.mp3", "gain_db": -18, "duck": true}
}
```
- `segments` is the only required key. Segments play in the order written, so reordering is just ordering. Times are seconds in the source.
- `speed` 0.5 to 2.0 (default 1). Expected length = sum of (end - start) / speed.
- `output`: give width AND height together (even numbers) or neither (keeps source size). `fit` is `crop` (fills the frame, trims edges) or `pad` (whole picture, black bars). Omit the rest unless asked.
- `captions` need the transcript; words come from it, so cut on sentence or word edges to avoid half-words.
- `music`: relative paths resolve next to plan.json. `gain_db` -40 to 0.
- `source` and `music.path` are relative to the plan file.

## Cut rules of thumb
- Start a segment at the first word, end it just after the last (about 0.2 s of room). Never cut mid-word.
- Drop dead air, false starts and repeats; do not drop a sentence another kept sentence depends on.
- Segments under 0.3 s trigger a warning; merge them.

## What qc does and does not check
Checks: streams exist, duration and size match the plan, black frames, frozen picture, dead air, a/v start and length, loudness near -16 LUFS.
Does not check: lip-sync drift inside the content, caption wording, whether the cut is good. Look at one frame or listen if it matters.

## Brand rules
Fonts, colours, caption style beyond the keys above, and intro/outro clips are not set here. Ask the user for them; do not invent.
