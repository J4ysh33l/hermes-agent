#!/usr/bin/env python3
"""changed.py - "did anything change since last time?" gate, so a routine skips its LLM turn when nothing did.
No LLM, standard library only. State: $AGENT_STATE_DIR/changed/<KEY>.json (default ~/.agent-state).

  changed.py check KEY --file PATH | --dir PATH | -- COMMAND [ARGS...]   exit 0 = changed (do the work), exit 3 = unchanged
  changed.py peek  KEY ...same sources...    same answer, but does not record it
  changed.py mark  KEY ...same sources...    record the current state (exit 0)
  changed.py reset KEY

Use in a routine:   changed.py check range-sales --file /files/pipeline.csv; [ $? = 3 ] && exit 0
(not `|| exit 0`: that would also stop on exit 2, an unreadable source. On an error the safe move is to do the work.)
`check` records the new state at once, so if the work after it fails the change is not offered again. To avoid
that, run `peek` first, do the work, then `mark` on success.
The first call for a KEY always counts as changed. A source that cannot be read (file missing, command fails)
exits 2 and records nothing: an error is never reported as "unchanged".
--file hashes contents. --dir hashes names, sizes and mtimes of everything under it (cheap, for big media
folders; shortcut: touching a file with no edit counts as a change, switch to hashing contents if that matters).
-- COMMAND is run without a shell; its stdout is hashed.
"""
import argparse, hashlib, json, os, re, subprocess, sys, tempfile
from datetime import datetime, timezone, UTC
from pathlib import Path

CHANGED, UNCHANGED, ERROR = 0, 3, 2


def state_file(key):
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", key):
        print("changed: KEY must be 1-80 characters of letters, digits, . _ -", file=sys.stderr)
        sys.exit(ERROR)
    return Path(os.environ.get("AGENT_STATE_DIR") or os.path.expanduser("~/.agent-state")) / "changed" / f"{key}.json"


def digest(a):
    h = hashlib.sha256()
    if a.file:
        h.update(Path(a.file).read_bytes())
    elif a.dir:
        root = Path(a.dir)
        if not root.is_dir():
            raise FileNotFoundError(a.dir)
        for p in sorted(x for x in root.rglob("*") if x.is_file()):
            st = p.stat()
            h.update(f"{p.relative_to(root)}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    else:
        p = subprocess.run(a.cmd, capture_output=True, timeout=300, check=False)
        if p.returncode != 0:
            raise RuntimeError(f"command exited {p.returncode}: {p.stderr.decode(errors='replace')[:200]}")
        h.update(p.stdout)
    return h.hexdigest()


def save(f, value):
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=f.parent)
    with os.fdopen(fd, "w") as fh:
        json.dump({"hash": value, "at": datetime.now(UTC).isoformat(timespec="seconds")}, fh)
    os.replace(tmp, f)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["check", "peek", "mark", "reset"])
    ap.add_argument("key")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--file")
    src.add_argument("--dir")
    argv = sys.argv[1:]
    cmd = []
    if "--" in argv:  # everything after -- is the command; argparse REMAINDER would swallow --file
        i = argv.index("--")
        argv, cmd = argv[:i], argv[i + 1:]
    a = ap.parse_args(argv)
    a.cmd = cmd
    f = state_file(a.key)
    if a.action == "reset":
        f.unlink(missing_ok=True)
        print(f"reset {a.key}")
        return CHANGED
    if not (a.file or a.dir or a.cmd):
        ap.error("give --file PATH, --dir PATH or -- COMMAND")
    try:
        new = digest(a)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
        print(f"changed: cannot read source ({e}); nothing recorded", file=sys.stderr)
        return ERROR
    try:
        old = json.loads(f.read_text(encoding="utf-8")).get("hash")
    except (OSError, ValueError):
        old = None
    if a.action == "mark":
        save(f, new)
        print("marked")
        return CHANGED
    same = old == new
    if a.action == "check" and not same:
        save(f, new)
    print("unchanged" if same else "changed")
    return UNCHANGED if same else CHANGED


if __name__ == "__main__":
    sys.exit(main())
