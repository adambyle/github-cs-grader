"""The student's side: home page, offering page, and the Join button."""

from conftest import ORG, sign_in_as
from test_membership import states

from webapp import auth
from webapp.extensions import db
from webapp.github.app_auth import API
from webapp.github.user_auth import TokenSet
from webapp.models import RosterEntry


def as_student(client, make_user, login="ann", github_id=101):
    user = make_user(login, mode="student", github_id=github_id)
    sign_in_as(client, user)
    return user


def test_student_sees_their_offering_and_the_join_banner(
    app, client, org_offering, fake_org, make_user
):
    fake_org["members"]["ann"] = "pending"
    as_student(client, make_user)
    home = client.get("/").text
    assert "CS 108 · Web" in home and "join" in home
    page = client.get(f"/offerings/{org_offering}").text
    assert f"Join {ORG}" in page
    assert f"https://github.com/orgs/{ORG}/invitation" in page
    assert "Roster" not in page  # not the staff page


def test_join_accepts_with_the_students_own_token(
    app, client, org_offering, fake_org, make_user, http_mock
):
    fake_org["members"]["ann"] = "pending"
    route = http_mock.patch(f"{API}/user/memberships/orgs/{ORG}").respond(
        200, json={"state": "active"}
    )
    as_student(client, make_user)
    resp = client.post(f"/offerings/{org_offering}/join", follow_redirects=True)
    assert route.calls.last.request.headers["Authorization"] == "Bearer ghu_ann"
    assert f"now a member of {ORG}" in resp.text
    assert states(app)["ann"] == "active"


def test_join_failure_points_to_github(app, client, org_offering, fake_org, make_user, http_mock):
    fake_org["members"]["ann"] = "pending"
    http_mock.patch(f"{API}/user/memberships/orgs/{ORG}").respond(403, json={"message": "no"})
    as_student(client, make_user)
    resp = client.post(f"/offerings/{org_offering}/join", follow_redirects=True)
    assert "Accept it on GitHub instead" in resp.text
    assert states(app)["ann"] == "invited"


def test_accepting_by_email_shows_up_on_the_next_visit(
    app, client, org_offering, fake_org, make_user
):
    fake_org["members"]["ann"] = "active"
    as_student(client, make_user)
    assert "You're a member of" in client.get(f"/offerings/{org_offering}").text
    assert states(app)["ann"] == "active"


def test_matched_by_account_id_after_a_rename(app, client, org_offering, fake_org, make_user):
    as_student(client, make_user, login="ann-renamed", github_id=101)
    assert "CS 108 · Web" in client.get("/").text
    assert client.get(f"/offerings/{org_offering}").status_code == 200


def test_dropped_students_and_strangers_see_nothing(app, client, org_offering, fake_org, make_user):
    with app.app_context():
        ann = db.session.scalar(db.select(RosterEntry).where(RosterEntry.github_login == "ann"))
        ann.dropped_at = ann.created_at
        db.session.commit()
    as_student(client, make_user)
    assert "no course lists that GitHub account" in client.get("/").text
    assert client.get(f"/offerings/{org_offering}").status_code == 404
    sign_in_as(client, make_user("stranger", github_id=999))
    assert client.get(f"/offerings/{org_offering}").status_code == 404
    assert client.post(f"/offerings/{org_offering}/join").status_code == 404


def test_signing_in_claims_rows_by_login(app, http_mock):
    with app.app_context():
        from webapp.models import Offering

        offering = db.session.scalar(db.select(Offering))
        assert offering is None  # no fixture here: make our own row
    http_mock.get(f"{API}/user").respond(200, json={"id": 555, "login": "NewKid", "name": None})
    http_mock.get(f"{API}/user/emails").respond(200, json=[])
    with app.app_context():
        from webapp.models import Course, Offering, User

        prof = User(github_id=1, login="prof")
        db.session.add(prof)
        db.session.flush()
        offering = Offering(course=Course(code="X", title="Y", created_by_id=prof.id), label="F")
        offering.roster.append(
            RosterEntry(
                username="nk", username_key="nk", github_login="newkid", github_status="unchecked"
            )
        )
        db.session.add(offering)
        db.session.commit()
        auth.sign_in(TokenSet("ghu_x", None, None, None))
        row = db.session.scalar(db.select(RosterEntry))
        assert (row.github_user_id, row.github_login, row.github_status) == (555, "NewKid", "ok")


def test_staff_on_their_own_roster_see_the_student_page_in_student_mode(
    app, client, org_offering, fake_org, make_user, http_mock
):
    http_mock.get(f"{API}/user/installations").respond(200, json={"installations": []})
    with app.app_context():
        from webapp.models import User

        prof = db.session.scalar(db.select(User).where(User.login == "prof"))
        prof_row = db.session.scalar(db.select(RosterEntry).where(RosterEntry.username == "prof"))
        prof_row.github_user_id = prof.github_id
        prof.mode = "student"
        db.session.commit()
    page = client.get(f"/offerings/{org_offering}").text
    assert "Assignments" in page and "Upload a roster" not in page
