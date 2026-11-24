"""Minimal HTTP client (stdlib). Sources take an ``Http`` so tests can pass ``FakeHttp`` instead."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) morning-brief/1.0"
TIMEOUT = 20


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)  # lower-case names

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class HttpError(Exception):
    def __init__(self, status: int, url: str, detail: str = "") -> None:
        # Never keep the query string: it can carry keys.
        bare = urllib.parse.urlsplit(url)._replace(query="").geturl()
        super().__init__(f"HTTP {status} from {bare} {detail[:200]}".strip())
        self.status = status
        self.detail = detail


class Http(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        form: dict[str, str] | None = None,
        json_body: Any = None,
        data: bytes | None = None,
    ) -> Response: ...


def build_url(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    sep = "&" if "?" in url else "?"
    return url + sep + urllib.parse.urlencode(params, doseq=True)


class UrllibHttp:
    """Real network client. Raises HttpError for any non-2xx status. ``timeout``: seconds per request
    (uploads and long model calls need more than the default)."""

    def __init__(self, timeout: float = TIMEOUT) -> None:
        self.timeout = timeout

    def request(self, method, url, *, params=None, headers=None, form=None, json_body=None, data=None) -> Response:
        hdrs = {"User-Agent": USER_AGENT, "Accept": "*/*", **(headers or {})}
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        elif json_body is not None:
            data = json.dumps(json_body).encode()
            hdrs["Content-Type"] = "application/json"
        full = build_url(url, params)
        req = urllib.request.Request(full, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return Response(resp.status, resp.read(), {k.lower(): v for k, v in resp.headers.items()})
        except urllib.error.HTTPError as exc:
            raise HttpError(exc.code, full, exc.read().decode("utf-8", errors="replace")) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HttpError(0, full, str(getattr(exc, "reason", exc))) from None

    def save(self, url: str, dest: Path, *, headers: dict[str, str] | None = None) -> Path:
        """GET ``url`` straight to ``dest`` without holding it in memory (meeting recordings)."""
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp, dest.open("wb") as out:
                shutil.copyfileobj(resp, out, 1 << 20)
        except urllib.error.HTTPError as exc:
            raise HttpError(exc.code, url, exc.read().decode("utf-8", errors="replace")) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HttpError(0, url, str(getattr(exc, "reason", exc))) from None
        return dest
