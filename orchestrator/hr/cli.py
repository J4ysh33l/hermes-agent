"""``python -m orchestrator.hr <words>``: the /hr commands on the host, e.g.
``python -m orchestrator.hr payslip ~/nov.xlsx 01/11/2026 30/11/2026 02/12/2026``."""

from __future__ import annotations

import sys

from . import chat


def main(argv: list[str] | None = None) -> int:
    print(chat.handle(" ".join(sys.argv[1:] if argv is None else argv)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
