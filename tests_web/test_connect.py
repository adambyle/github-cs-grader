from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from conftest import sign_in_as

from webapp.extensions import db
from webapp.github.app_auth import API
from webapp.models import Course, CourseStaff, Installation, Offering

ORG_INSTALL = {
    "id": 777,
    "account": {"id": 55, "login": "cs108-26fa", "type": "Organization"},
    "repository_selection": "all",
    "permissions": {"members": "write"},
    "suspended_at": None,
}


@pytest.fixture
def offering_id(app, client, make_user):
    """An instructor signed in, owning CS 108 with a Fall 2026 offering."""
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


def visible(*installs):
    """The installations GET /user/installations reports for the user."""
    return respx.get(f"{API}/user/installations").respond(
        200, json={"total_count": len(installs), "installations": list(installs)}
    )


def org_of(app, offering_id):
    with app.app_context():
        return db.session.get(Offering, offering_id).org_login


def start_state(client, offering_id):
    resp = client.get(f"/offerings/{offering_id}/connect")
    return parse_qs(urlparse(resp.headers["Location"]).query)["state"][0]


def test_connect_goes_to_install_page_with_signed_state(client, offering_id):
    url = urlparse(client.get(f"/offerings/{offering_id}/connect").headers["Location"])
    assert url.netloc == "github.com"
    assert url.path == "/apps/coursekit-test/installations/new"
    assert parse_qs(url.query)["state"][0]


@respx.mock
def test_setup_url_links_an_installation_the_user_can_see(app, client, offering_id):
    state = start_state(client, offering_id)
    visible(ORG_INSTALL)
    resp = client.get(
        f"/github/installed?installation_id=777&setup_action=install&state={state}",
        follow_redirects=True,
    )
    assert "Connected to cs108-26fa." in resp.text
    assert org_of(app, offering_id) == "cs108-26fa"


@respx.mock
def test_setup_url_works_from_the_session_when_state_is_missing(app, client, offering_id):
    client.get(f"/offerings/{offering_id}/connect")
    visible(ORG_INSTALL)
    client.get("/github/installed?installation_id=777&setup_action=install")
    assert org_of(app, offering_id) == "cs108-26fa"


@respx.mock
def test_typed_in_installation_id_is_refused(app, client, offering_id):
    client.get(f"/offerings/{offering_id}/connect")
    visible(ORG_INSTALL)  # the user can see 777, not 999
    resp = client.get(
        "/github/installed?installation_id=999&setup_action=install", follow_redirects=True
    )
    assert "see that installation" in resp.text
    assert org_of(app, offering_id) is None


@respx.mock
def test_personal_account_is_refused(app, client, offering_id):
    client.get(f"/offerings/{offering_id}/connect")
    visible({**ORG_INSTALL, "account": {"id": 9, "login": "prof", "type": "User"}})
    resp = client.get(
        "/github/installed?installation_id=777&setup_action=install", follow_redirects=True
    )
    assert "personal account prof" in resp.text
    assert org_of(app, offering_id) is None


@respx.mock
def test_selected_repositories_warns(client, offering_id):
    visible({**ORG_INSTALL, "repository_selection": "selected"})
    resp = client.post(
        f"/offerings/{offering_id}/installation",
        data={"installation_id": 777},
        follow_redirects=True,
    )
    assert "only see selected repositories" in resp.text


@respx.mock
def test_offering_page_lists_existing_org_installations(client, offering_id):
    personal = {**ORG_INSTALL, "id": 5, "account": {"id": 9, "login": "prof", "type": "User"}}
    visible(ORG_INSTALL, personal)
    page = client.get(f"/offerings/{offering_id}").text
    assert '<option value="777">cs108-26fa</option>' in page
    assert ">prof</option>" not in page


def test_request_for_owner_approval(client, offering_id, http_mock):
    http_mock.get(f"{API}/user/installations").respond(200, json={"installations": []})
    client.get(f"/offerings/{offering_id}/connect")
    resp = client.get("/github/installed?setup_action=request", follow_redirects=True)
    assert "has to approve" in resp.text


def test_state_for_someone_else_is_ignored(app, client, offering_id, make_user):
    state = start_state(client, offering_id)
    sign_in_as(client, make_user("intruder", mode="instructor"))
    resp = client.get(
        f"/github/installed?installation_id=777&setup_action=install&state={state}",
        follow_redirects=True,
    )
    assert "Open the offering it belongs to" in resp.text
    assert org_of(app, offering_id) is None


@respx.mock
def test_removed_installation_shows_reconnect(app, client, offering_id):
    route = visible(ORG_INSTALL)
    client.post(f"/offerings/{offering_id}/installation", data={"installation_id": 777})
    with app.app_context():
        db.session.get(Installation, 777).removed_at = datetime.now(UTC)
        db.session.commit()
    # GitHub no longer lists it either (otherwise the page would rightly revive it)
    route.return_value = httpx.Response(200, json={"total_count": 0, "installations": []})
    assert "was removed from cs108-26fa" in client.get(f"/offerings/{offering_id}").text
