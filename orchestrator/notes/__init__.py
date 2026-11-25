"""Smriti: summaries, task lists, PRDs and other documents from your Teams meetings. No model reads a
meeting you did not ask about.

- ``settings``: the ``notes:`` section of brief.yaml (check hours, chunking, token pacing, audio budget).
- ``store``: the meetings remembered, your requests, finding a meeting by words from its subject.
- ``teams``: Microsoft Graph: ended meetings you organised, their transcripts and recordings by session.
- ``vtt``: Teams transcripts (WebVTT) → timed lines with speakers; sessions joined in time order.
- ``audio``: recording → mono audio chunks with ffmpeg (the video is never sent).
- ``transcribe``: chunks → Gemini (Hindi in Latin script), paced under your tokens-per-minute; names from Teams.
- ``docs``: summary, tasks, PRD, any named document from the transcript text; Markdown → .docx.
- ``handoff``: Claude writes it through your private repo (issue event → result.md).
- ``telegram``: messages and files to you with Hermes' bot.
- ``work``: the 2-hourly check that asks you, and the queue that makes and delivers.
- ``chat`` / ``cli``: ``/notes``; ``python -m orchestrator.notes run|check``.
"""

from . import audio, chat, cli, docs, handoff, settings, store, teams, telegram, transcribe, vtt, work

__all__ = ["audio", "chat", "cli", "docs", "handoff", "settings", "store", "teams", "telegram", "transcribe",
           "vtt", "work"]
