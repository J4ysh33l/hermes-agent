#!/usr/bin/env python3
"""bigfile.py - read only what is new in a huge CSV/log/queue file, filter it, and trim it with an archive.
No LLM, standard library only. Replaces "the bot reads the whole 450k-character file every run".
State: $AGENT_STATE_DIR/bigfile/ (default ~/.agent-state), archives in $AGENT_STATE_DIR/archive/.

  bigfile.py new  FILE --consumer NAME [--max-rows 200] [--cell-chars 200] [--cols a,b] [--where C>=V ...] [--peek]
      Rows added since NAME last read this file. Exit 0 = rows printed, 3 = nothing new, 2 = error.
      Each consumer (a bot or routine) has its own place in the file.
  bigfile.py view FILE [--tail N] [--max-rows 200] [--cell-chars 200] [--cols a,b] [--where C>=V ...]
      Stateless filtered look, e.g. next week's calendar rows:  view calendar.csv --where date>=2026-11-23 --where date<=2026-11-29
  bigfile.py trim FILE (--keep-rows N | --keep-chars N) [--archive-dir DIR] [--apply]
      Keeps the header and the newest rows; older rows are APPENDED to an archive file, never deleted.
      Dry run unless --apply. Run it while the writers are paused (pausectl) or at a quiet hour.
  bigfile.py reset FILE --consumer NAME      read from the start next time

.csv files are read as CSV (header row, quoted multi-line cells); anything else row = line (--cols/--where need CSV).
--where COL=V | COL>=V | COL<=V compares text, so ISO dates work; several --where are ANDed.
A last line without a trailing newline is a row still being written: `new` leaves it for next time and `trim` refuses.
Shortcut: a file replaced by another with at least as many rows cannot be detected; run `reset` after replacing one.
Shortcut: trim's last re-check is a size+mtime test just before the swap; an append in that instant would be lost.
"""
import argparse, csv, fcntl, hashlib, io, json, os, re, sys, tempfile
from contextlib import contextmanager
from pathlib import Path


def state_root():
    return Path(os.environ.get("AGENT_STATE_DIR") or os.path.expanduser("~/.agent-state"))


def read_text(path):
    with open(path, newline="", encoding="utf-8", errors="surrogateescape") as f:
        return f.read()


def records(text, is_csv):
    """-> (raw records each keeping its line ending, text ends inside an open quote).
    CSV rules like the csv module: a quote opens only at the start of a field, "" inside quotes is a literal
    quote, so 6" frame in an unquoted cell does not swallow the rows after it."""
    if not is_csv:
        return text.splitlines(keepends=True), False
    out, start, quoted, fs, i, n = [], 0, False, True, 0, len(text)
    while i < n:
        ch = text[i]
        if quoted:
            if ch == '"':
                if text[i + 1:i + 2] == '"':
                    i += 1
                else:
                    quoted = False
        elif ch == '"' and fs:
            quoted = True
        elif ch == "\n":
            out.append(text[start:i + 1])
            start, fs, i = i + 1, True, i + 1
            continue
        fs = not quoted and ch == ","
        i += 1
    if start < n:
        out.append(text[start:])
    return out, quoted


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)


def parse(rec):
    return next(csv.reader([rec]), [])


@contextmanager
def locked(path):
    """Per-file state record: {"dropped": rows removed by trim, "cursors": {consumer: absolute rows read}}."""
    key = hashlib.sha1(str(Path(path).resolve()).encode()).hexdigest()[:12]
    d = state_root() / "bigfile"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{key}.lock", "w", encoding="utf-8") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        sf = d / f"{key}.json"
        try:
            st = json.loads(sf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {"path": str(Path(path).resolve()), "dropped": 0, "cursors": {}}
        yield st
        fd, tmp = tempfile.mkstemp(dir=d)
        with os.fdopen(fd, "w") as fh:
            json.dump(st, fh)
        os.replace(tmp, sf)


def load(path):
    """-> (is_csv, header_raw|None, data_records, tail). tail: "ok", "partial" (last line has no newline: a
    writer is mid-row) or "open_quote" (the file ends inside a quoted cell: mid-row, or a broken row)."""
    is_csv = str(path).lower().endswith(".csv")
    text = read_text(path)
    recs, open_q = records(text, is_csv)
    header = recs.pop(0) if is_csv and recs else None
    tail = "open_quote" if open_q and text.endswith("\n") else "partial" if open_q or (text and not text.endswith("\n")) else "ok"
    return is_csv, header, recs, tail


def make_filter(wheres, header):
    if not wheres:
        return lambda row: True
    if header is None:
        die("bigfile: --cols/--where need a .csv file with a header row")
    names = [c.strip() for c in parse(header)]
    tests = []
    for w in wheres:
        m = re.fullmatch(r"([^=<>]+)(>=|<=|=)(.*)", w)
        if not m or m.group(1).strip() not in names:
            die(f"bigfile: bad --where {w!r}; columns are: {', '.join(names)}")
        tests.append((names.index(m.group(1).strip()), m.group(2), m.group(3)))

    def ok(row):
        for i, op, v in tests:
            cell = row[i].strip() if i < len(row) else ""
            if not (cell == v if op == "=" else cell >= v if op == ">=" else cell <= v):
                return False
        return True
    return ok


def show(header, recs, a):
    """Print header + rows compactly (cells cut at --cell-chars, newlines in cells become spaces)."""
    cols = None
    if a.cols:
        if header is None:
            die("bigfile: --cols/--where need a .csv file with a header row")
        names = [c.strip() for c in parse(header)]
        want = [c.strip() for c in a.cols.split(",")]
        bad = [c for c in want if c not in names]
        if bad:
            die(f"bigfile: unknown column(s) {bad}; columns are: {', '.join(names)}")
        cols = [names.index(c) for c in want]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")

    def emit(rec):
        row = parse(rec) if header is not None else [rec.rstrip("\r\n")]
        if cols is not None:
            row = [row[i] if i < len(row) else "" for i in cols]
        w.writerow([(c.replace("\n", " ").replace("\r", "")[:a.cell_chars] + ("~" if len(c) > a.cell_chars else "")) for c in row])
    if header is not None:
        emit(header)
    for r in recs:
        emit(r)
    sys.stdout.write(out.getvalue())


def cmd_new(a):
    with locked(a.file) as st:  # lock first: a concurrent trim must not change the file under our position
        is_csv, header, recs, tail = load(a.file)
        if tail != "ok" and recs:
            recs = recs[:-1]
        ok = make_filter(a.where, header)
        pos = st["cursors"].get(a.consumer, 0) - st["dropped"]
        if pos < 0:
            print(f"# {-pos} unread rows were moved to the archive by trim; reading from the oldest kept row")
            pos = 0
        elif pos > len(recs):
            print("# file has fewer rows than last read (replaced or shortened); reading from the start")
            pos = 0
        picked, i = [], pos
        while i < len(recs) and len(picked) < a.max_rows:
            if ok(parse(recs[i]) if is_csv else recs[i]):
                picked.append(recs[i])
            i += 1
        if not a.peek:
            st["cursors"][a.consumer] = st["dropped"] + i
    if tail == "open_quote":
        print("# the file ends inside an unclosed quote: the last row (and anything after it) is not readable yet", file=sys.stderr)
        if not picked:
            return 2
    if not picked:
        print("# no new rows")
        return 3
    show(header, picked, a)
    if len(recs) - i > 0:
        print(f"# {len(recs) - i} more unread rows; run again for the next batch")
    return 0


def cmd_view(a):
    is_csv, header, recs, tail = load(a.file)
    if tail != "ok" and recs:
        recs = recs[:-1]
    ok = make_filter(a.where, header)
    rows = [r for r in recs if ok(parse(r) if is_csv else r)]
    n = min(a.tail, a.max_rows) if a.tail else a.max_rows
    shown = rows[-n:] if a.tail else rows[:n]
    if not shown:
        print("# no matching rows")
        return 3
    show(header, shown, a)
    if len(rows) > len(shown):
        print(f"# {len(rows) - len(shown)} more matching rows not shown (raise --max-rows)")
    return 0


def cmd_trim(a):
    path = Path(a.file)
    st0 = path.stat()
    is_csv, header, recs, tail = load(path)
    if tail != "ok":
        print("bigfile: the file ends mid-row (no final newline or an unclosed quote); a writer may be busy or a row is broken; "
              "nothing modified", file=sys.stderr)
        return 2
    keep, chars = 0, 0
    for r in reversed(recs):
        if (a.keep_rows is not None and keep >= a.keep_rows) or (a.keep_chars is not None and chars + len(r) > a.keep_chars):
            break
        keep, chars = keep + 1, chars + len(r)
    moved = recs[:len(recs) - keep]
    if not moved:
        print(f"# nothing to trim ({len(recs)} rows)")
        return 3
    arch_dir = Path(a.archive_dir) if a.archive_dir else state_root() / "archive"
    archive = arch_dir / (path.name[:-4] + ".archive.csv" if is_csv else path.name + ".archive")
    size_after = len(header or "") + sum(len(r) for r in recs[len(moved):])
    print(f"{path.name}: {len(recs)} rows, {st0.st_size} bytes -> keep newest {keep} rows (~{size_after} chars); "
          f"move {len(moved)} older rows to {archive}")
    if not a.apply:
        print("dry run: nothing changed; add --apply to do it")
        return 0
    st1 = path.stat()
    if (st1.st_size, st1.st_mtime_ns) != (st0.st_size, st0.st_mtime_ns):
        print("bigfile: file changed while reading; aborted, nothing modified", file=sys.stderr)
        return 2
    arch_dir.mkdir(parents=True, exist_ok=True)
    with open(archive, "a", newline="", encoding="utf-8", errors="surrogateescape") as af:
        if header and af.tell() == 0:
            af.write(header)
        af.writelines(moved)
        af.flush()
        os.fsync(af.fileno())
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(fd, "w", newline="", encoding="utf-8", errors="surrogateescape") as tf:
        tf.write(header or "")
        tf.writelines(recs[len(moved):])
        tf.flush()
        os.fsync(tf.fileno())
    os.chmod(tmp, st0.st_mode & 0o7777)
    st2 = path.stat()
    if (st2.st_size, st2.st_mtime_ns) != (st0.st_size, st0.st_mtime_ns):
        os.unlink(tmp)
        print("bigfile: file changed during trim; aborted (rows already appended to the archive are duplicates, harmless)", file=sys.stderr)
        return 2
    with locked(path) as st:
        os.replace(tmp, path)
        st["dropped"] += len(moved)
    print(f"done: {len(moved)} rows archived")
    return 0


def cmd_reset(a):
    with locked(a.file) as st:
        st["cursors"].pop(a.consumer, None)
    print(f"reset {a.consumer}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="action", required=True)

    def common(p, consumer=False):
        p.add_argument("file")
        if consumer:
            p.add_argument("--consumer", required=True)
        return p
    for name in ("new", "view"):
        p = common(sub.add_parser(name), consumer=(name == "new"))
        p.add_argument("--max-rows", type=int, default=200)
        p.add_argument("--cell-chars", type=int, default=200)
        p.add_argument("--cols")
        p.add_argument("--where", action="append", default=[])
        if name == "new":
            p.add_argument("--peek", action="store_true", help="do not move this consumer's place")
        else:
            p.add_argument("--tail", type=int, default=0)
    t = common(sub.add_parser("trim"))
    g = t.add_mutually_exclusive_group(required=True)
    g.add_argument("--keep-rows", type=int)
    g.add_argument("--keep-chars", type=int)
    t.add_argument("--archive-dir")
    t.add_argument("--apply", action="store_true")
    common(sub.add_parser("reset"), consumer=True)
    a = ap.parse_args()
    if not Path(a.file).is_file():
        print(f"bigfile: no such file: {a.file}", file=sys.stderr)
        return 2
    return {"new": cmd_new, "view": cmd_view, "trim": cmd_trim, "reset": cmd_reset}[a.action](a)


if __name__ == "__main__":
    sys.exit(main())
