"""
app_auth.py, acting as the GitHub App.
======================================

Two kinds of credential, both minted from the App's private key:

    App JWT              proves "I am this App". Lives at most ten minutes.
                         Only good for /app/... endpoints, such as listing
                         the organizations that installed the App.
    installation token   acts inside ONE organization that installed the App,
                         with the App's permissions. Lives an hour. Used for
                         everything else: repositories, members, contents.

Installation tokens are cached and replaced five minutes before they expire,
so a burst of calls (a whole class being assigned) mints one token, not
thirty.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

import httpx
import jwt
from flask import current_app

API = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "coursekit",
}
REFRESH_MARGIN = 300  # seconds before expiry at which a cached token is replaced


class GitHubError(RuntimeError):
    pass


def app_jwt(app_id: str, private_key_pem: str, now: float | None = None) -> str:
    now = int(time.time() if now is None else now)
    # iat is backdated a minute to allow for clock drift, as GitHub advises.
    # iss is the App ID (as a string; PyJWT insists). GitHub's docs allow the
    # client ID too, but the App ID is the form every GitHub endpoint accepts.
    claims = {"iat": now - 60, "exp": now + 540, "iss": str(app_id)}
    return jwt.encode(claims, private_key_pem, algorithm="RS256")


class GitHubApp:
    def __init__(self, app_id: str, private_key_pem: str, http: httpx.Client | None = None):
        self.app_id = app_id
        self._key = private_key_pem
        self._http = http or httpx.Client(base_url=API, headers=HEADERS, timeout=30)
        self._tokens: dict[int, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def _app_get(self, path: str):
        resp = self._http.get(
            path, headers={"Authorization": f"Bearer {app_jwt(self.app_id, self._key)}"}
        )
        return _json_or_raise(resp)

    def installations(self) -> list[dict]:
        """Every organization or account that has installed the App."""
        return self._app_get("/app/installations?per_page=100")

    def installation_token(self, installation_id: int) -> str:
        with self._lock:
            cached = self._tokens.get(installation_id)
            if cached and cached[1] - REFRESH_MARGIN > time.time():
                return cached[0]
            resp = self._http.post(
                f"/app/installations/{installation_id}/access_tokens",
                headers={"Authorization": f"Bearer {app_jwt(self.app_id, self._key)}"},
            )
            data = _json_or_raise(resp)
            expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
            self._tokens[installation_id] = (data["token"], expires.timestamp())
            return data["token"]

    def installation_get(self, installation_id: int, path: str):
        """GET an API path acting as the given installation."""
        token = self.installation_token(installation_id)
        resp = self._http.get(path, headers={"Authorization": f"Bearer {token}"})
        return _json_or_raise(resp)


def _json_or_raise(resp: httpx.Response):
    if resp.is_success:
        return resp.json()
    try:
        message = resp.json().get("message", resp.text)
    except ValueError:
        message = resp.text
    raise GitHubError(
        f"GitHub {resp.request.method} {resp.request.url.path} "
        f"returned {resp.status_code}: {message}"
    )


def github_app() -> GitHubApp:
    """The App for the current Flask app, built on first use."""
    app = current_app._get_current_object()
    if "github_app" not in app.extensions:
        with open(app.config["GITHUB_APP_PRIVATE_KEY_PATH"], encoding="utf-8") as fh:
            key = fh.read()
        app.extensions["github_app"] = GitHubApp(app.config["GITHUB_APP_ID"], key)
    return app.extensions["github_app"]
