"""Org invitations and membership (membership.py, the roster page's org
panel, and the organization.* webhooks)."""

from datetime import UTC, datetime, timedelta

import httpx
from conftest import ORG
from test_handlers import deliver

from webapp.extensions import db
from webapp.github.app_auth import API
from webapp.models import Installation, Offering, RosterEntry


def states(app):
    with app.app_context():
        return {
            e.github_login or e.username: e.membership
            for e in db.session.scalars(db.select(RosterEntry))
        }


def test_send_invitations_invites_participants_only(app, client, org_offering, fake_org):
    fake_org["members"]["bob"] = "active"
    page = client.get(f"/offerings/{org_offering}/roster").text  # starts a check
    assert "Send invitations (2)" in page
    resp = client.post(f"/offerings/{org_offering}/roster/invitations", follow_redirects=True)
    assert "Sending 2 invitations" in resp.text
    got = states(app)
    assert (got["ann"], got["bob"], got["cy"]) == ("invited", "active", "invited")
    assert got["nogh"] == "unknown"  # no GitHub username: never checked or invited
    invited = sorted(login for method, login in fake_org["calls"] if method == "INVITE")
    assert invited == ["ann", "cy"]
    # sending again invites nobody
    fake_org["calls"].clear()
    client.post(f"/offerings/{org_offering}/roster/invitations")
    assert not any(method == "INVITE" for method, _ in fake_org["calls"])


def test_the_daily_cap_pauses_and_keeps_the_rest_queued(app, client, org_offering, fake_org):
    fake_org["refuse"] = httpx.Response(
        422,
        json={
            "message": "Validation Failed",
            "errors": [{"message": "Over invitation rate limit"}],
        },
    )
    client.post(f"/offerings/{org_offering}/roster/invitations")
    got = states(app)
    assert got["ann"] == got["bob"] == got["cy"] == "queued"
    with app.app_context():
        offering = db.session.get(Offering, org_offering)
        resume = offering.invites_resume_at.replace(tzinfo=UTC)
        assert resume > datetime.now(UTC) + timedelta(hours=23)
    page = client.get(f"/offerings/{org_offering}/roster").text
    assert "3 more will be sent automatically" in page


def test_a_refused_invitation_is_failed_with_the_reason_and_can_be_resent(
    app, client, org_offering, fake_org
):
    fake_org["refuse"] = httpx.Response(422, json={"message": "Invitee is blocked"})
    client.post(f"/offerings/{org_offering}/roster/invitations")
    assert states(app)["ann"] == "failed"
    page = client.get(f"/offerings/{org_offering}/roster").text
    assert "Invitee is blocked" in page and "Resend" in page
    fake_org["refuse"] = None
    with app.app_context():
        ann = db.session.scalar(db.select(RosterEntry).where(RosterEntry.github_login == "ann"))
    client.post(f"/offerings/{org_offering}/roster/entries/{ann.id}/invite")
    assert states(app)["ann"] == "invited"


def test_webhooks_move_rows_between_states(app, client, org_offering, fake_org):
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


def test_removing_dropped_people(app, client, org_offering, fake_org):
    fake_org["members"].update(ann="active", bob="pending")
    client.get(f"/offerings/{org_offering}/roster")  # check picks up the states
    with app.app_context():
        for e in db.session.scalars(db.select(RosterEntry)):
            if e.github_login in ("ann", "bob"):
                e.dropped_at = datetime.now(UTC)
        db.session.commit()
    page = client.get(f"/offerings/{org_offering}/roster?show=dropped").text
    assert "Remove dropped people from the organization (2)" in page
    resp = client.post(f"/offerings/{org_offering}/roster/remove-dropped", follow_redirects=True)
    assert "Removed 2 dropped people" in resp.text
    assert fake_org["members"] == {}
    got = states(app)
    assert got["ann"] == got["bob"] == "none"


def test_changing_a_login_forgets_the_old_membership(
    app, client, org_offering, fake_org, http_mock
):
    http_mock.get(f"{API}/users/dee").respond(200, json={"id": 104, "login": "dee"})
    fake_org["members"]["ann"] = "active"
    client.get(f"/offerings/{org_offering}/roster")
    with app.app_context():
        ann = db.session.scalar(db.select(RosterEntry).where(RosterEntry.github_login == "ann"))
    client.post(
        f"/offerings/{org_offering}/roster/entries/{ann.id}",
        data={"github_id": "dee", "role": "student"},
    )
    assert states(app)["dee"] == "unknown"


def test_not_connected_offering_cannot_invite(app, client, org_offering):
    with app.app_context():
        db.session.get(Installation, 777).removed_at = datetime.now(UTC)
        db.session.commit()
    resp = client.post(f"/offerings/{org_offering}/roster/invitations", follow_redirects=True)
    assert "GitHub organization first" in resp.text
    assert "GitHub organization to send invitations" in resp.text


def test_status_token_changes_with_membership(app, client, org_offering, fake_org):
    first = client.get(f"/offerings/{org_offering}/roster/status.json").json["token"]
    client.post(f"/offerings/{org_offering}/roster/invitations")
    assert client.get(f"/offerings/{org_offering}/roster/status.json").json["token"] != first
