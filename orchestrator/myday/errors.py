"""The one error kind My day raises: a message the user can act on, shown as is."""

from __future__ import annotations


class MyDayError(Exception):
    """Something to tell the user ('To Do: HTTP 403 …', 'no bill 4'). Nothing was changed for the
    step that raised it."""
