"""
Signing in and out, and switching mode.

    GET  /login?as=student|instructor[&next=/path]   off to GitHub
    GET  /auth/github/callback                        back from GitHub
    POST /logout
    POST /account/mode                                switch student/instructor
"""

from __future__ import annotations

import logging
import secrets
import time
from urllib.parse import urlsplit

from flask import Blueprint, current_app, flash, g, redirect, request, session, url_for

from .. import auth
from ..access import login_required, may_use_instructor_mode, safe_next
from ..extensions import db
from ..github import user_auth
from ..github.app_auth import GitHubError
from ..models import MODES

log = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)

# Sign-ins started but not yet back from GitHub, keyed by `state`. Several
# may be in flight (two tabs, a double click); each keeps its own verifier.
PENDING_KEY = "oauth_pending"
PENDING_MAX = 5
PENDING_SECONDS = 600


def _redirect_uri() -> str:
    # Must match the App's Callback URL exactly.
    return f"{current_app.config['BASE_URL']}/auth/github/callback"


def _set_mode(user, wanted: str) -> None:
    if wanted == "instructor" and not may_use_instructor_mode(user):
        flash("Instructor mode is not available for this account.")
        wanted = "student"
    user.mode = wanted


@bp.get("/login")
def login():
    # GitHub returns to BASE_URL's host. The pending sign-in lives in this
    # host's cookie, so start on that host (localhost vs 127.0.0.1 are
    # different sites to a browser, and the cookie would not come back).
    base = current_app.config["BASE_URL"]
    if request.host != urlsplit(base).netloc:
        return redirect(base + request.full_path.rstrip("?"))

    mode = request.args.get("as", "student")
    if mode not in MODES:
        mode = "student"
    verifier, challenge = user_auth.new_pkce()
    state = secrets.token_urlsafe(32)
    now = time.time()
    pending = {
        k: v
        for k, v in session.get(PENDING_KEY, {}).items()
        if now - v["started"] < PENDING_SECONDS
    }
    pending[state] = {
        "verifier": verifier,
        "mode": mode,
        "next": safe_next(request.args.get("next")),
        "started": now,
    }
    session[PENDING_KEY] = dict(list(pending.items())[-PENDING_MAX:])
    return redirect(
        user_auth.authorize_url(
            current_app.config["GITHUB_APP_CLIENT_ID"], _redirect_uri(), state, challenge
        )
    )


@bp.get("/auth/github/callback")
def callback():
    state = request.args.get("state", "")
    in_flight = session.get(PENDING_KEY, {})
    pending = in_flight.pop(state, None)
    session[PENDING_KEY] = in_flight
    if pending and time.time() - pending["started"] >= PENDING_SECONDS:
        pending = None
    if request.args.get("error"):
        if request.args["error"] == "access_denied":
            flash("Sign-in was cancelled.")
        else:
            reason = request.args.get("error_description") or request.args["error"]
            flash(f"GitHub reported a problem: {reason}")
        return redirect(url_for("home.index"))

    if not pending:
        if g.user is not None:
            # Already signed in: a repeated callback (back button, restored
            # tab). Nothing to do and nothing worth alarming anyone over.
            log.info("ignored a repeated sign-in callback for %s", g.user.login)
            return redirect(url_for("home.index"))
        # A callback we did not start (or started over 10 minutes ago).
        flash("That sign-in didn't start here or has expired. Please sign in again.")
        return redirect(url_for("home.index"))
    code = request.args.get("code")
    if not code:
        flash("GitHub did not send a sign-in code. Please try again.")
        return redirect(url_for("home.index"))

    cfg = current_app.config
    try:
        tokens = user_auth.exchange_code(
            cfg["GITHUB_APP_CLIENT_ID"],
            cfg["GITHUB_APP_CLIENT_SECRET"],
            code,
            pending["verifier"],
            _redirect_uri(),
        )
        user = auth.sign_in(tokens)
    except GitHubError as exc:
        log.warning("sign-in failed: %s", exc)
        flash(f"Sign-in failed: {exc}")
        return redirect(url_for("home.index"))

    _set_mode(user, pending["mode"])
    db.session.commit()
    session.clear()
    session.permanent = True
    session["user_id"] = user.id
    log.info("%s signed in (%s mode)", user.login, user.mode)
    return redirect(pending.get("next") or url_for("home.index"))


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("home.index"))


@bp.post("/account/mode")
@login_required
def switch_mode():
    wanted = request.form.get("mode", "")
    if wanted in MODES:
        _set_mode(g.user, wanted)
        db.session.commit()
    return redirect(url_for("home.index"))
