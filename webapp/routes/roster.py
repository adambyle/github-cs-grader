"""
An offering's roster: uploading the CLI's CSV (preview, then apply) and
editing single rows. Staff only. Plan: expansion/agent-spec/roster.md.

    GET  /offerings/<o>/roster                          the list (?show=attention|dropped|all)
    POST /offerings/<o>/roster/uploads                  upload a CSV; makes a preview
    GET  /offerings/<o>/roster/uploads/<u>              the preview
    POST /offerings/<o>/roster/uploads/<u>/apply        apply it
    POST /offerings/<o>/roster/uploads/<u>/cancel       discard it
    GET  /offerings/<o>/roster/new                      add one person (form)
    POST /offerings/<o>/roster/entries                  add one person
    GET  /offerings/<o>/roster/entries/<e>/edit         edit one person (form)
    POST /offerings/<o>/roster/entries/<e>              save the edit
    POST /offerings/<o>/roster/entries/<e>/drop         mark dropped
    POST /offerings/<o>/roster/entries/<e>/restore      unmark
    GET  /offerings/<o>/roster.csv                      the roster, in the upload format
    GET  /offerings/<o>/roster/blank.csv                just the header row

Nothing here writes to GitHub. It only looks up whether GitHub usernames
exist, with the instructor's own token.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from .. import auth
from .. import roster as rostermod
from ..access import offering_staff_required
from ..extensions import db
from ..github import api
from ..github.app_auth import GitHubError
from ..models import RosterEntry, RosterUpload

log = logging.getLogger(__name__)

bp = Blueprint("roster", __name__)

LOOKUP_THREADS = 8
FIELD_LABELS = {
    "first_name": "First name",
    "last_name": "Last name",
    "email": "Email",
    "section": "Section",
    "github_login": "GitHub",
    "role": "Role",
}


# -- GitHub lookups -----------------------------------------------------------


def check_logins(logins: list[str]) -> tuple[dict, str | None]:
    """Look up GitHub usernames with the signed-in person's token, 8 at a
    time. Returns ({lowercased login: {"id", "login"} or None}, error). On an
    error the results are empty: the rows are saved as unchecked."""
    if not logins:
        return {}, None
    try:
        token = auth.user_access_token(g.user)
    except auth.NeedsSignIn:
        return {}, "your GitHub sign-in has expired; sign out and in again to check them"
    try:
        with ThreadPoolExecutor(max_workers=LOOKUP_THREADS) as pool:
            found = list(pool.map(lambda login: api.lookup_user(token, login), logins))
    except GitHubError as exc:
        log.warning("GitHub username lookups failed: %s", exc)
        return {}, str(exc)
    return {login.lower(): result for login, result in zip(logins, found, strict=True)}, None


def set_github(entry: RosterEntry, login: str, lookups: dict) -> None:
    """Store a GitHub username on an entry, with what the lookup found."""
    entry.github_login = login
    entry.github_user_id = None
    if not login:
        entry.github_status = "missing"
    elif login.lower() not in lookups:
        entry.github_status = "unchecked"
    elif lookups[login.lower()] is None:
        entry.github_status = "not_found"
    else:
        entry.github_status = "ok"
        entry.github_login = lookups[login.lower()]["login"]
        entry.github_user_id = lookups[login.lower()]["id"]


# -- the list ------------------------------------------------------------------


def _entries(offering) -> list[RosterEntry]:
    return sorted(offering.roster, key=rostermod.sort_key)


def _bump(offering) -> None:
    offering.roster_revision = (offering.roster_revision or 0) + 1


@bp.get("/offerings/<int:offering_id>/roster")
@offering_staff_required
def page(offering_id):
    show = request.args.get("show", "")
    entries = _entries(g.offering)
    if show == "attention":
        shown = [e for e in entries if e.needs_attention]
    elif show == "dropped":
        shown = [e for e in entries if e.dropped_at is not None]
    elif show == "all":
        shown = entries
    else:
        show, shown = "", [e for e in entries if e.dropped_at is None]
    return render_template(
        "roster.html",
        offering=g.offering,
        course=g.course,
        entries=shown,
        show=show,
        counts=counts(g.offering),
    )


def counts(offering) -> dict:
    """The numbers the offering page's Roster panel shows."""
    out = {"student": 0, "test": 0, "staff": 0, "dropped": 0, "attention": 0}
    for e in offering.roster:
        if e.dropped_at is not None:
            out["dropped"] += 1
            continue
        out["student" if e.role == "student" else "test" if e.role == "test" else "staff"] += 1
        if e.needs_attention and e.role in rostermod.PARTICIPANT_ROLES:
            out["attention"] += 1
    out["total"] = len(offering.roster)
    return out


# -- uploads -------------------------------------------------------------------


@bp.post("/offerings/<int:offering_id>/roster/uploads")
@offering_staff_required
def upload(offering_id):
    file = request.files.get("file")
    mode = request.form.get("mode", "replace")
    if mode not in rostermod.MODES:
        abort(400)
    if file is None or not file.filename:
        flash("Choose a CSV file to upload.")
        return redirect(url_for("roster.page", offering_id=offering_id))
    try:
        parsed = rostermod.parse(file.read(rostermod.MAX_BYTES + 1))
    except rostermod.RosterError as exc:
        flash(f"{file.filename}: {exc}")
        return redirect(url_for("roster.page", offering_id=offering_id))

    preview = rostermod.diff(g.offering.roster, parsed, mode)
    logins = rostermod.logins_to_check(preview)
    # Rows kept unchanged whose earlier lookup failed get another try.
    in_file = {r["username"].lower() for r in parsed.rows}
    logins += [
        e.github_login
        for e in g.offering.roster
        if e.github_status == "unchecked" and e.github_login and e.username_key in in_file
    ]
    lookups, error = check_logins(sorted(set(logins), key=str.lower))
    preview["github"] = lookups
    preview["github_error"] = error
    preview["not_found"] = sorted(
        (login for login in set(logins) if lookups.get(login.lower(), 0) is None), key=str.lower
    )

    up = RosterUpload(
        offering_id=g.offering.id,
        uploaded_by_id=g.user.id,
        filename=file.filename[:255],
        mode=mode,
        base_revision=g.offering.roster_revision,
        parsed=parsed.to_json(),
        preview=preview,
    )
    db.session.add(up)
    db.session.commit()
    return redirect(url_for("roster.preview", offering_id=offering_id, upload_id=up.id))


def _upload(upload_id) -> RosterUpload:
    up = db.session.get(RosterUpload, upload_id)
    if up is None or up.offering_id != g.offering.id:
        abort(404)
    return up


@bp.get("/offerings/<int:offering_id>/roster/uploads/<int:upload_id>")
@offering_staff_required
def preview(offering_id, upload_id):
    up = _upload(upload_id)
    return render_template(
        "roster_preview.html",
        offering=g.offering,
        course=g.course,
        upload=up,
        p=up.preview,
        stale=up.base_revision != g.offering.roster_revision,
        labels=FIELD_LABELS,
        name=rostermod.display_name,
    )


@bp.post("/offerings/<int:offering_id>/roster/uploads/<int:upload_id>/apply")
@offering_staff_required
def apply(offering_id, upload_id):
    up = _upload(upload_id)
    if up.applied_at is not None:
        flash("That upload was already applied.")
        return redirect(url_for("roster.page", offering_id=offering_id))
    if up.base_revision != g.offering.roster_revision:
        flash("The roster changed after this preview was made. Upload the file again.")
        return redirect(url_for("roster.page", offering_id=offering_id))

    summary = apply_preview(g.offering, up.preview)
    up.applied_at = datetime.now(UTC)
    db.session.commit()
    flash("Roster updated: " + summary + ".")
    return redirect(url_for("roster.page", offering_id=offering_id))


def apply_preview(offering, p: dict) -> str:
    """Make the changes a saved preview lists. Returns a summary."""
    lookups = p.get("github") or {}
    by_key = {e.username_key: e for e in offering.roster}
    fields = ("first_name", "last_name", "email", "section", "role")

    for row in p["new"]:
        entry = RosterEntry(username=row["username"], username_key=row["username"].lower())
        for k in fields:
            setattr(entry, k, row[k])
        set_github(entry, row["github_login"], lookups)
        offering.roster.append(entry)
    for item in p["changed"] + p["returning"]:
        row, entry = item["row"], by_key.get(item["row"]["username"].lower())
        if entry is None:
            continue
        for k in fields:
            setattr(entry, k, row[k])
        if "github_login" in item["changes"] or entry.github_status == "unchecked":
            set_github(entry, row["github_login"], lookups)
        entry.dropped_at = None
    for username in p["unchanged"]:
        entry = by_key.get(username.lower())
        if entry is not None and entry.github_status == "unchecked":
            set_github(entry, entry.github_login, lookups)
    now = datetime.now(UTC)
    for d in p["dropped"]:
        entry = by_key.get(d["username"].lower())
        if entry is not None and entry.dropped_at is None:
            entry.dropped_at = now
    _bump(offering)

    parts = [
        f"{len(p['new'])} added",
        f"{len(p['changed'])} changed",
        f"{len(p['returning'])} returned",
        f"{len(p['dropped'])} dropped",
    ]
    return ", ".join(parts)


@bp.post("/offerings/<int:offering_id>/roster/uploads/<int:upload_id>/cancel")
@offering_staff_required
def cancel(offering_id, upload_id):
    up = _upload(upload_id)
    if up.applied_at is None:
        db.session.delete(up)
        db.session.commit()
    return redirect(url_for("roster.page", offering_id=offering_id))


# -- one person at a time ------------------------------------------------------


def _entry(entry_id) -> RosterEntry:
    entry = db.session.get(RosterEntry, entry_id)
    if entry is None or entry.offering_id != g.offering.id:
        abort(404)
    return entry


def _login_holder(login: str, except_id: int | None = None) -> RosterEntry | None:
    """Who else on this roster (not dropped) has this GitHub username."""
    if not login:
        return None
    for e in g.offering.roster:
        if e.id != except_id and e.dropped_at is None and e.github_login.lower() == login.lower():
            return e
    return None


def _form_row() -> dict:
    return rostermod.clean_row({k: request.form.get(k, "") for k in rostermod.FIELDS})


def _form_page(entry, form, status=200):
    return (
        render_template(
            "roster_entry_form.html",
            offering=g.offering,
            course=g.course,
            entry=entry,
            form=form,
            roles=rostermod.ROLES,
        ),
        status,
    )


@bp.get("/offerings/<int:offering_id>/roster/new")
@offering_staff_required
def new_entry(offering_id):
    return _form_page(None, {"role": "student"})


@bp.post("/offerings/<int:offering_id>/roster/entries")
@offering_staff_required
def create_entry(offering_id):
    row = _form_row()
    form = {**row, "github_id": row["github_login"]}
    problem = rostermod.check_row(row)
    if problem is None and any(
        e.username_key == row["username"].lower() for e in g.offering.roster
    ):
        problem = f"{row['username']} is already on the roster (perhaps dropped: see Dropped)."
    holder = _login_holder(row["github_login"])
    if problem is None and holder:
        problem = f"GitHub username {row['github_login']} already belongs to {holder.username}."
    if problem:
        flash(problem[0].upper() + problem[1:])
        return _form_page(None, form, 400)

    entry = RosterEntry(username=row["username"], username_key=row["username"].lower())
    for k in ("first_name", "last_name", "email", "section", "role"):
        setattr(entry, k, row[k])
    lookups, error = check_logins([row["github_login"]] if row["github_login"] else [])
    set_github(entry, row["github_login"], lookups)
    g.offering.roster.append(entry)
    _bump(g.offering)
    db.session.commit()
    _flash_lookup(entry, error)
    flash(f"Added {entry.display_name}.")
    return redirect(url_for("roster.page", offering_id=offering_id))


@bp.get("/offerings/<int:offering_id>/roster/entries/<int:entry_id>/edit")
@offering_staff_required
def edit_entry(offering_id, entry_id):
    entry = _entry(entry_id)
    return _form_page(entry, entry.csv_row())


@bp.post("/offerings/<int:offering_id>/roster/entries/<int:entry_id>")
@offering_staff_required
def update_entry(offering_id, entry_id):
    entry = _entry(entry_id)
    row = _form_row()
    row["username"] = entry.username  # never changed: repos are named after it
    form = {**row, "github_id": row["github_login"]}
    problem = rostermod.check_row(row)
    holder = _login_holder(row["github_login"], except_id=entry.id)
    if problem is None and holder and entry.dropped_at is None:
        problem = f"GitHub username {row['github_login']} already belongs to {holder.username}."
    if problem:
        flash(problem[0].upper() + problem[1:])
        return _form_page(entry, form, 400)

    for k in ("first_name", "last_name", "email", "section", "role"):
        setattr(entry, k, row[k])
    error = None
    if row["github_login"].lower() != entry.github_login.lower() or (
        row["github_login"] and entry.github_status == "unchecked"
    ):
        lookups, error = check_logins([row["github_login"]] if row["github_login"] else [])
        set_github(entry, row["github_login"], lookups)
    _bump(g.offering)
    db.session.commit()
    _flash_lookup(entry, error)
    flash(f"Saved {entry.display_name}.")
    return redirect(url_for("roster.page", offering_id=offering_id))


def _flash_lookup(entry: RosterEntry, error: str | None) -> None:
    if entry.github_status == "not_found":
        flash(f"GitHub has no account called {entry.github_login}. Check the spelling.")
    elif entry.github_status == "unchecked" and error:
        flash(f"Couldn't check the GitHub username: {error}")


@bp.post("/offerings/<int:offering_id>/roster/entries/<int:entry_id>/drop")
@offering_staff_required
def drop_entry(offering_id, entry_id):
    entry = _entry(entry_id)
    if entry.dropped_at is None:
        entry.dropped_at = datetime.now(UTC)
        _bump(g.offering)
        db.session.commit()
        flash(f"Dropped {entry.display_name}.")
    return redirect(url_for("roster.page", offering_id=offering_id))


@bp.post("/offerings/<int:offering_id>/roster/entries/<int:entry_id>/restore")
@offering_staff_required
def restore_entry(offering_id, entry_id):
    entry = _entry(entry_id)
    holder = _login_holder(entry.github_login, except_id=entry.id)
    if holder:
        flash(
            f"Can't restore {entry.username}: GitHub username {entry.github_login} now belongs "
            f"to {holder.username}."
        )
    elif entry.dropped_at is not None:
        entry.dropped_at = None
        _bump(g.offering)
        db.session.commit()
        flash(f"Restored {entry.display_name}.")
    return redirect(url_for("roster.page", offering_id=offering_id, show="dropped"))


# -- downloads -----------------------------------------------------------------


def _csv_response(text: str, name: str) -> Response:
    return Response(
        text,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def _file_stem() -> str:
    raw = f"{g.course.code}-{g.offering.label}-roster"
    return re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-").lower()


@bp.get("/offerings/<int:offering_id>/roster.csv")
@offering_staff_required
def download(offering_id):
    rows = [e.csv_row() for e in _entries(g.offering) if e.dropped_at is None]
    return _csv_response(rostermod.csv_text(rows), _file_stem() + ".csv")


@bp.get("/offerings/<int:offering_id>/roster/blank.csv")
@offering_staff_required
def blank(offering_id):
    return _csv_response(rostermod.csv_text([]), "roster.csv")
