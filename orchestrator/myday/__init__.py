"""My day: a gamified day planner in Telegram on Microsoft To Do. No model call anywhere.

- ``settings``: myday.yaml → frozen Settings (times, points, To Do list names, health nudges).
- ``game``: points, levels and the streak in state.json; the badge under every Telegram message.
- ``todo``: Microsoft To Do through Graph (lists, tasks, steps), on the brief's Outlook login.
- ``session``: settings, clock, state and To Do for one command or cron run.
- ``dates``: due-date words read by script (today, fri, 25 nov, +3, someday).
- ``day``: today's board, top picks, done/snooze/move, crediting tasks ticked in the To Do app.
- ``bills``: generated → due timeline per bill, To Do tasks with reminders, paid on time or late.
- ``goals``: work and personal goals as To Do tasks; milestones are their steps.
- ``health``: nudges at fixed times and a private local log.
- ``card``: the 07:30 card, the evening wrap-up and the 15-minute tick.
- ``celebrate``: the streak GIFs (Pillow) sent through the Hermes Telegram bot.
- ``chat`` / ``cli``: /day, /bills, /goals, /health; ``python -m orchestrator.myday``.
"""
