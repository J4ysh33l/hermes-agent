"""Rules every workflow follows (see orchestrator/README.md). These read source files on purpose:
the rule is about where code lives, not about behaviour."""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCH = ROOT / "orchestrator"
sys.path.insert(0, str(ROOT))

# Endpoints that run a model and bill tokens. Listing models is not a model call.
MODEL_ENDPOINTS = re.compile(r":generateContent|:streamGenerateContent|chat/completions|/v1/messages\b|/v1/responses\b")


class Rules(unittest.TestCase):
    def test_every_model_call_goes_through_the_logged_client(self):
        offenders = []
        for path in ORCH.rglob("*.py"):
            if path.name == "llm.py" or "tests" in path.parts:
                continue
            if MODEL_ENDPOINTS.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], "call orchestrator.llm instead so the call is logged")


if __name__ == "__main__":
    unittest.main()
