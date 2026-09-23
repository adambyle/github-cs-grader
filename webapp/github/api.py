"""
api.py, named GitHub operations, one function per REST call.
============================================================

The web-app counterpart of the CLI's coursekit/ghcli.py. Each function takes
the token to act with: a user access token (acting as the signed-in person)
or an installation token (acting as the App inside one org). Which kind a
call needs is noted on each function; GitHub's table is "Permissions
required for GitHub Apps" in its REST docs.
"""

from __future__ import annotations

import httpx

from .app_auth import API, HEADERS, GitHubError, _json_or_raise


def _get(token: str, path: str):
    try:
        resp = httpx.get(
            f"{API}{path}", headers={**HEADERS, "Authorization": f"Bearer {token}"}, timeout=30
        )
    except httpx.HTTPError as exc:
        raise GitHubError(f"could not reach GitHub: {exc}") from exc
    return _json_or_raise(resp)


def _get_all(token: str, path: str, key: str | None = None) -> list:
    """Every page of a list endpoint, following GitHub's Link headers. `key`
    names the list inside the response when it is wrapped in an object."""
    url = f"{API}{path}{'&' if '?' in path else '?'}per_page=100"
    items: list = []
    while url:
        try:
            resp = httpx.get(
                url, headers={**HEADERS, "Authorization": f"Bearer {token}"}, timeout=30
            )
        except httpx.HTTPError as exc:
            raise GitHubError(f"could not reach GitHub: {exc}") from exc
        data = _json_or_raise(resp)
        items.extend(data[key] if key else data)
        url = resp.links.get("next", {}).get("url")
    return items


def get_user(user_token: str) -> dict:
    """The signed-in person: id, login, name, avatar_url. [user token]"""
    return _get(user_token, "/user")


def primary_email(user_token: str) -> str | None:
    """Their primary verified email, or None. Needs the App's "Email
    addresses: read" account permission. [user token]"""
    for entry in _get(user_token, "/user/emails"):
        if entry.get("primary") and entry.get("verified"):
            return entry.get("email")
    return None


def user_installations(user_token: str) -> list[dict]:
    """The App's installations this person can access (for an org: they can
    administer it, or it was installed on repositories they can reach).
    GitHub's recommended way to check a setup-URL installation_id really
    belongs to the person who arrived with it. [user token]"""
    return _get_all(user_token, "/user/installations", key="installations")


def lookup_user(token: str, login: str) -> dict | None:
    """A GitHub account by username: {"id", "login"} with GitHub's
    capitalization, or None if there's no such account. Public data, so any
    token will do; the roster uses the instructor's. [user token]"""
    try:
        resp = httpx.get(
            f"{API}/users/{login}",
            headers={**HEADERS, "Authorization": f"Bearer {token}"},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise GitHubError(f"could not reach GitHub: {exc}") from exc
    if resp.status_code == 404:
        return None
    data = _json_or_raise(resp)
    return {"id": data["id"], "login": data["login"]}
