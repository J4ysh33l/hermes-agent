"""One-time logins, run by hand on the host (over SSH). Tokens go to $HERMES_HOME/brief/tokens/.

Both use the paste-back flow (authorization code + PKCE, loopback redirect): open a link on any
device, sign in, then paste the address the browser lands on (a localhost page that fails to
load). Nothing listens on the host. The code in that address is useless without the PKCE
verifier, which never leaves this process.

Microsoft's device-code flow is not used: security defaults and Microsoft's managed Conditional
Access policy block it, and Google's device flow does not allow Gmail scopes.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets as pysecrets
import time
import urllib.parse
from collections.abc import Callable

from .creds import Secrets
from .net import Http, HttpError
from .sources import gmail, outlook

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
REDIRECT = "http://localhost:8765/"  # Google: Desktop client. Entra: "Mobile and desktop applications".


def _pkce() -> tuple[str, str]:
    verifier = pysecrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _paste_back(link: str, service: str, ask: Callable[[str], str], say: Callable[[str], None]) -> str:
    """Show the sign-in link, read back the address the browser landed on, return the code."""
    say(f"1. Open this link on your laptop or phone and sign in to {service}:\n")
    say(link)
    say("\n2. The browser then fails to load a localhost page. That is expected.")
    pasted = ask("3. Paste the full address from the browser's address bar here: ").strip()
    found = urllib.parse.parse_qs(urllib.parse.urlsplit(pasted).query)
    if "error" in found:
        detail = (found.get("error_description") or found["error"])[0]
        raise SystemExit(f"{service} sign-in failed: {detail}")
    return (found.get("code") or [pasted])[0]


def _exchange(http: Http, url: str, form: dict[str, str], service: str) -> dict:
    try:
        data = http.request("POST", url, form=form).json()
    except HttpError as exc:
        raise SystemExit(f"{service} sign-in failed: {exc.detail or exc}") from None
    if not data.get("refresh_token"):
        raise SystemExit(f"{service} returned no refresh token; run the login again.")
    return data


def google(http: Http, secrets: Secrets, ask: Callable[[str], str] = input, say: Callable[[str], None] = print,
           account: str = gmail.MAIN) -> None:
    """One login per Gmail account; ``account`` is your label for it (main, work, family...)."""
    if not re.fullmatch(r"[a-z0-9_-]{1,20}", account):
        raise SystemExit("Account label: up to 20 lowercase letters, digits, '-' or '_'.")
    client_id, client_secret = secrets.get("GOOGLE_CLIENT_ID"), secrets.get("GOOGLE_CLIENT_SECRET")
    if not (client_id and client_secret):
        raise SystemExit("Put GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in $HERMES_HOME/.env first.")
    verifier, challenge = _pkce()
    params = {"client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code", "scope": gmail.SCOPE,
              "access_type": "offline", "prompt": "select_account consent", "code_challenge": challenge,
              "code_challenge_method": "S256"}
    say(f"Signing in the Gmail account you call '{account}'. Use a private window so the right account is used.")
    code = _paste_back(GOOGLE_AUTH + "?" + urllib.parse.urlencode(params), "Google", ask, say)
    form = {"client_id": client_id, "client_secret": client_secret, "code": code, "code_verifier": verifier,
            "grant_type": "authorization_code", "redirect_uri": REDIRECT}
    data = _exchange(http, gmail.TOKEN_URL, form, "Google")
    email = gmail.address(http, data["access_token"])
    taken = [a.label for a in gmail.accounts(secrets.token_dir)
             if a.label != account and secrets.token(a.token_name).get("email") == email]
    if taken:
        raise SystemExit(f"{email} is already saved as '{taken[0]}'. Sign in with a different account.")
    secrets.save_token(gmail.token_name(account),
                       {"refresh_token": data["refresh_token"], "email": email, "saved_at": time.time()})
    say(f"Gmail login saved: {email} as '{account}'.")


def google_scoped(http: Http, secrets: Secrets, scope: str, ask: Callable[[str], str] = input,
                  say: Callable[[str], None] = print) -> dict:
    """A Google sign-in for one more scope (another workflow's login, e.g. the studio's Drive); returns
    the token response with its refresh token. Client id/secret are the Gmail ones."""
    client_id, client_secret = secrets.get("GOOGLE_CLIENT_ID"), secrets.get("GOOGLE_CLIENT_SECRET")
    if not (client_id and client_secret):
        raise SystemExit("Put GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in $HERMES_HOME/.env first.")
    verifier, challenge = _pkce()
    params = {"client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code", "scope": scope,
              "access_type": "offline", "prompt": "select_account consent", "code_challenge": challenge,
              "code_challenge_method": "S256"}
    code = _paste_back(GOOGLE_AUTH + "?" + urllib.parse.urlencode(params), "Google", ask, say)
    form = {"client_id": client_id, "client_secret": client_secret, "code": code, "code_verifier": verifier,
            "grant_type": "authorization_code", "redirect_uri": REDIRECT}
    return _exchange(http, gmail.TOKEN_URL, form, "Google")


def microsoft(http: Http, secrets: Secrets, ask: Callable[[str], str] = input,
              say: Callable[[str], None] = print) -> None:
    client_id, tenant = secrets.get("MS_CLIENT_ID"), secrets.get("MS_TENANT_ID") or "organizations"
    if not client_id:
        raise SystemExit("Put MS_CLIENT_ID (and MS_TENANT_ID) in $HERMES_HOME/.env first.")
    base = outlook.LOGIN.format(tenant=tenant)
    verifier, challenge = _pkce()
    params = {"client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code", "response_mode": "query",
              "scope": outlook.LOGIN_SCOPES, "prompt": "select_account", "code_challenge": challenge,
              "code_challenge_method": "S256"}
    code = _paste_back(base + "/authorize?" + urllib.parse.urlencode(params), "Microsoft", ask, say)
    form = {"client_id": client_id, "grant_type": "authorization_code", "code": code, "code_verifier": verifier,
            "redirect_uri": REDIRECT, "scope": outlook.LOGIN_SCOPES}
    data = _exchange(http, base + "/token", form, "Microsoft")
    secrets.save_token("microsoft", {"refresh_token": data["refresh_token"], "saved_at": time.time()})
    say("Outlook login saved.")
