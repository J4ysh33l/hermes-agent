"""Names → people. Never guesses: a name that fits two people stops that line.

Order: an email address as given; else your Slack workspace (handle, display name, real name, first
name, email name; exact first, then 'starts with'); else your company directory in Outlook, whose
email then finds their Slack account. A 'starts with' match ('@jay' → Jaysheel Bhatt) is marked
``exact=False``: commands that send at once refuse it and ask for the full name; previews accept
it, since you see the full name before anything goes. A name that matches no one gets up to three
"did you mean" suggestions from the workspace; none is ever picked for you. Someone found only in Outlook has no Slack id: they get the
invite email, not a Slack note.

The Slack member list is cached for 12 hours in ``outreach/slack_users.json``.
"""

from __future__ import annotations

import difflib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from orchestrator.brief.net import Http

from . import graph, slackapi
from .errors import OutreachError

CACHE_SECONDS = 12 * 3600
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Person:
    name: str
    first: str
    email: str = ""
    slack_id: str = ""


@dataclass(frozen=True)
class Lookup:
    """``person`` when exactly one match, else ``problem`` says why (shown to you)."""

    word: str
    person: Person | None = None
    problem: str = ""
    exact: bool = True  # False: matched by 'starts with' only


def _member(m: dict) -> Person:
    p = m.get("profile") or {}
    real = p.get("real_name") or m.get("real_name") or ""
    name = p.get("display_name") or real or m.get("name", "")
    first = p.get("first_name") or (real or name).split(" ")[0]
    return Person(name=name, first=first, email=(p.get("email") or "").lower(), slack_id=m["id"])


def _keys(m: dict) -> set[str]:
    p = m.get("profile") or {}
    real = (p.get("real_name") or m.get("real_name") or "").lower()
    email = (p.get("email") or "").lower()
    return {k for k in (m.get("name", "").lower(), (p.get("display_name") or "").lower(), real,
                        (p.get("first_name") or real.split(" ")[0]).lower(), email.split("@")[0]) if k}


def clean(word: str) -> str:
    return word.strip().lstrip("@").strip(" ,.;:").strip()


class Directory:
    def __init__(self, http: Http, slack_token: str, state_dir: Path,
                 graph_token: Callable[[], str] | None = None, now: float | None = None) -> None:
        self._http, self._token, self._graph_token = http, slack_token, graph_token
        self._cache = state_dir / "outreach" / "slack_users.json"
        self._now = time.time() if now is None else now
        self._members: list[dict] | None = None

    def members(self) -> list[dict]:
        if self._members is None:
            self._members = self._load()
        return self._members

    def _load(self) -> list[dict]:
        if self._cache.is_file():
            data = json.loads(self._cache.read_text(encoding="utf-8"))
            if self._now - data.get("saved", 0) < CACHE_SECONDS:
                return data["members"]
        rows = [m for m in slackapi.users(self._http, self._token)
                if not m.get("deleted") and not m.get("is_bot") and m.get("id") != "USLACKBOT"]
        self._cache.parent.mkdir(parents=True, exist_ok=True)
        self._cache.write_text(json.dumps({"saved": self._now, "members": rows}), encoding="utf-8")
        return rows

    def by_id(self, user_id: str) -> Person | None:
        return next((_member(m) for m in self.members() if m["id"] == user_id), None)

    def _by_email(self, email: str, name: str = "", first: str = "") -> Person:
        hit = next((m for m in self.members() if (m.get("profile") or {}).get("email", "").lower() == email), None)
        if hit is None and self._token:
            hit = slackapi.by_email(self._http, self._token, email)
        if hit:
            return _member(hit)
        # An address with no name anywhere (an outside guest): show the address, greet "there".
        return Person(name=name or email, first=first or (name.split(" ")[0] if name else "there"), email=email)

    def _suggest(self, word: str) -> str:
        names = {k: _member(m).name for m in self.members() for k in _keys(m)}
        close = dict.fromkeys(names[k] for k in difflib.get_close_matches(word.lower(), list(names), n=6, cutoff=0.75))
        return f" Did you mean {', '.join(list(close)[:3])}?" if close else ""

    def _slack(self, word: str, handle: bool) -> tuple[list[dict], bool]:
        low = word.lower()
        if handle:  # '@priya' means the Slack handle or display name, before any first-name match
            named = [m for m in self.members()
                     if low in (m.get("name", "").lower(), ((m.get("profile") or {}).get("display_name") or "").lower())]
            if len(named) == 1:
                return named, True
        exact = [m for m in self.members() if low in _keys(m)]
        if exact:
            return exact, True
        return [m for m in self.members() if any(k.startswith(low) for k in _keys(m))], False

    def _outlook(self, word: str) -> list[dict[str, str]]:
        if self._graph_token is None:
            return []
        try:
            return graph.find_people(self._http, self._graph_token(), word)
        except OutreachError:
            return []

    def find(self, raw: str) -> Lookup:
        word = clean(raw)
        if not word:
            return Lookup(raw, problem="empty name")
        if EMAIL.match(word):
            return Lookup(raw, self._by_email(word.lower()))
        found, exact = self._slack(word, raw.strip().startswith("@"))
        if len(found) == 1:
            return Lookup(raw, _member(found[0]), exact=exact)
        if len(found) > 1:
            names = ", ".join(_member(m).name for m in found[:5])
            return Lookup(raw, problem=f"'{word}' matches {names}. Use their @handle or email.")
        staff = self._outlook(word)
        if len(staff) == 1:
            return Lookup(raw, self._by_email(staff[0]["email"].lower(), staff[0]["name"], staff[0]["first"]))
        if len(staff) > 1:
            names = ", ".join(s["name"] for s in staff[:5])
            return Lookup(raw, problem=f"'{word}' matches {names} in Outlook. Use their email.")
        return Lookup(raw, problem=f"No one called '{word}' in Slack or your company directory.{self._suggest(word)}")

    def find_all(self, words: list[str], exact_only: bool = False) -> tuple[list[Person], list[str]]:
        """(people found, in order and without repeats; problems). ``exact_only`` turns a
        'starts with' match into a problem that names the person it would have been."""
        people: list[Person] = []
        problems: list[str] = []
        for word in words:
            hit = self.find(word)
            if hit.person is not None and exact_only and not hit.exact:
                problems.append(f"'{clean(word)}' is not a full name. Did you mean {hit.person.name}? "
                                "Write their full first name, @handle or email.")
            elif hit.person is None:
                problems.append(hit.problem)
            elif hit.person not in people:
                people.append(hit.person)
        return people, problems
