"""
access.py, who is signed in, and what they may see.
===================================================

MODE IS A VIEW, NOT A PERMISSION
    A user's mode (student or instructor) chooses which home page and menus
    they see. It grants nothing on its own: every course page also checks the
    person's relationship to THAT course (staff, or on its roster), and those
    checks arrive with the course models. Instructor mode only unlocks
    creating a course. So a student who switches to instructor mode sees an
    empty course list, not anyone's grades.

    Whether someone may use instructor mode at all is decided in exactly one
    place, may_use_instructor_mode(), so it can be tightened before production
    without hunting (expansion/agent-spec/deploy.md, section 5).
"""

from __future__ import annotations

from functools import wraps

from flask import g, redirect, request, session, url_for

from .extensions import db
from .models import User


def may_use_instructor_mode(user: User) -> bool:
    # Self-selected for now (expansion/goals.md). Replace before production.
    return True


def load_current_user() -> None:
    """before_request: g.user is the signed-in User, or None."""
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        g.user = db.session.get(User, user_id)
        if g.user is None:  # deleted since they signed in
            session.clear()


def safe_next(target: str | None) -> str | None:
    """A post-sign-in destination, only if it is a path on this site. A full
    URL or a //host path would let a crafted link bounce people elsewhere."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("home.index", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def instructor_mode_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user.mode != "instructor":
            return redirect(url_for("home.index"))
        return view(*args, **kwargs)

    return wrapped
