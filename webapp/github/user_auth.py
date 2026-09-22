"""
user_auth.py, signing people in with GitHub (the App's OAuth web flow).
======================================================================

    1. authorize_url()  send the browser to GitHub with a random `state` and
                        a PKCE challenge
    2. GitHub sends it back to /auth/github/callback with a one-time `code`
    3. exchange_code()  trade the code (plus the PKCE verifier) for tokens

The result is a USER access token: it acts as that person, limited to what
both they and the App may do. It lives 8 hours; the refresh token (6 months)
gets a new one with refresh(). A GitHub App asks for no OAuth scopes: its
permissions, set on the App's settings page, are the scope.

Plain HTTP only. Storing tokens and users is webapp/auth.py's job.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from .app_auth import GitHubError

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"


@dataclass
class TokenSet:
    access_token: str
    access_expires_at: datetime | None
    refresh_token: str | None
    refresh_expires_at: datetime | None


def new_pkce() -> tuple[str, str]:
    """(verifier, challenge). GitHub accepts only the S256 method."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    query = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


def _token_request(fields: dict) -> TokenSet:
    now = datetime.now(UTC)
    try:
        resp = httpx.post(
            TOKEN_URL, data=fields, headers={"Accept": "application/json"}, timeout=30
        )
    except httpx.HTTPError as exc:
        raise GitHubError(f"could not reach GitHub to sign in: {exc}") from exc
    try:
        data = resp.json()
    except ValueError:
        raise GitHubError(f"GitHub's token endpoint returned {resp.status_code}") from None
    # Failures come back as 200 with an "error" field.
    if not resp.is_success or "error" in data or "access_token" not in data:
        reason = data.get("error_description") or data.get("error") or resp.status_code
        raise GitHubError(f"GitHub refused the sign-in: {reason}")

    def expiry(key: str) -> datetime | None:
        return now + timedelta(seconds=int(data[key])) if data.get(key) else None

    return TokenSet(
        access_token=data["access_token"],
        access_expires_at=expiry("expires_in"),
        refresh_token=data.get("refresh_token"),
        refresh_expires_at=expiry("refresh_token_expires_in"),
    )


def exchange_code(
    client_id: str, client_secret: str, code: str, verifier: str, redirect_uri: str
) -> TokenSet:
    return _token_request(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
        }
    )


def refresh(client_id: str, client_secret: str, refresh_token: str) -> TokenSet:
    return _token_request(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    )
