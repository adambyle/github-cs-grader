"""
Signing in and out, and switching mode.

    GET  /login?as=student|instructor[&next=/path]   off to GitHub
    GET  /auth/github/callback                        back from GitHub
    POST /logout
    POST /account/mode                                switch student/instructor
"""

from __future__ import annotations

import hmac
import logging
import secrets

from flask import Blueprint, current_app, flash, g, redirect, request, session, url_for

from .. import auth
from ..access import login_required, may_use_instructor_mode, safe_next
from ..extensions import db
from ..github import user_auth
from ..github.app_auth import GitHubError
from ..models import MODES

log = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)


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
    mode = request.args.get("as", "student")
    if mode not in MODES:
        mode = "student"
    verifier, challenge = user_auth.new_pkce()
    state = secrets.token_urlsafe(32)
    session["oauth"] = {
        "state": state,
        "verifier": verifier,
        "mode": mode,
        "next": safe_next(request.args.get("next")),
    }
    return redirect(
        user_auth.authorize_url(
            current_app.config["GITHUB_APP_CLIENT_ID"], _redirect_uri(), state, challenge
        )
    )


@bp.get("/auth/github/callback")
def callback():
    pending = session.pop("oauth", None)
    if request.args.get("error"):
        if request.args["error"] == "access_denied":
            flash("Sign-in was cancelled.")
        else:
            reason = request.args.get("error_description") or request.args["error"]
            flash(f"GitHub reported a problem: {reason}")
        return redirect(url_for("home.index"))

    state = request.args.get("state", "")
    if not pending or not hmac.compare_digest(pending["state"], state):
        # A callback we did not start: an old tab, or a forged link.
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
