"""GET /healthz: the server is up and the database opens."""

from flask import Blueprint
from sqlalchemy import text

from ..extensions import db

bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    db.session.execute(text("SELECT 1"))
    return "ok\n", 200, {"Content-Type": "text/plain"}
