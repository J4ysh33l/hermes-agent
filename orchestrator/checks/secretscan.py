#!/usr/bin/env python3
"""Refuse to push credentials. Standard library only.

Scans every file under orchestrator/, plus whatever else this fork adds or changes on top of
the pinned upstream (``git diff <base>...HEAD``, staged and untracked files), so upstream's own
test fixtures are not re-scanned on every push. Pass paths to scan exactly those instead.

Exit codes: 0 clean, 1 findings, 2 usage or git error.
A line that really must hold a matching string carries ``secretscan: allow`` with a reason.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE = "origin/main"
OWN_TREE = "orchestrator"  # always scanned in full, not only its changes
ALLOW_MARK = "secretscan: allow"
MAX_BYTES = 2_000_000


PLACEHOLDER = re.compile(r"(?i)path/to|your[-_]|example|placeholder|changeme|dummy|fake|x{8,}|<[^>]+>|\$\{?\w")


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    skip_placeholders: bool = False

    def matches(self, line: str) -> bool:
        return any(
            not (self.skip_placeholders and PLACEHOLDER.search(m.group(0))) for m in self.pattern.finditer(line)
        )


RULES: tuple[Rule, ...] = (
    Rule("telegram bot token", re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b")),
    Rule("google api key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    Rule("google oauth client secret", re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{20,}")),
    Rule("google oauth refresh token", re.compile(r"\b1//0[A-Za-z0-9_-]{30,}")),
    Rule("slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    Rule("slack webhook", re.compile(r"hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+")),
    Rule("aws access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    Rule("github token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})")),
    Rule("anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    Rule("openai-style key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
    Rule("private key block", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    Rule("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    Rule(
        "assigned secret",
        re.compile(
            r"(?i)\b(?:secret|token|api[_-]?key|passw(?:or)?d|client[_-]?secret)\w*\s*[:=]\s*"
            r"['\"]?[A-Za-z0-9_\-+/=.]{24,}"
        ),
        skip_placeholders=True,
    ),
)

BLOCKED_NAMES = re.compile(
    r"(?:^|/)(?:\.env(?:\.[\w-]+)?|credentials\.json|token\.json|client_secret[\w.-]*\.json|"
    r"[\w.-]+\.(?:pem|p12|pfx|key)|id_(?:rsa|ed25519|ecdsa))$"
)
SAFE_ENV_NAMES = re.compile(r"\.env\.(?:example|sample|template)$")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str

    def render(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: {self.rule}"


def _git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def changed_files(base: str) -> list[str]:
    names = set(_git("diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"))
    names.update(_git("diff", "--name-only", "--diff-filter=ACMR", "--cached"))
    names.update(_git("diff", "--name-only", "--diff-filter=ACMR"))
    names.update(_git("ls-files", "--others", "--exclude-standard"))
    names.update(_git("ls-files", "--", OWN_TREE))
    return sorted(names)


def scan_text(path: str, text: str) -> list[Finding]:
    found: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARK in line:
            continue
        found.extend(Finding(path, number, rule.name) for rule in RULES if rule.matches(line))
    return found


def scan_path(path: str) -> list[Finding]:
    if BLOCKED_NAMES.search(path) and not SAFE_ENV_NAMES.search(path):
        return [Finding(path, 0, "file name looks like a credential file")]
    file = Path(path)
    if not file.is_file() or file.stat().st_size > MAX_BYTES:
        return []
    data = file.read_bytes()
    if b"\0" in data[:4096]:
        return []
    return scan_text(path, data.decode("utf-8", errors="replace"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="scan these files instead of the fork's changes")
    parser.add_argument("--base", default=DEFAULT_BASE, help=f"upstream ref to diff against (default {DEFAULT_BASE})")
    args = parser.parse_args(argv)
    try:
        paths = args.paths or changed_files(args.base)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"secretscan: cannot list changed files: {exc}", file=sys.stderr)
        return 2
    findings = [finding for path in paths for finding in scan_path(path)]
    for finding in findings:
        print(finding.render())
    print(f"secretscan: {len(paths)} files, {len(findings)} findings", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
