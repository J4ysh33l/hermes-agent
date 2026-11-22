#!/usr/bin/env python3
"""capout.py - run a command and cap what it prints, so one tool result cannot blow the context budget.

Why: measured on Hermes (see hermes_config_snippet.yaml): no config setting caps a single tool result
below ~100K chars, and one 13k-token result pushed a request to 28k tokens (ceiling is 25k).
Run every command Hermes executes through this, or make the script itself print compactly.

Usage:  capout.py [--max-chars N] [--head N] -- COMMAND [ARGS...]
Default 3000 chars (~750-1000 tokens). When truncated, the full output is saved under
$AGENT_STATE_DIR/spill/ (default ~/.agent-state/spill/) and the path is printed, so nothing is lost.
Exit code is the command's own. No shell is used (argv list), no LLM, standard library only.
"""
import argparse, os, subprocess, sys, time, pathlib

def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--max-chars", type=int, default=3000)
    ap.add_argument("--head", type=int, default=0, help="chars kept from the start (default 70%% of max)")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    if not cmd:
        ap.error("no command given")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=int(os.environ.get("CAPOUT_TIMEOUT", "300")), check=False)
        out, rc = (p.stdout or "") + (("\n" + p.stderr) if p.stderr.strip() else ""), p.returncode
    except FileNotFoundError:
        print(f"capout: command not found: {cmd[0]}"); return 127
    except subprocess.TimeoutExpired:
        print("capout: command timed out"); return 124
    if len(out) <= a.max_chars:
        sys.stdout.write(out); return rc
    head = a.head or int(a.max_chars * 0.7); tail = max(0, a.max_chars - head)
    d = pathlib.Path(os.environ.get("AGENT_STATE_DIR", os.path.expanduser("~/.agent-state"))) / "spill"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{int(time.time())}-{os.getpid()}.txt"; f.write_text(out)
    sys.stdout.write(out[:head] + f"\n... [{len(out) - head - tail} chars cut; full output: {f}] ...\n" + (out[-tail:] if tail else ""))
    return rc

if __name__ == "__main__":
    sys.exit(main())
