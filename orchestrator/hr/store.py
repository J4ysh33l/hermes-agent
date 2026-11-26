"""Your HR files kept in your private GitHub repo, so a new Hermes (or a Claude session) starts with them.

In the repo (``hr.store_repo``, default ``notes.handoff_repo``; it must be PRIVATE: the templates carry
your signature): ``hr/templates/*.docx`` (offer letters, payslip) and ``hr/duties.json`` (the duties
kept per position). Token: the same ``GITHUB_HANDOFF_TOKEN`` (Contents read/write).

``/hr sync pull`` copies them into ``$HERMES_HOME/hr/`` (a file you have changed locally is replaced;
run it on a new machine, or after editing a template in the repo). ``/hr sync push`` sends yours up.
Duties are pushed by themselves after an offer that wrote a new position, when the store is set up.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from orchestrator.brief.net import HttpError
from orchestrator.handoff import Handoff, HandoffError

FOLDER = "hr"
TEMPLATES = "templates"
DUTIES = "duties.json"
KINDS = (".docx",)


def _repo(ctx) -> Handoff:
    return Handoff(ctx.http, ctx.secrets, ctx.settings.store_repo)


def _get(repo: Handoff, path: str):
    try:
        return repo._call("GET", f"contents/{path}")
    except HttpError as exc:
        if exc.status == 404:
            return None
        raise


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    tmp.replace(path)


def _blob(repo: Handoff, entry: dict) -> bytes:
    found = _get(repo, entry["path"])
    if found and found.get("content"):
        return base64.b64decode(found["content"])
    # over 1 MB the contents API leaves content empty: the blob API has it
    return base64.b64decode(repo._call("GET", f"git/blobs/{entry['sha']}")["content"])


def pull(ctx) -> str:
    repo = _repo(ctx)
    if not repo.ready:
        return ("The HR store is not set up: hr.store_repo (or notes.handoff_repo) in brief.yaml and "
                "GITHUB_HANDOFF_TOKEN in .env.")
    got = []
    try:
        listing = _get(repo, f"{FOLDER}/{TEMPLATES}") or []
        for entry in listing if isinstance(listing, list) else []:
            if entry.get("type") == "file" and entry["name"].lower().endswith(KINDS):
                _write(ctx.paths.templates / entry["name"], _blob(repo, entry))
                got.append(entry["name"])
        found = _get(repo, f"{FOLDER}/{DUTIES}")
        if found:
            _write(ctx.paths.home / DUTIES, base64.b64decode(found["content"]))
            got.append(DUTIES)
    except (HttpError, HandoffError, OSError) as exc:
        return f"Pull stopped: {getattr(exc, 'status', '') or exc}. Got so far: {', '.join(got) or 'nothing'}."
    if not got:
        return f"Nothing in {repo.repo}/{FOLDER}/ yet. /hr sync push sends your templates and duties there."
    return f"Pulled from {repo.repo}: {', '.join(got)}."


def push(ctx) -> str:
    repo = _repo(ctx)
    if not repo.ready:
        return ("The HR store is not set up: hr.store_repo (or notes.handoff_repo) in brief.yaml and "
                "GITHUB_HANDOFF_TOKEN in .env.")
    files = sorted(p for p in ctx.paths.templates.glob("*") if p.suffix.lower() in KINDS) if ctx.paths.templates.is_dir() else []
    duties = ctx.paths.home / DUTIES
    sent = []
    try:
        for path in files:
            repo.put(f"{FOLDER}/{TEMPLATES}/{path.name}", path.read_bytes())
            sent.append(path.name)
        if duties.is_file():
            repo.put(f"{FOLDER}/{DUTIES}", duties.read_bytes())
            sent.append(DUTIES)
    except (HttpError, HandoffError, OSError) as exc:
        return f"Push stopped: {getattr(exc, 'status', '') or exc}. Sent so far: {', '.join(sent) or 'nothing'}."
    return f"Pushed to {repo.repo}: {', '.join(sent)}." if sent else "Nothing to push (no templates or duties yet)."


def push_duties(ctx) -> None:
    """After an offer: the duties table up to the store, quietly (no store, or GitHub down: kept locally)."""
    repo = _repo(ctx)
    duties = ctx.paths.home / DUTIES
    if not repo.ready or not duties.is_file():
        return
    try:
        repo.put(f"{FOLDER}/{DUTIES}", duties.read_bytes())
    except (HttpError, HandoffError, OSError):
        pass
