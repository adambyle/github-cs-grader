"""
Courses and their offerings (semesters).

    GET  /courses/new                         form (instructor mode)
    POST /courses                             create; the creator becomes owner
    GET  /courses/<id>                        offerings and staff (staff only)
    POST /courses/<id>/offerings              add a semester
    POST /courses/<id>/staff                  add a co-instructor (owner only)
    POST /courses/<id>/staff/<user>/remove    remove someone else from the staff (owner only)
    GET  /offerings/<id>                      the offering page (staff only, for now)
    POST /offerings/<id>/delete               delete a semester (owner only)
"""

from __future__ import annotations

import logging

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import auth, membership
from ..access import (
    course_staff_required,
    instructor_mode_required,
    offering_staff_required,
    staff_role,
)
from ..extensions import db
from ..github import api, installations
from ..github.app_auth import GitHubError
from ..models import Course, CourseStaff, Offering, User
from . import roster

log = logging.getLogger(__name__)

bp = Blueprint("courses", __name__)


@bp.get("/courses/new")
@instructor_mode_required
def new_course():
    return render_template("course_new.html", form={})


@bp.post("/courses")
@instructor_mode_required
def create_course():
    form = {k: request.form.get(k, "").strip() for k in ("code", "title")}
    errors = []
    if not form["code"]:
        errors.append("A course code is required, e.g. CS 112.")
    if not form["title"]:
        errors.append("A title is required.")
    if errors:
        for e in errors:
            flash(e)
        return render_template("course_new.html", form=form), 400
    course = Course(code=form["code"], title=form["title"], created_by_id=g.user.id)
    course.staff.append(CourseStaff(user_id=g.user.id, role="owner"))
    db.session.add(course)
    db.session.commit()
    return redirect(url_for("courses.course", course_id=course.id))


@bp.get("/courses/<int:course_id>")
@course_staff_required
def course(course_id):
    return render_template("course.html", course=g.course)


@bp.post("/courses/<int:course_id>/offerings")
@course_staff_required
def create_offering(course_id):
    label = request.form.get("label", "").strip()
    if not label:
        flash("Name the semester, e.g. Fall 2026.")
        return redirect(url_for("courses.course", course_id=course_id))
    if any(o.label.lower() == label.lower() for o in g.course.offerings):
        flash(f"{g.course.code} already has an offering called {label}.")
        return redirect(url_for("courses.course", course_id=course_id))
    offering = Offering(course=g.course, label=label)
    db.session.add(offering)
    db.session.commit()
    return redirect(url_for("courses.offering", offering_id=offering.id))


@bp.post("/courses/<int:course_id>/staff")
@course_staff_required
def add_staff(course_id):
    if g.staff_role != "owner":
        abort(403)
    login = request.form.get("login", "").strip().lstrip("@")
    user = db.session.scalar(db.select(User).where(db.func.lower(User.login) == login.lower()))
    if user is None:
        flash(
            f"No one has signed in to coursekit as {login} yet. Ask them to sign in once, "
            "then add them."
        )
    elif staff_role(user, g.course):
        flash(f"{user.login} is already on the staff.")
    else:
        g.course.staff.append(CourseStaff(user_id=user.id, role="instructor"))
        db.session.commit()
        flash(f"{user.login} can now manage {g.course.code}.")
    return redirect(url_for("courses.course", course_id=course_id))


@bp.post("/courses/<int:course_id>/staff/<int:user_id>/remove")
@course_staff_required
def remove_staff(course_id, user_id):
    if g.staff_role != "owner":
        abort(403)
    if user_id == g.user.id:
        flash("You can't remove yourself from the staff.")
        return redirect(url_for("courses.course", course_id=course_id))
    member = db.session.scalar(
        db.select(CourseStaff).where(
            CourseStaff.course_id == course_id, CourseStaff.user_id == user_id
        )
    )
    if member is not None:
        login = member.user.login
        db.session.delete(member)
        db.session.commit()
        flash(f"{login} can no longer manage {g.course.code}.")
    return redirect(url_for("courses.course", course_id=course_id))


@bp.get("/offerings/<int:offering_id>")
@offering_staff_required
def offering(offering_id):
    choices, choices_error = [], None
    if g.offering.installation is None or g.offering.installation.state == "removed":
        choices, choices_error = _installable_orgs()
    return render_template(
        "offering.html",
        offering=g.offering,
        course=g.course,
        choices=choices,
        choices_error=choices_error,
        roster_counts=roster.counts(g.offering),
        members=membership.summary(g.offering),
    )


@bp.post("/offerings/<int:offering_id>/delete")
@offering_staff_required
def delete_offering(offering_id):
    if g.staff_role != "owner":
        abort(403)
    label, course_id = g.offering.label, g.course.id
    db.session.delete(g.offering)
    db.session.commit()
    flash(f"Deleted {g.course.code} {label}. Nothing on GitHub was changed.")
    return redirect(url_for("courses.course", course_id=course_id))


def _installable_orgs():
    """Orgs where the App is installed and the signed-in person can see the
    installation: the "choose an existing one" list. (installations, error)."""
    try:
        token = auth.user_access_token(g.user)
        found = [
            installations.record(data)
            for data in api.user_installations(token)
            if (data.get("account") or {}).get("type") == "Organization"
        ]
        db.session.commit()
        return found, None
    except auth.NeedsSignIn:
        return [], "sign-in"
    except GitHubError as exc:
        log.warning("could not list %s's installations: %s", g.user.login, exc)
        return [], str(exc)
