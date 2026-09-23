"""
The student's side of an offering. Plan: github-integration.md section 6.5.

    GET  /offerings/<o>          (courses.offering hands students to offering_page())
    POST /offerings/<o>/join     accept the org invitation with the student's own token

A student sees an offering when a roster row (not dropped) is their GitHub
account (access.matches). Staff who are also on the roster see this page in
student mode.
"""

from __future__ import annotations

import logging

from flask import Blueprint, flash, g, redirect, render_template, url_for

from .. import auth, membership
from ..access import offering_member_required
from ..extensions import db
from ..github import api
from ..github.app_auth import GitHubError

log = logging.getLogger(__name__)

bp = Blueprint("student", __name__)


def refresh_membership(entry) -> None:
    """Re-read a student's own membership unless they're already a member,
    so accepting the invitation by email shows up at once. One call."""
    if entry.membership == "active" or entry.github_status != "ok":
        return
    try:
        token, org = membership.org_token(entry.offering)
        state = api.membership_state(token, org, entry.github_login)
    except (GitHubError, membership.NotConnected) as exc:
        log.info("couldn't refresh %s's membership: %s", entry.username, exc)
        return
    new = membership.STATE_FROM_GITHUB[state]
    if new != entry.membership and not (new == "none" and entry.membership == "queued"):
        membership.set_state(entry, new)
        db.session.commit()


def offering_page():
    refresh_membership(g.entry)
    inst = g.offering.installation
    return render_template(
        "offering_student.html",
        offering=g.offering,
        course=g.course,
        entry=g.entry,
        org=inst.account_login if inst and inst.state == "connected" else None,
    )


@bp.post("/offerings/<int:offering_id>/join")
@offering_member_required
def join(offering_id):
    back = redirect(url_for("courses.offering", offering_id=offering_id))
    entry = g.entry
    inst = g.offering.installation
    if entry is None or inst is None or inst.state != "connected":
        return back
    org = inst.account_login
    try:
        state = api.accept_membership(auth.user_access_token(g.user), org)
    except auth.NeedsSignIn:
        flash("Sign out and in again, then try Join once more.")
        return back
    except GitHubError as exc:
        log.info("%s couldn't join %s: %s", g.user.login, org, exc)
        flash(
            "GitHub didn't accept the invitation from here. Accept it on GitHub instead, "
            "with the link below."
        )
        return back
    membership.set_state(entry, membership.STATE_FROM_GITHUB.get(state, "active"))
    db.session.commit()
    flash(f"You're now a member of {org}.")
    return back
