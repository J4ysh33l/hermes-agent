"""The evening deadline recap (20:00): one Telegram message of what is waiting on you, by script.

- ``parts``: each part of the recap (approvals, HR mail, To Do tasks and bills, calendar deadlines),
  read from the files the other workflows keep and from Outlook; a part that fails is named.
- ``resume``: ``/resume <n>`` brings back an expired approval after checking it is still safe.
- ``cli``: ``python -m orchestrator.recap now`` (the cron and ``/recap now``); help otherwise.

No model call anywhere.
"""

from . import cli, parts, resume

__all__ = ["cli", "parts", "resume"]
