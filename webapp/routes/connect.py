"""
Connecting an offering to its GitHub org, through the App's installation.

    GET  /offerings/<id>/connect        off to GitHub's "install coursekit" page
    POST /offerings/<id>/installation   choose an org where it is already installed
    POST /offerings/<id>/disconnect     unlink the org (nothing changes on GitHub)
    GET  /github/installed              the App's Setup URL: GitHub sends people
                                        back here after installing

NEVER TRUST installation_id FROM THE ADDRESS BAR
    The Setup URL arrives with ?installation_id=N, and anyone can type any N.
    Before linking, link() confirms the person's own GitHub token can see
    that installation (GET /user/installations), which is GitHub's
    recommended check.

WHICH OFFERING
    The offering being connected travels to GitHub and back in a signed,
    one-hour `state` value, and is also remembered in the session, in case
    GitHub drops `state` (it does not pass it through every path).
"""

from __future__ import annotations

import logging

from flask import Blueprint, abort, current_app, flash, g, redirect, request, session, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .. import auth
from ..access import login_required, offering_staff_required, staff_role
from ..extensions import db
from ..github import api, installations
from ..github.app_auth import GitHubError
from ..models import Offering

log = logging.getLogger(__name__)

bp = Blueprint("connect", __name__)

STATE_MAX_AGE = 3600
SESSION_KEY = "connecting_offering"


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt="coursekit-install")


def installation_settings_url(inst) -> str:
    return f"https://github.com/organizations/{inst.account_login}/settings/installations/{inst.id}"


class LinkError(RuntimeError):
    pass


def link(offering: Offering, installation_id: int) -> list[str]:
    """Connect `offering` to an installation the signed-in person can see.
    Returns messages for the page. Raises LinkError if it cannot be done."""
    try:
        token = auth.user_access_token(g.user)
        mine = {i["id"]: i for i in api.user_installations(token)}
    except auth.NeedsSignIn as exc:
        raise LinkError("Please sign out and sign in again, then connect.") from exc
    except GitHubError as exc:
        raise LinkError(f"GitHub could not be asked about the installation: {exc}") from exc
    if installation_id not in mine:
        raise LinkError(
            "Your GitHub account can't see that installation of coursekit, "
            "so it can't be connected from here."
        )
    inst = installations.record(mine[installation_id])
    if inst.account_type != "Organization":
        db.session.commit()
        raise LinkError(
            f"coursekit is installed on the personal account {inst.account_login}. "
            "Each offering needs a GitHub organization."
        )
    offering.installation = inst
    db.session.commit()
    log.info("offering %s connected to %s", offering.id, inst.account_login)

    messages = [f"Connected to {inst.account_login}."]
    if inst.repository_selection != "all":
        messages.append(
            f"coursekit can only see selected repositories in {inst.account_login}. It needs "
            f"All repositories: change it at {installation_settings_url(inst)}"
        )
    others = [
        o
        for o in db.session.scalars(
            db.select(Offering).where(
                Offering.installation_id == inst.id, Offering.id != offering.id
            )
        )
    ]
    if others:
        names = ", ".join(f"{o.course.code} {o.label}" for o in others)
        messages.append(
            f"{inst.account_login} is also used by {names}. Each semester "
            "normally gets its own organization."
        )
    return messages


@bp.get("/offerings/<int:offering_id>/connect")
@offering_staff_required
def start(offering_id):
    session[SESSION_KEY] = offering_id
    state = _signer().dumps({"o": offering_id, "u": g.user.id})
    slug = current_app.config["GITHUB_APP_SLUG"]
    return redirect(f"https://github.com/apps/{slug}/installations/new?state={state}")


@bp.post("/offerings/<int:offering_id>/installation")
@offering_staff_required
def choose(offering_id):
    installation_id = request.form.get("installation_id", type=int)
    if not installation_id:
        abort(400)
    _link_and_report(g.offering, installation_id)
    return redirect(url_for("courses.offering", offering_id=offering_id))


@bp.post("/offerings/<int:offering_id>/disconnect")
@offering_staff_required
def disconnect(offering_id):
    org = g.offering.org_login
    g.offering.installation = None
    db.session.commit()
    if org:
        flash(
            f"Disconnected {org}. coursekit is still installed on it; uninstall it on GitHub "
            "if it's no longer needed."
        )
    return redirect(url_for("courses.offering", offering_id=offering_id))


@bp.get("/github/installed")
@login_required
def installed():
    offering = _offering_being_connected()
    back = (
        url_for("courses.offering", offering_id=offering.id) if offering else url_for("home.index")
    )

    if request.args.get("setup_action") == "request":
        flash(
            "An owner of that organization has to approve installing coursekit. Once they "
            "have, come back to the offering page and choose the organization from the list."
        )
        return redirect(back)

    installation_id = request.args.get("installation_id", type=int)
    if not installation_id:
        flash("GitHub didn't say which installation this was. Try connecting again.")
        return redirect(back)

    if offering is None:
        # Installed from GitHub directly, or the connection went stale.
        flash(
            "coursekit is installed. Open the offering it belongs to and choose the "
            "organization there."
        )
        return redirect(back)
    _link_and_report(offering, installation_id)
    return redirect(back)


def _offering_being_connected() -> Offering | None:
    remembered = session.pop(SESSION_KEY, None)
    offering_id = None
    state = request.args.get("state")
    if state:
        try:
            data = _signer().loads(state, max_age=STATE_MAX_AGE)
            if data.get("u") == g.user.id:
                offering_id = data.get("o")
        except BadSignature:
            log.warning("setup URL with a bad or expired state from %s", g.user.login)
    offering_id = offering_id or remembered
    offering = db.session.get(Offering, offering_id) if offering_id else None
    if offering is None or staff_role(g.user, offering.course) is None:
        return None
    return offering


def _link_and_report(offering: Offering, installation_id: int) -> None:
    try:
        for message in link(offering, installation_id):
            flash(message)
    except LinkError as exc:
        flash(str(exc))
