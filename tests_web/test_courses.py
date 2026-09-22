from conftest import sign_in_as

from webapp.extensions import db
from webapp.github.app_auth import API
from webapp.models import Course, Offering


def create_course(client, code="CS 108", title="Web Programming"):
    resp = client.post("/courses", data={"code": code, "title": title})
    assert resp.status_code == 302
    return int(resp.headers["Location"].rsplit("/", 1)[1])


def test_instructor_creates_course_and_offering(app, client, make_user, http_mock):
    sign_in_as(client, make_user("prof", mode="instructor"))
    course_id = create_course(client)
    resp = client.post(f"/courses/{course_id}/offerings", data={"label": "Fall 2026"})
    assert resp.status_code == 302
    home = client.get("/").text
    assert "CS 108 · Web Programming" in home and "Fall 2026" in home
    http_mock.get(f"{API}/user/installations").respond(200, json={"installations": []})
    page = client.get(resp.headers["Location"]).text
    assert "Connect organization" in page


def test_duplicate_offering_is_refused(app, client, make_user):
    sign_in_as(client, make_user("prof", mode="instructor"))
    course_id = create_course(client)
    client.post(f"/courses/{course_id}/offerings", data={"label": "Fall 2026"})
    resp = client.post(
        f"/courses/{course_id}/offerings", data={"label": "fall 2026"}, follow_redirects=True
    )
    assert "already has an offering" in resp.text
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Offering.id))) == 1


def test_student_mode_cannot_create_courses(client, make_user):
    sign_in_as(client, make_user("stu", mode="student"))
    assert client.post("/courses", data={"code": "X", "title": "Y"}).status_code == 302
    assert client.get("/courses/new").status_code == 302


def test_someone_off_the_staff_gets_404_even_in_instructor_mode(app, client, make_user):
    prof, other = make_user("prof", mode="instructor"), make_user("other", mode="instructor")
    sign_in_as(client, prof)
    course_id = create_course(client)
    client.post(f"/courses/{course_id}/offerings", data={"label": "Fall 2026"})
    with app.app_context():
        offering_id = db.session.scalar(db.select(Offering.id))
    sign_in_as(client, other)
    assert client.get(f"/courses/{course_id}").status_code == 404
    assert client.get(f"/offerings/{offering_id}").status_code == 404
    assert "CS 108" not in client.get("/").text


def test_owner_adds_co_instructor_who_has_signed_in(app, client, make_user):
    prof, co = make_user("prof", mode="instructor"), make_user("co-prof")
    sign_in_as(client, prof)
    course_id = create_course(client)
    resp = client.post(
        f"/courses/{course_id}/staff", data={"login": "@Co-Prof"}, follow_redirects=True
    )
    assert "co-prof can now manage CS 108" in resp.text
    resp = client.post(
        f"/courses/{course_id}/staff", data={"login": "nobody"}, follow_redirects=True
    )
    assert "No one has signed in to coursekit as nobody" in resp.text
    sign_in_as(client, co)
    assert client.get(f"/courses/{course_id}").status_code == 200
    # a co-instructor cannot add more staff
    assert client.post(f"/courses/{course_id}/staff", data={"login": "prof"}).status_code == 403


def test_missing_fields(client, make_user, app):
    sign_in_as(client, make_user("prof", mode="instructor"))
    assert client.post("/courses", data={"code": "", "title": ""}).status_code == 400
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Course.id))) == 0
