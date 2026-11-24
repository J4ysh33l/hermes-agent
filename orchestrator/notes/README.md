# Smriti: meeting notes

Summaries, task lists, PRDs and any other document from the Teams meetings you organise. Nothing is
transcribed until you ask, and what you ask for is never dropped.

## How it works

1. **You are asked.** At 10, 12, 14, 16, 18 and 20:00, one calendar call finds your Teams meetings
   that ended. For each new one, Telegram asks:
   ```
   🎙 Product sync ended (13:00–13:50) · recording ✓ · transcript ✓ (2 sessions)
   What do you need? /notes product sync summary tasks prd · doc <anything> · transcript
   Add claude to use Claude (default Gemini). Nothing needed: /notes product sync skip
   ```
   An unanswered meeting stays in the 20:00 recap until you answer or `skip`.
2. **The transcript is made once.** The recording is downloaded, the video dropped and the audio cut
   into 45-minute chunks. Each chunk is one Gemini call, at least 70 s after the last, and only when
   the last 60 s of Gemini use (every workflow) plus this call fits your tokens-per-minute.
   - Hindi is written in Latin script.
   - Speakers get their names from the Teams transcript, matched by time.
   - A stop-and-restart is several sessions, joined in time order with a marker.
   - No recording: the Teams transcript is used as it is.
   - Neither after 24 hours: you are told.
   - A daily audio budget (180 min) holds the rest for the next day. The budget is checked before
     any download, from Teams' own times.
3. **Documents come from the saved text.** Summary and tasks arrive as messages; a PRD or a document
   you describe (`doc client follow-up email`) as a Word file. Asking again a week later costs one
   text call: the audio is never sent twice.
4. **Claude** (`… claude`): Hermes commits the transcript and the request to your private handoff
   repo and opens an issue, the event your Claude scheduled task starts on. Claude commits
   `result.md`; Hermes sends it to you. The contract is `HANDOFF.md`.

A request waiting (for the recording, the budget or Claude) or failed is listed in the 20:00 recap.
A failure is retried each run, up to `max_attempts`, then reported with the command to ask again.

## Commands

```
/notes list                                  meetings of the last 7 days and what was made
/notes product sync summary tasks prd        name a meeting by words from its subject, or last
/notes onboarding doc client follow-up email any document: everything after doc says what
/notes last transcript                       the transcript file
/notes product sync skip                     nothing needed
```

Words matching two meetings are never guessed: you are shown both and add a word.

## Tokens

| Step | Input | Output |
|---|---|---|
| One 45-min audio chunk | 86,400 (32 a second) + ~1,000 prompt | transcript ~11–13k |
| Summary / tasks / PRD | the transcript (~15k an hour) + ~800 | ~1.5k / ~0.8k / ~3–6k |

A 1-hour meeting with summary, tasks and PRD: about 140k input and 25k output over 4–5 calls,
none above ~88k.

## Setup

- **Entra:** Delegated **OnlineMeetings.Read**, **OnlineMeetingTranscript.Read.All**,
  **OnlineMeetingRecording.Read.All**, admin consent, then `python -m orchestrator.brief auth microsoft`.
  Works for meetings you organise.
- **Teams:** start **Record and transcribe** in the meeting (or turn on automatic recording in its
  options). Gemini needs the recording; the transcript gives speaker names.
- **ffmpeg** on the host.
- **Cron:** `orchestrator/brief/install.sh` writes `smriti.py`; add the `smriti` cron it prints
  (every 15 minutes; idle runs make no network call).
- **Claude (optional):** `notes.handoff_repo` in `brief.yaml`, `GITHUB_HANDOFF_TOKEN` in `.env`
  (fine-grained, that repo only, Contents and Issues read/write), `HANDOFF.md` in the repo.

## Tested

Against fake Teams, Gemini, Telegram and GitHub, with real ffmpeg on a generated recording
(`tests/test_notes.py`):
- asked once per ended meeting you organised (not others', not running, not non-Teams)
- 9 s of audio in 3 chunks, paced by the gap, each upload deleted, the video not kept
- names from Teams, Hindi-in-Latin prompt, the previous part passed on for speaker numbering
- summary as a message, PRD as a .docx, the transcript reused for a later request
- Claude through the repo
- over the audio budget it waits without downloading
- nothing recorded is reported once after a day
- two matching meetings are never guessed

**Not yet run** against real Teams (waiting on the permissions), real Gemini audio, or the handoff repo.
