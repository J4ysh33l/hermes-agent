"""The one error kind outreach raises: a message the user can act on, shown as is."""

from __future__ import annotations


class OutreachError(Exception):
    """Something to tell the user ('Slack: not_in_channel', 'no Outlook login'). Nothing was sent
    for the step that raised it."""
