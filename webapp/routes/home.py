"""GET /: sign-in buttons when signed out, otherwise the home page for the
user's mode. The lists fill in as courses and rosters arrive."""

from flask import Blueprint, g, render_template, request

from ..access import safe_next

bp = Blueprint("home", __name__)


@bp.get("/")
def index():
    if g.user is None:
        return render_template("landing.html", next=safe_next(request.args.get("next")))
    if g.user.mode == "instructor":
        return render_template("home_instructor.html")
    return render_template("home_student.html")
