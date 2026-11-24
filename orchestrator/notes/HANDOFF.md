# Smriti → Claude handoff (copy this file into your private handoff repo)

Hermes opens an issue in this repo for every `/notes … claude` request. Your Claude scheduled task
starts on the **issue opened** event and does this:

1. Read the issue. It names a folder `smriti/<id>/` holding:
   - `request.md`: what to write (summary, task list, PRD, or a document described in words) and the
     meeting's subject and time.
   - `transcript.md`: the meeting, one line per turn: `[mm:ss] Name: words`. Hindi is in Latin script.
2. Write the document in English **from the transcript only**: never invent names, numbers or dates;
   write "Not discussed" where something is missing. Markdown with `#` headings and `-` bullets
   (Hermes turns it into a Word file).
3. Commit it as `smriti/<id>/result.md` on the default branch.
4. Close the issue.

Hermes checks for `result.md` every 15 minutes and sends it to you on Telegram. Nothing else in the
repo is read. Transcripts are private meeting content: keep this repo private.
