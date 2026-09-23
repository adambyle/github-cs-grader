"""The roster pages: upload, preview, apply, and editing one row."""

import io
import re
from pathlib import Path

import httpx
import pytest
from conftest import sign_in_as

from webapp.extensions import db
from webapp.github.app_auth import API
from webapp.models import Course, CourseStaff, Offering, RosterEntry, RosterUpload

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/sample-course/roster/roster.csv"
HEADER = "username,first_name,last_name,email,section,github_id,role\n"

# GitHub accounts that "exist", by lowercased login: (id, capitalization).
ACCOUNTS = {"jsmith-gh": (101, "JSmith-GH"), "adambyle": (102, "adambyle"), "real": (103, "Real")}


@pytest.fixture
def github_users(http_mock):
    """GET /users/<login> answers from ACCOUNTS; records what was asked."""
    asked = []

    def lookup(request):
        login = request.url.path.rsplit("/", 1)[1]
        asked.append(login)
        if login.lower() in ACCOUNTS:
            uid, name = ACCOUNTS[login.lower()]
            return httpx.Response(200, json={"id": uid, "login": name})
        return httpx.Response(404, json={"message": "Not Found"})

    http_mock.get(url__regex=rf"^{re.escape(API)}/users/[^/]+$").mock(side_effect=lookup)
    return asked


@pytest.fixture
def offering_id(app, make_user, client):
    prof = make_user("prof", mode="instructor")
    with app.app_context():
        course = Course(code="CS 108", title="Web", created_by_id=prof.id)
        course.staff.append(CourseStaff(user_id=prof.id, role="owner"))
        offering = Offering(course=course, label="Fall 2026")
        db.session.add(course)
        db.session.commit()
        oid = offering.id
    sign_in_as(client, prof)
    return oid


def upload(client, offering_id, text, mode="replace", name="roster.csv"):
    data = {"file": (io.BytesIO(text.encode()), name), "mode": mode}
    resp = client.post(
        f"/offerings/{offering_id}/roster/uploads", data=data, content_type="multipart/form-data"
    )
    assert resp.status_code == 302, resp.text
    return resp.headers["Location"]


def apply(client, preview_url):
    return client.post(preview_url + "/apply", follow_redirects=True)


def entries(app):
    with app.app_context():
        return {e.username: e for e in db.session.scalars(db.select(RosterEntry))}


def test_example_roster_uploads_and_flags_the_placeholder_login(
    app, client, offering_id, github_users
):
    preview = upload(client, offering_id, EXAMPLE.read_text())
    page = client.get(preview).text
    assert "New (2)" in page
    assert "GitHub usernames not found (1)" in page and "your-test-login" in page
    assert "Roster updated: 2 added" in apply(client, preview).text
    got = entries(app)
    assert (got["jsmith"].github_status, got["jsmith"].github_login) == ("ok", "JSmith-GH")
    assert got["testacct"].github_status == "not_found"


def test_found_logins_store_id_and_capitalization(
    app, client, offering_id, github_users, http_mock
):
    http_mock.get(f"{API}/user/installations").respond(200, json={"installations": []})
    apply(client, upload(client, offering_id, HEADER + "a,Ann,Lee,,,@adambyle,teacher\nb,,,,,,\n"))
    got = entries(app)
    assert (got["a"].github_status, got["a"].github_user_id) == ("ok", 102)
    assert got["b"].github_status == "missing"
    page = client.get(f"/offerings/{offering_id}").text
    assert "1 student" in page and "1 staff" in page and "1 needs a GitHub username" in page


def test_reupload_only_looks_up_changed_logins(app, client, offering_id, github_users):
    apply(client, upload(client, offering_id, HEADER + "a,,,,,real,\nb,,,,,adambyle,\n"))
    github_users.clear()
    preview = upload(client, offering_id, HEADER + "a,,,,,REAL,\nb,,,,,jsmith-gh,\n")
    assert github_users == ["jsmith-gh"]
    page = client.get(preview).text
    assert "Changed (1)" in page and "Unchanged (1)" in page
    apply(client, preview)
    assert entries(app)["b"].github_login == "JSmith-GH"


def test_whole_roster_mode_drops_and_restore_brings_back(app, client, offering_id, github_users):
    apply(client, upload(client, offering_id, HEADER + "a,,,,,,\nb,,,,,,\n"))
    preview = upload(client, offering_id, HEADER + "a,,,,,,\n")
    assert "Dropped (1)" in client.get(preview).text
    apply(client, preview)
    b = entries(app)["b"]
    assert b.dropped_at is not None
    assert "<td>b</td>" not in client.get(f"/offerings/{offering_id}/roster").text
    assert "<td>b</td>" in client.get(f"/offerings/{offering_id}/roster?show=dropped").text
    resp = client.post(
        f"/offerings/{offering_id}/roster/entries/{b.id}/restore", follow_redirects=True
    )
    assert "Restored b" in resp.text
    assert entries(app)["b"].dropped_at is None


def test_merge_mode_drops_nobody(app, client, offering_id, github_users):
    apply(client, upload(client, offering_id, HEADER + "a,,,,,,\n"))
    apply(client, upload(client, offering_id, HEADER + "b,,,,,,\n", mode="merge"))
    assert all(e.dropped_at is None for e in entries(app).values())


def test_problem_rows_are_left_out_and_the_rest_applies(app, client, offering_id, github_users):
    preview = upload(client, offering_id, HEADER + "a,,,,,,\na,,,,,,\nb,,,,,,\n")
    assert "Problems (1)" in client.get(preview).text
    apply(client, preview)
    assert sorted(entries(app)) == ["a", "b"]


def test_stale_preview_is_refused(app, client, offering_id, github_users):
    first = upload(client, offering_id, HEADER + "a,,,,,,\n")
    second = upload(client, offering_id, HEADER + "b,,,,,,\n")
    apply(client, first)
    resp = apply(client, second)
    assert "The roster changed after this preview was made" in resp.text
    assert sorted(entries(app)) == ["a"]


def test_cancel_changes_nothing(app, client, offering_id, github_users):
    preview = upload(client, offering_id, HEADER + "a,,,,,,\n")
    client.post(preview + "/cancel")
    assert entries(app) == {}
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(RosterUpload.id))) == 0


def test_github_unreachable_saves_rows_unchecked(app, client, offering_id, http_mock):
    http_mock.get(url__regex=rf"^{re.escape(API)}/users/").mock(
        side_effect=httpx.ConnectError("down")
    )
    preview = upload(client, offering_id, HEADER + "a,,,,,real,\n")
    assert "Couldn't check GitHub usernames" in client.get(preview).text
    apply(client, preview)
    assert entries(app)["a"].github_status == "unchecked"


def test_add_edit_and_drop_by_hand(app, client, offering_id, github_users):
    base = f"/offerings/{offering_id}/roster"
    resp = client.post(
        f"{base}/entries",
        data={"username": "cj", "first_name": "Cara", "github_id": "cjonez", "role": "student"},
        follow_redirects=True,
    )
    assert "GitHub has no account called cjonez" in resp.text
    cj = entries(app)["cj"]
    assert cj.github_status == "not_found"
    assert 'name="username"' in client.get(f"{base}/new").text
    assert "can't be changed" in client.get(f"{base}/entries/{cj.id}/edit").text
    # the same username again is refused
    resp = client.post(f"{base}/entries", data={"username": "CJ", "role": "student"})
    assert resp.status_code == 400 and "already on the roster" in resp.text
    # fix the login; username can't change even if the form says so
    resp = client.post(
        f"{base}/entries/{cj.id}",
        data={"username": "other", "first_name": "Cara", "github_id": "real", "role": "student"},
        follow_redirects=True,
    )
    cj = entries(app)["cj"]
    assert (cj.github_status, cj.github_login, cj.github_user_id) == ("ok", "Real", 103)
    client.post(f"{base}/entries/{cj.id}/drop")
    assert entries(app)["cj"].dropped_at is not None


def test_login_already_on_the_roster_is_refused(app, client, offering_id, github_users):
    apply(client, upload(client, offering_id, HEADER + "a,,,,,real,\n"))
    resp = client.post(
        f"/offerings/{offering_id}/roster/entries",
        data={"username": "b", "github_id": "REAL", "role": "student"},
    )
    assert resp.status_code == 400 and "already belongs to a" in resp.text


def test_download_round_trips_with_no_changes(app, client, offering_id, github_users):
    apply(client, upload(client, offering_id, HEADER + "a,Ann,Lee,a@x.edu,A,real,test\nb,,,,,,\n"))
    csv = client.get(f"/offerings/{offering_id}/roster.csv")
    assert csv.mimetype == "text/csv"
    assert csv.text.startswith(HEADER)
    page = client.get(upload(client, offering_id, csv.text)).text
    assert "Nothing to change" in page and "Unchanged (2)" in page
    blank = client.get(f"/offerings/{offering_id}/roster/blank.csv")
    assert blank.text == HEADER


def test_only_staff_see_the_roster(app, client, offering_id, make_user):
    sign_in_as(client, make_user("stranger", mode="instructor"))
    assert client.get(f"/offerings/{offering_id}/roster").status_code == 404
    assert client.get(f"/offerings/{offering_id}/roster.csv").status_code == 404
