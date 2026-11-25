"""Watches: tell you when a page adds something (job openings, uploads, posts). A script reads and
compares; Claude, through the handoff repo, researches new pages and writes notes on changes.

Modules:
- ``settings``  the ``watch:`` section of brief.yaml.
- ``sources``   a page → items: job-board JSON feeds, RSS/Atom, or a page's links; ``detect`` picks one.
- ``store``     the watches and what each saw last (``$HERMES_HOME/watch/watches.json``).
- ``claude``    the two requests to Claude (setup research, change note) and reading its answers.
- ``work``      one check, and the cron run: due checks, then Claude's answers.
- ``chat``      /watch add · list · check · every · match · pause · resume · remove · claude · ask.
- ``cli``       ``python -m orchestrator.watch run`` (the cron) or any /watch words on the host.
"""
