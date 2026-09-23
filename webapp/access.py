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

from flask import abort, g, redirect, request, session, url_for

from .extensions import db
from .models import Course, CourseStaff, Offering, RosterEntry, User


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


# -- courses ---------------------------------------------------------------


def staff_role(user: User, course: Course) -> str | None:
    """'owner', 'instructor', or None when the user is not on the staff."""
    return db.session.scalar(
        db.select(CourseStaff.role).where(
            CourseStaff.course_id == course.id, CourseStaff.user_id == user.id
        )
    )


def staff_courses(user: User) -> list[Course]:
    return list(
        db.session.scalars(
            db.select(Course)
            .join(CourseStaff)
            .where(CourseStaff.user_id == user.id)
            .order_by(Course.code)
        )
    )


def course_staff_required(view):
    """For routes with <int:course_id>: sets g.course and g.staff_role, or
    404s. Not 403: people off the staff are not told the course exists."""

    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        course = db.session.get(Course, kwargs["course_id"])
        role = staff_role(g.user, course) if course else None
        if role is None:
            abort(404)
        g.course, g.staff_role = course, role
        return view(*args, **kwargs)

    return wrapped


def roster_entry(user: User, offering: Offering) -> RosterEntry | None:
    """The user's row on an offering's roster (not dropped), or None."""
    for e in offering.roster:
        if e.dropped_at is None and matches(user, e):
            return e
    return None


def matches(user: User, entry: RosterEntry) -> bool:
    """Is this roster row this person? By GitHub's numeric id when the row
    has one (it survives renames), otherwise by username."""
    if entry.github_user_id is not None:
        return entry.github_user_id == user.github_id
    return bool(entry.github_login) and entry.github_login.lower() == user.login.lower()


def student_entries(user: User) -> list[RosterEntry]:
    """Every roster row (not dropped) that is this person, newest offering
    first."""
    rows = db.session.scalars(
        db.select(RosterEntry)
        .join(Offering)
        .where(
            RosterEntry.dropped_at.is_(None),
            db.or_(
                RosterEntry.github_user_id == user.github_id,
                db.and_(
                    RosterEntry.github_user_id.is_(None),
                    db.func.lower(RosterEntry.github_login) == user.login.lower(),
                ),
            ),
        )
        .order_by(Offering.created_at.desc())
    )
    return list(rows)


def offering_member_required(view):
    """For routes with <int:offering_id> that students use: sets g.offering,
    g.course, g.staff_role (None for students) and g.entry (their roster
    row, or None for staff), or 404s."""

    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        offering = db.session.get(Offering, kwargs["offering_id"])
        if offering is None:
            abort(404)
        role = staff_role(g.user, offering.course)
        entry = roster_entry(g.user, offering)
        if role is None and entry is None:
            abort(404)
        g.offering, g.course, g.staff_role, g.entry = offering, offering.course, role, entry
        return view(*args, **kwargs)

    return wrapped


def offering_staff_required(view):
    """For routes with <int:offering_id>: sets g.offering, g.course and
    g.staff_role, or 404s. Roster members get their own check with the
    roster."""

    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        offering = db.session.get(Offering, kwargs["offering_id"])
        role = staff_role(g.user, offering.course) if offering else None
        if role is None:
            abort(404)
        g.offering, g.course, g.staff_role = offering, offering.course, role
        return view(*args, **kwargs)

    return wrapped
