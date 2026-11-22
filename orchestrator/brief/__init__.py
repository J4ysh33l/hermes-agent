"""Morning brief: one Telegram message at 8:15 IST built by scripts, ranked by one Gemini call.

Modules:
- ``items``     the shared record types (Item, SourceResult, Quote) and the error kinds.
- ``net``       a tiny stdlib HTTP client; tests swap in a fake with the same interface.
- ``settings``  ``brief.yaml`` (hand-edited) + ``prefs.json`` (changed by /brief commands) → Settings.
- ``creds``     reads ``$HERMES_HOME/.env`` (cron scripts get a sanitized environment) and token files.
- ``sources/``  one module per source: slack, gmail, outlook, news, markets.
- ``filters``   seen-store, newsletters, muted senders/words, excluded mail, topic tagging, size cap.
- ``rank``      the single Gemini call with its fallback chain; unranked order if every model fails.
- ``render``    the Telegram text (top items, markets block, what failed) and the ``more`` list.
- ``store``     state folder: seen ids, last run, saved editions.
- ``cli``       ``python -m orchestrator.brief <command>``; the Hermes plugin and cron launcher call it.
"""
