"""Org invitations and membership (membership.py, the roster page's org
panel, and the organization.* webhooks)."""

import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import sign_in_as
from test_handlers import deliver

from webapp.extensions import db
from webapp.github.app_auth import API
from webapp.models import Course, CourseStaff, Installation, Offering, RosterEntry

ORG = "cs108-26fa"


@pytest.fixture
def github(http_mock):
    """A fake org. `members` maps lowercased login -> 'active' or 'pending';
    invitations add 'pending'. `refuse` makes invitations fail with a
    response. `calls` records (method, path)."""
    state = {"members": {}, "refuse": None, "calls": []}
    ids = {101: "ann", 102: "bob", 103: "cy"}
    expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    http_mock.post(f"{API}/app/installations/777/access_tokens").respond(
        201, json={"token": "ghs_org", "expires_at": expires}
    )

    def membership(request):
        login = request.url.path.rsplit("/", 1)[1].lower()
        state["calls"].append((request.method, login))
        if request.method == "DELETE":
            state["members"].pop(login, None)
            return httpx.Response(204)
        if login in state["members"]:
            return httpx.Response(200, json={"state": state["members"][login]})
        return httpx.Response(404, json={"message": "Not Found"})

    def invite(request):
        import json

        uid = json.loads(request.content)["invitee_id"]
        state["calls"].append(("INVITE", ids[uid]))
        if state["refuse"] is not None:
            return state["refuse"]
        state["members"][ids[uid]] = "pending"
        return httpx.Response(201, json={})

    http_mock.route(url__regex=rf"^{re.escape(API)}/orgs/{ORG}/memberships/[^/]+$").mock(
        side_effect=membership
    )
    http_mock.post(f"{API}/orgs/{ORG}/invitations").mock(side_effect=invite)
    return state


@pytest.fixture
def offering_id(app, make_user, client):
    prof = make_user("prof", mode="instructor")
    with app.app_context():
        inst = Installation(
            id=777,
            account_id=55,
            account_login=ORG,
            account_type="Organization",
            repository_selection="all",
        )
        course = Course(code="CS 108", title="Web", created_by_id=prof.id)
        course.staff.append(CourseStaff(user_id=prof.id, role="owner"))
        offering = Offering(course=course, label="Fall 2026", installation=inst)
        for n, (login, uid) in enumerate([("ann", 101), ("bob", 102), ("cy", 103)]):
            offering.roster.append(
                RosterEntry(
                    username=f"s{n}",
                    username_key=f"s{n}",
                    first_name=login.title(),
                    github_login=login,
                    github_user_id=uid,
                    github_status="ok",
                )
            )
        offering.roster.append(RosterEntry(username="nogh", username_key="nogh"))
        offering.roster.append(
            RosterEntry(
                username="prof",
                username_key="prof",
                role="teacher",
                github_login="prof",
                github_user_id=9,
                github_status="ok",
            )
        )
        db.session.add(course)
        db.session.commit()
        oid = offering.id
    sign_in_as(client, prof)
    return oid


def states(app):
    with app.app_context():
        return {
            e.github_login or e.username: e.membership
            for e in db.session.scalars(db.select(RosterEntry))
        }


def test_send_invitations_invites_participants_only(app, client, offering_id, github):
    github["members"]["bob"] = "active"
    page = client.get(f"/offerings/{offering_id}/roster").text  # starts a check
    assert "Send invitations (2)" in page
    resp = client.post(f"/offerings/{offering_id}/roster/invitations", follow_redirects=True)
    assert "Sending 2 invitations" in resp.text
    got = states(app)
    assert (got["ann"], got["bob"], got["cy"]) == ("invited", "active", "invited")
    assert got["nogh"] == "unknown"  # no GitHub username: never checked or invited
    invited = sorted(login for method, login in github["calls"] if method == "INVITE")
    assert invited == ["ann", "cy"]
    # sending again invites nobody
    github["calls"].clear()
    client.post(f"/offerings/{offering_id}/roster/invitations")
    assert not any(method == "INVITE" for method, _ in github["calls"])


def test_the_daily_cap_pauses_and_keeps_the_rest_queued(app, client, offering_id, github):
    github["refuse"] = httpx.Response(
        422,
        json={
            "message": "Validation Failed",
            "errors": [{"message": "Over invitation rate limit"}],
        },
    )
    client.post(f"/offerings/{offering_id}/roster/invitations")
    got = states(app)
    assert got["ann"] == got["bob"] == got["cy"] == "queued"
    with app.app_context():
        offering = db.session.get(Offering, offering_id)
        resume = offering.invites_resume_at.replace(tzinfo=UTC)
        assert resume > datetime.now(UTC) + timedelta(hours=23)
    page = client.get(f"/offerings/{offering_id}/roster").text
    assert "3 more will be sent automatically" in page


def test_a_refused_invitation_is_failed_with_the_reason_and_can_be_resent(
    app, client, offering_id, github
):
    github["refuse"] = httpx.Response(422, json={"message": "Invitee is blocked"})
    client.post(f"/offerings/{offering_id}/roster/invitations")
    assert states(app)["ann"] == "failed"
    page = client.get(f"/offerings/{offering_id}/roster").text
    assert "Invitee is blocked" in page and "Resend" in page
    github["refuse"] = None
    with app.app_context():
        ann = db.session.scalar(db.select(RosterEntry).where(RosterEntry.github_login == "ann"))
    client.post(f"/offerings/{offering_id}/roster/entries/{ann.id}/invite")
    assert states(app)["ann"] == "invited"


def test_webhooks_move_rows_between_states(app, client, offering_id, github):
    install = {"id": 777}
    org = {"login": ORG}
    deliver(
        client,
        "organization",
        {
            "action": "member_invited",
            "installation": install,
            "organization": org,
            "invitation": {"login": "ANN"},
            "user": {"id": 101, "login": "ann"},
        },
    )
    assert states(app)["ann"] == "invited"
    added = {"user": {"id": 101, "login": "ann-renamed"}, "state": "active"}
    deliver(
        client,
        "organization",
        {
            "action": "member_added",
            "installation": install,
            "organization": org,
            "membership": added,
        },
    )
    assert states(app)["ann"] == "active"  # matched by id despite the rename
    deliver(
        client,
        "organization",
        {
            "action": "member_removed",
            "installation": install,
            "organization": org,
            "membership": added,
        },
    )
    assert states(app)["ann"] == "none"


def test_removing_dropped_people(app, client, offering_id, github):
    github["members"].update(ann="active", bob="pending")
    client.get(f"/offerings/{offering_id}/roster")  # check picks up the states
    with app.app_context():
        for e in db.session.scalars(db.select(RosterEntry)):
            if e.github_login in ("ann", "bob"):
                e.dropped_at = datetime.now(UTC)
        db.session.commit()
    page = client.get(f"/offerings/{offering_id}/roster?show=dropped").text
    assert "Remove dropped people from the organization (2)" in page
    resp = client.post(f"/offerings/{offering_id}/roster/remove-dropped", follow_redirects=True)
    assert "Removed 2 dropped people" in resp.text
    assert github["members"] == {}
    got = states(app)
    assert got["ann"] == got["bob"] == "none"


def test_changing_a_login_forgets_the_old_membership(app, client, offering_id, github, http_mock):
    http_mock.get(f"{API}/users/dee").respond(200, json={"id": 104, "login": "dee"})
    github["members"]["ann"] = "active"
    client.get(f"/offerings/{offering_id}/roster")
    with app.app_context():
        ann = db.session.scalar(db.select(RosterEntry).where(RosterEntry.github_login == "ann"))
    client.post(
        f"/offerings/{offering_id}/roster/entries/{ann.id}",
        data={"github_id": "dee", "role": "student"},
    )
    assert states(app)["dee"] == "unknown"


def test_not_connected_offering_cannot_invite(app, client, offering_id):
    with app.app_context():
        db.session.get(Installation, 777).removed_at = datetime.now(UTC)
        db.session.commit()
    resp = client.post(f"/offerings/{offering_id}/roster/invitations", follow_redirects=True)
    assert "GitHub organization first" in resp.text
    assert "GitHub organization to send invitations" in resp.text


def test_status_token_changes_with_membership(app, client, offering_id, github):
    first = client.get(f"/offerings/{offering_id}/roster/status.json").json["token"]
    client.post(f"/offerings/{offering_id}/roster/invitations")
    assert client.get(f"/offerings/{offering_id}/roster/status.json").json["token"] != first
