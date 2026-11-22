"""The only door to a model for orchestrator workflows. Every call, failed or not, writes one
usage line (orchestrator/usage.py). ``tests/test_rules.py`` fails if any other file under
orchestrator/ talks to a model endpoint directly.

Gemini reports its own counts in ``usageMetadata``: promptTokenCount (input),
candidatesTokenCount (visible output), thoughtsTokenCount (hidden thinking, billed as output),
cachedContentTokenCount (input served from cache). Logging reads them; it costs no extra call.
"""

from __future__ import annotations

import time
from typing import Any

from orchestrator import usage

GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _text(data: dict[str, Any]) -> str:
    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def gemini(http, api_key: str, model: str, prompt: str, *, workflow: str, step: str, json_mode: bool = False,
           max_output_tokens: int = 1200, temperature: float = 0.2) -> str:
    """One generateContent call. Raises whatever ``http`` raises; the usage line is written first."""
    config: dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_output_tokens}
    if json_mode:
        config["responseMimeType"] = "application/json"
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": config}
    started = time.monotonic()
    try:
        data = http.request("POST", GEMINI.format(model=model), headers={"x-goog-api-key": api_key},
                            json_body=body).json()
    except Exception as exc:
        usage.log_call(workflow, step, "gemini", model, ok=False, ms=int((time.monotonic() - started) * 1000),
                       note=str(exc)[:200])
        raise
    meta = data.get("usageMetadata") or {}
    usage.log_call(workflow, step, "gemini", model,
                   input_tokens=meta.get("promptTokenCount", 0), output_tokens=meta.get("candidatesTokenCount", 0),
                   cached=meta.get("cachedContentTokenCount", 0), reasoning=meta.get("thoughtsTokenCount", 0),
                   ms=int((time.monotonic() - started) * 1000))
    return _text(data)
