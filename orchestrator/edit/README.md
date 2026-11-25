# Editor (`/edit`): your own footage, cut and finished in a style

This is a separate workflow from the studio. The studio makes faceless videos from notes; the editor
finishes footage of you talking. It runs as its own Hermes profile (`editor`, set up by `install.sh`) and
shares the studio's install: the Python venv with faster-whisper, Remotion and the music library.

The editor can only shorten what you said or add things on top of it: it can't change your words, and
it never shows a number you didn't say. How to record for it: `SHOOTING.md`.

## Commands

```
/edit <Drive link or file> [style] [what you want]   a new job (Drive: share as "anyone with the link")
/edit styles · /edit style <name> · /edit style new <name> [from <style>]
/edit queue · /edit plan <job> · /edit approve <job> · /edit cancel <job> · /edit run
```

On the host:
```
python -m orchestrator.edit run clip.mp4 [--style mine] [--plan plan.json] [--notes "..."]   # end to end, no Claude
python -m orchestrator.edit prompt <job dir>     # the editor's prompt, to plan by hand
python -m orchestrator.edit check <job dir>      # check a plan.json
python -m orchestrator.edit styles · style new <name> [--from mine] · queue
```

## What happens to a job (`queue.py`, cron every 5 minutes)

1. **Fetch and ingest** (`media.py`). The upload becomes `source.mp4`: H.264, 1080×1920, at a constant
   30 fps. Phones record a variable frame rate, which makes cuts and captions drift. HDR is tone-mapped,
   the picture is turned upright, and landscape footage is cropped to the middle.
   Your voice becomes `voice.wav`: rumble cut, noise reduced (`sound.denoise`), sibilance softened, and
   gently levelled.
2. **Transcribe** (`transcript.py`, `asr_worker.py` in the studio venv). faster-whisper `large-v3-turbo`
   gives word times. It writes Hinglish in Latin letters (`edit.asr_language: en`, with a Hinglish prompt
   that also keeps "umm"/"matlab" from being dropped). The words are grouped into numbered sentences
   (`words.py`).
3. **Plan** (`editor.py`, `plan.py`, `prompts/plan.md`). Claude directs the edit. It reads the numbered
   sentences, the style, your notes, the list of your own files in the job's `assets/`, and what the camera
   saw (`watch.py`, with OpenCV in the studio venv). Claude can't play a video, so it gets:
   - `watch.md`: how it was recorded, measured: framing (where your face is, how big), light, focus, the
     room's noise; then a log per sentence of what the picture does (face lost or moving, another face in
     frame, dark, blurred, a jump);
   - **frame sheets** (`frames-*.jpg`): a frame about every second, each labelled with its time and the word
     being said ("21.0s S4.12").

   It writes `plan.json`:
   - sentences to drop and words to trim (how much is its call);
   - the title card;
   - optionally, what covers or joins the face, anchored to words (`S3.5` = sentence 3, word 5):
     - `cutaway`: full-screen b-roll, from your files (`file`) or stock (`query`);
     - `split`: the picture fills the top half and your face moves to the bottom half;
     - `pop`: a 1–3 word chip that springs in beside your face;
     - `stat`, `list`, `chapter`, `headline`, `quote`, `image`, `screenshot` cards;
     - `hide`: a blurred box over anything private (a patient's name, a phone number);
   - punch-ins (they zoom towards your face) and the music mood;
   - optionally a colour fix for this footage ("grade": brighter, warmer, sharper...);
   - **scenes**, storyboarded by idea: an explainer that stays up while an idea is said and builds as it is
     said (`remotion/src/edit/Scenes.tsx`). Layouts: `panel` (top half on the brand colour, your face zoomed
     into the bottom half), `full` (the whole frame while your voice carries on), `top` (big type over the
     wall above your head). Types: statement (with strike-through or underline on a word), counter, stack
     (rows with icons and ✓/✗), steps, compare (a balance), bars, points (bullets struck out, or 01/02),
     badge, and an end card. Elements arrive on their words;
   - words cut from inside a sentence ("cut"), caption words coloured problem/solution ("emphasis"), the end
     card ("end").

   The style can play the talk faster (`pace.speed`, pitch kept; the Medoc reels run at about 1.25×).
   Everything drawn (graphics, scenes and the word-by-word captions with the spoken word in a box) is one
   transparent Remotion render (`Timeline.tsx`) laid over the cut once.

   Claude never sees or writes times, so it can't cut into a word. The plan goes through your Claude plan
   via the handoff repo, the same as the studio. Claude runs `tools/check_edit.py` there before handing
   in, and Hermes checks the plan again:
   - every anchor must exist;
   - no number may appear that you didn't say;
   - no two cards may overlap;
   - only kinds the style allows;
   - b-roll must stay within the style's share (a split counts half);
   - a title of 2–9 words.

   B-roll, graphics and how much to cut are the editor's creative choice: none is required. The checker
   only *suggests* where nothing changes on screen for long. A plan that still fails after
   two rounds becomes a rough cut (cuts, captions, punch-ins). The rough cut is never rendered without
   your approval, even with `edit.approve: false`.
4. **Cut list** (`cuts.py`, code only). This step:
   - cuts pauses longer than `pace.max_pause` down to it;
   - cuts fillers that stand alone ("umm", and "matlab"/"toh" only when isolated);
   - cuts the earlier of two near-identical takes (85% the same words) and false starts;
   - drops and trims what the plan says, unless the plan's `keep` overrules a retake.

   Every cut falls between words, with `pace.pad` of room on each side.
5. **Approval.** The plan comes to you on Telegram: the length, what was cut and why, and every graphic.
   `/edit approve <job>` renders it.
6. **Render** (`render.py`). Each kept stretch is cut out of `source.mp4` with its zoom and grade, and the
   pieces are joined; the length is counted in frames, so picture and sound never drift. Remotion renders
   each graphic alone on a transparent frame, only for its time on screen (`remotion/src/edit/Graphic.tsx`).
   ffmpeg then lays the graphics over the cut, burns the captions (libass), and adds the logo and the
   progress bar. The voice is cut on the same stretches with a 15 ms fade at each joint, mixed with
   effects and ducked music (studio `sound.py`), and brought to −14 LUFS. QC (studio `qc.py`) runs last,
   then the video goes to Telegram and to Drive when you're signed in.

## Styles (`style.py`, `styles/*.yaml`)

| Style | Captions | Title | Graphics | Pace |
|---|---|---|---|---|
| `clean` | white Manrope, 3 words | none | stat, headline, list, chapter, lower third, pictures | calm, no punch-ins |
| `zero1` | white rounded sans, 3 words, sentence case, under the face | white pill | black stat boxes, clippings, emoji | change every ~3.5 s, punch-in every 12 s |
| `aevy` | tiny yellow, 2 words, lower case, mid-frame | white card, editorial serif | clippings, full-bleed photos, progress bar | change every ~1.8 s, smooth pushes |
| **`mine`** (default) | Zero1's | Aevy's serif card | Zero1's boxes and clippings | in between: change every ~2.5 s, punch-in every 10 s |

The reference styles are based on frames from both channels (2026-11-25). Their pacing is estimated, not
measured; `research_notes/Raw footage editing/` has the sources.

Your own style goes in `$HERMES_HOME/edit/styles/<name>.yaml` and states only what differs from the style
it extends. Brand files (your logo) go in `$HERMES_HOME/edit/brand/`. Every field is listed in
`styles/clean.yaml`. The fonts are free look-alikes: Manrope for Zero1's rounded sans, Newsreader for
Aevy's serif.

## Measured (2026-11-25, this container, 4 threads)

| Step | Input | Time |
|---|---|---|
| Ingest (HEVC 1920×1080 → 1080×1920 CFR + voice clean-up) | 47 s clip | 22 s |
| Transcribe, large-v3-turbo int8 | 47 s of speech | 33 s |
| Render: 13 shots, 6 graphics, captions, mix, QC | 36 s edited video | 140–146 s |
| One graphic alone (Remotion, ProRes 4444 with alpha) | 2.5 s | ~23 s, most of it Chrome starting |

On the 2-core host, expect roughly twice as long. Each step runs alone, so Whisper, Chrome and x264 are
never in memory together.

## Not yet
- Face-following reframing of landscape footage (currently a centre crop, or `frame_x` in `media.prepare`),
  and cursor-following zooms in screen demos.
- Footage straight from your own Drive. Hermes' Drive sign-in uses the `drive.file` scope and only sees
  files it made, so today you share a link. Reading your Drive would need a broader permission; that's
  your call.
- Telegram uploads over 20 MB, a Bot API limit. Send big files via Drive.
- A Hinglish fine-tuned Whisper (Oriserve Hindi2Hinglish, Apache-2.0) as `edit.asr_model`, once tested on
  your real footage.
- **Not yet run end to end on real footage with a real Claude plan.** Tested on a synthetic clip carrying
  your voice recording, with a hand-written plan.
