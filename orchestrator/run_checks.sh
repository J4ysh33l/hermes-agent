#!/usr/bin/env bash
# Run before every push: all orchestrator tests, then the secret scan over the fork's changes.
# Usage: orchestrator/run_checks.sh [--base <upstream ref>]   (default base: origin/main)
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$ROOT"

status=0
for test in $(git ls-files --cached --others --exclude-standard 'orchestrator/**/test_*.py' 'orchestrator/test_*.py'); do
    echo "== $test"
    if out="$(cd "$(dirname "$test")" && python3 "$(basename "$test")" 2>&1)"; then
        printf '%s\n' "$out" | tail -n 3
    else
        printf '%s\n' "$out" | tail -n 40
        echo "FAILED: $test"
        status=1
    fi
done

echo "== secret scan"
python3 orchestrator/checks/secretscan.py "$@" || status=1

find orchestrator -name __pycache__ -type d -prune -exec rm -rf {} +
[ "$status" -eq 0 ] && echo "ALL CHECKS PASSED" || echo "CHECKS FAILED"
exit "$status"
