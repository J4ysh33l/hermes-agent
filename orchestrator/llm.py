"""The only door to a model for orchestrator workflows. Every call, failed or not, writes one
usage line (orchestrator/usage.py). ``tests/test_rules.py`` fails if any other file under
orchestrator/ talks to a model endpoint directly.

Gemini reports its own counts in ``usageMetadata``: promptTokenCount (input),
candidatesTokenCount (visible output), thoughtsTokenCount (hidden thinking, billed as output),
cachedContentTokenCount (input served from cache). Logging reads them; it costs no extra call.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

from orchestrator import usage

GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
CLAUDE = "https://api.anthropic.com/v1/messages"
CLAUDE_VERSION = "2026-10-21"
CLAUDE_FALLBACK = "server-side-fallback-2026-07-01"  # a declined request is re-run on a fallback model
API = "https://generativelanguage.googleapis.com"
FILE_WAIT = 2.0  # seconds between checks while Gemini prepares an uploaded file
FILE_TRIES = 90


def _text(data: dict[str, Any]) -> str:
    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def gemini(http, api_key: str, model: str, prompt: str, *, workflow: str, step: str, json_mode: bool = False,
           max_output_tokens: int = 1200, temperature: float = 0.2, schema: dict[str, Any] | None = None,
           files: tuple[tuple[str, str], ...] = ()) -> str:
    """One generateContent call. Raises whatever ``http`` raises; the usage line is written first.
    ``schema`` (JSON mode only) makes the API enforce the answer's shape, e.g. an ``enum`` of allowed ids.
    ``files``: (mime type, file uri) pairs from ``upload``, sent before the prompt (audio, documents)."""
    config: dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_output_tokens}
    if json_mode:
        config["responseMimeType"] = "application/json"
        if schema:
            config["responseSchema"] = schema
    parts = [{"file_data": {"mime_type": mime, "file_uri": uri}} for mime, uri in files] + [{"text": prompt}]
    body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
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


def claude(http, api_key: str, model: str, prompt: str, *, workflow: str, step: str, max_tokens: int = 16000,
           effort: str = "medium", images: tuple[bytes, ...] = ()) -> str:
    """One Messages API call (raw HTTP, like ``gemini``, so it is logged and faked the same way).
    Thinking is on by default on current Claude models; ``effort`` sets how much (low … max). No sampling
    parameters: API version 2026-10-21 refuses them. Raises ValueError on a refusal or a cut-off answer.
    ``images``: PNGs shown before the prompt (e.g. frames of a render to review)."""
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                            "data": base64.b64encode(png).decode("ascii")}} for png in images]
    body = {"model": model, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": [*content, {"type": "text", "text": prompt}]}],
            "output_config": {"effort": effort}, "fallbacks": "default"}
    headers = {"x-api-key": api_key, "anthropic-version": CLAUDE_VERSION, "anthropic-beta": CLAUDE_FALLBACK}
    started = time.monotonic()
    try:
        data = http.request("POST", CLAUDE, headers=headers, json_body=body).json()
    except Exception as exc:
        usage.log_call(workflow, step, "anthropic", model, ok=False, ms=int((time.monotonic() - started) * 1000),
                       note=str(exc)[:200])
        raise
    meta = data.get("usage") or {}
    usage.log_call(workflow, step, "anthropic", model, input_tokens=meta.get("input_tokens", 0),
                   output_tokens=meta.get("output_tokens", 0), cached=meta.get("cache_read_input_tokens", 0),
                   ms=int((time.monotonic() - started) * 1000))
    stop = data.get("stop_reason")
    if stop == "refusal":
        why = (data.get("stop_details") or {}).get("explanation") or "no reason given"
        raise ValueError(f"Claude declined: {why}")
    if stop == "max_tokens":
        raise ValueError(f"Claude ran out of room ({max_tokens} tokens) before finishing")
    return "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")


# ---- Gemini Files API: large inputs (meeting audio) are uploaded, referenced, then deleted ----------
# Uploading costs no tokens; the tokens are counted (and logged) by the gemini() call that uses the file.


def upload(http, api_key: str, path: Path, mime: str) -> dict[str, Any]:
    """Resumable upload (the documented way for large files); returns the file resource
    (``name``, ``uri``, ``state``)."""
    data = path.read_bytes()
    start = http.request("POST", f"{API}/upload/v1beta/files", json_body={"file": {"display_name": path.name}},
                         headers={"x-goog-api-key": api_key, "X-Goog-Upload-Protocol": "resumable",
                                  "X-Goog-Upload-Command": "start",
                                  "X-Goog-Upload-Header-Content-Length": str(len(data)),
                                  "X-Goog-Upload-Header-Content-Type": mime})
    target = start.headers.get("x-goog-upload-url")
    if not target:
        raise ValueError("Gemini did not return an upload address")
    done = http.request("POST", target, data=data,
                        headers={"X-Goog-Upload-Command": "upload, finalize", "X-Goog-Upload-Offset": "0",
                                 "Content-Length": str(len(data))})
    return done.json()["file"]


def wait_active(http, api_key: str, name: str, sleep=time.sleep) -> dict[str, Any]:
    """Gemini prepares audio before it can be used; wait until its state is ACTIVE."""
    for _ in range(FILE_TRIES):
        found = http.request("GET", f"{API}/v1beta/{name}", headers={"x-goog-api-key": api_key}).json()
        if found.get("state") == "ACTIVE":
            return found
        if found.get("state") == "FAILED":
            raise ValueError(f"Gemini could not read {name}")
        sleep(FILE_WAIT)
    raise ValueError(f"Gemini took too long to prepare {name}")


def delete(http, api_key: str, name: str) -> None:
    http.request("DELETE", f"{API}/v1beta/{name}", headers={"x-goog-api-key": api_key})
