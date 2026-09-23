"""
auth.py, turning a GitHub sign-in into a coursekit user, and keeping their
token usable.
=========================================================================

The HTTP half lives in github/user_auth.py; the pages in routes/auth.py.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from flask import current_app

from . import crypto
from .extensions import db
from .github import api, user_auth
from .github.app_auth import GitHubError
from .models import RosterEntry, User, UserToken

log = logging.getLogger(__name__)

# Refresh a user token when less than this is left on it.
REFRESH_MARGIN = timedelta(minutes=5)


class NeedsSignIn(RuntimeError):
    """The stored token is gone, revoked or past refreshing: the person has
    to sign in again before coursekit can act as them."""


def _aware(when: datetime | None) -> datetime | None:
    # SQLite hands datetimes back without a timezone; they were stored in UTC.
    return when.replace(tzinfo=UTC) if when is not None and when.tzinfo is None else when


def sign_in(tokens: user_auth.TokenSet) -> User:
    """Create or update the User for whoever owns these tokens, and store
    the tokens. Found by GitHub's numeric id, so a renamed account is the
    same user with a new login."""
    profile = api.get_user(tokens.access_token)
    try:
        email = api.primary_email(tokens.access_token)
    except GitHubError as exc:
        # Not worth failing a sign-in over (e.g. the App lacks the Email
        # addresses permission); the roster CSV carries emails anyway.
        log.warning("could not read %s's email: %s", profile.get("login"), exc)
        email = None

    user = db.session.scalar(db.select(User).where(User.github_id == profile["id"]))
    if user is None:
        user = User(github_id=profile["id"])
        db.session.add(user)
    user.login = profile["login"]
    user.name = profile.get("name")
    user.avatar_url = profile.get("avatar_url")
    if email:
        user.email = email
    user.last_login_at = datetime.now(UTC)
    store_tokens(user, tokens)
    _claim_roster_rows(user)
    db.session.commit()
    return user


def _claim_roster_rows(user: User) -> None:
    """Roster rows naming this login whose account id isn't known yet (the
    lookup failed or was never made) get it now: signing in proves the
    login is theirs, and the id keeps matching after a rename."""
    rows = db.session.scalars(
        db.select(RosterEntry).where(
            RosterEntry.github_user_id.is_(None),
            db.func.lower(RosterEntry.github_login) == user.login.lower(),
        )
    )
    for row in rows:
        row.github_user_id = user.github_id
        row.github_login = user.login
        row.github_status = "ok"


def store_tokens(user: User, tokens: user_auth.TokenSet) -> None:
    if user.token is None:
        user.token = UserToken(access_token_enc="")
    t = user.token
    t.access_token_enc = crypto.encrypt(tokens.access_token)
    t.access_expires_at = tokens.access_expires_at
    if tokens.refresh_token:
        t.refresh_token_enc = crypto.encrypt(tokens.refresh_token)
        t.refresh_expires_at = tokens.refresh_expires_at


def user_access_token(user: User) -> str:
    """A usable access token for acting as this person, refreshed if it is
    close to expiring. Raises NeedsSignIn when that is impossible."""
    t = user.token
    if t is None:
        raise NeedsSignIn(f"{user.login} has no stored GitHub token")
    now = datetime.now(UTC)
    expires = _aware(t.access_expires_at)
    if expires is None or expires - now > REFRESH_MARGIN:
        return crypto.decrypt(t.access_token_enc)

    refresh_expires = _aware(t.refresh_expires_at)
    if not t.refresh_token_enc or (refresh_expires and refresh_expires <= now):
        raise NeedsSignIn(f"{user.login}'s GitHub sign-in has expired")
    cfg = current_app.config
    try:
        tokens = user_auth.refresh(
            cfg["GITHUB_APP_CLIENT_ID"],
            cfg["GITHUB_APP_CLIENT_SECRET"],
            crypto.decrypt(t.refresh_token_enc),
        )
    except GitHubError as exc:
        raise NeedsSignIn(f"could not refresh {user.login}'s GitHub sign-in: {exc}") from exc
    store_tokens(user, tokens)
    db.session.commit()
    return tokens.access_token
