"""Outreach: Slack messages sent as you, and Outlook meetings, approved from Telegram.

Modules:
- ``settings``    the ``outreach:`` section of brief.yaml (cap, gap, models, message templates).
- ``times``       clock words for the fixed commands (15:00, 3pm-6pm, 15m, tomorrow).
- ``slackapi``    Slack Web API calls (user token): users, channels, DMs, post, schedule.
- ``graph``       Microsoft Graph: your busy times, colleague lookup, creating events (Teams).
- ``people``      names → people (Slack, then the Outlook directory); never guesses.
- ``slots``       packs meetings back to back from the window start with a gap.
- ``understand``  the model calls (read a sentence, write messages, pick meeting requests).
- ``plan``        plans waiting for approval, the send log and the daily cap.
- ``build``       requests → plans; ``execute`` runs an approved plan.
- ``session``     one command's settings, secrets, clock and logins.
- ``chat``        /slack and /meet handlers, and ``draft`` for Hermes' agent (cannot send).
- ``cli``         ``python -m orchestrator.outreach draft|slack|meet ...``.
"""
