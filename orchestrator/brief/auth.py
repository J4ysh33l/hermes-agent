"""One-time logins, run by hand on the host (over SSH). Tokens go to $HERMES_HOME/brief/tokens/.

google:    paste-back OAuth flow (works without a browser on the host).
microsoft: device-code flow (open a URL on any device, type the code shown).
"""

from __future__ import annotations

import base64
import hashlib
import secrets as pysecrets
import time
import urllib.parse
from collections.abc import Callable

from .creds import Secrets
from .net import Http, HttpError
from .sources import gmail, outlook

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
REDIRECT = "http://localhost:8765/"


def google(http: Http, secrets: Secrets, ask: Callable[[str], str] = input, say: Callable[[str], None] = print) -> None:
    client_id, client_secret = secrets.get("GOOGLE_CLIENT_ID"), secrets.get("GOOGLE_CLIENT_SECRET")
    if not (client_id and client_secret):
        raise SystemExit("Put GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in $HERMES_HOME/.env first.")
    verifier = pysecrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {"client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code", "scope": gmail.SCOPE,
              "access_type": "offline", "prompt": "consent", "code_challenge": challenge,
              "code_challenge_method": "S256"}
    say("1. Open this link on your laptop or phone and allow read-only Gmail access:\n")
    say(GOOGLE_AUTH + "?" + urllib.parse.urlencode(params))
    say("\n2. The browser then fails to load a localhost page. That is expected.")
    pasted = ask("3. Paste the full address from the browser's address bar here: ").strip()
    code = (urllib.parse.parse_qs(urllib.parse.urlsplit(pasted).query).get("code") or [pasted])[0]
    form = {"client_id": client_id, "client_secret": client_secret, "code": code, "code_verifier": verifier,
            "grant_type": "authorization_code", "redirect_uri": REDIRECT}
    data = http.request("POST", gmail.TOKEN_URL, form=form).json()
    if not data.get("refresh_token"):
        raise SystemExit("Google returned no refresh token; run again (the link asks for consent each time).")
    secrets.save_token("google", {"refresh_token": data["refresh_token"], "saved_at": time.time()})
    say("Gmail login saved.")


def microsoft(http: Http, secrets: Secrets, say: Callable[[str], None] = print, sleep=time.sleep) -> None:
    client_id, tenant = secrets.get("MS_CLIENT_ID"), secrets.get("MS_TENANT_ID") or "organizations"
    if not client_id:
        raise SystemExit("Put MS_CLIENT_ID (and MS_TENANT_ID) in $HERMES_HOME/.env first.")
    base = outlook.LOGIN.format(tenant=tenant)
    start = http.request("POST", base + "/devicecode", form={"client_id": client_id, "scope": outlook.SCOPES}).json()
    say(start.get("message") or f"Open {start['verification_uri']} and enter {start['user_code']}")
    interval = int(start.get("interval", 5))
    deadline = time.time() + int(start.get("expires_in", 900))
    form = {"client_id": client_id, "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": start["device_code"]}
    while time.time() < deadline:
        sleep(interval)
        try:
            data = http.request("POST", base + "/token", form=form).json()
        except HttpError as exc:
            if "authorization_pending" in exc.detail:
                continue
            if "slow_down" in exc.detail:
                interval += 5
                continue
            raise SystemExit(f"Microsoft login failed: {exc}") from None
        secrets.save_token("microsoft", {"refresh_token": data["refresh_token"], "saved_at": time.time()})
        say("Outlook login saved.")
        return
    raise SystemExit("The code expired before it was used; run again.")
