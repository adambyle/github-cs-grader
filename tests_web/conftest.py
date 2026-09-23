"""
Shared fixtures. No network and no .env: every test builds its own settings,
a throwaway RSA key and a SQLite file in a temporary folder, and GitHub is
faked with respx.

    docker compose run --rm web pytest
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import UTC, datetime, timedelta

# Before anything imports webapp.tasks: keep the queue out of /data.
os.environ["HUEY_DB"] = os.path.join(tempfile.mkdtemp(prefix="coursekit-test-"), "huey.db")

import httpx  # noqa: E402
import pytest  # noqa: E402
import respx  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from webapp import create_app  # noqa: E402
from webapp.extensions import db  # noqa: E402
from webapp.github.app_auth import API  # noqa: E402
from webapp.models import Course, CourseStaff, Installation, Offering, RosterEntry  # noqa: E402
from webapp.tasks import huey  # noqa: E402

WEBHOOK_SECRET = "test-webhook-secret"
TOKEN_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def http_mock():
    """Any HTTP request a test has not mocked fails at once, instead of
    quietly reaching the real GitHub. Tests can add routes to it by taking
    this fixture, or use their own @respx.mock, which takes precedence."""
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture(scope="session")
def rsa_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    return key, pem


@pytest.fixture
def key_file(tmp_path, rsa_key):
    path = tmp_path / "app.pem"
    path.write_text(rsa_key[1])
    return path


@pytest.fixture
def environ(tmp_path, key_file):
    """A complete, valid environment, as .env would provide."""
    return {
        "FLASK_SECRET_KEY": "test",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}",
        "BASE_URL": "http://localhost/",  # the test client's host; trailing slash on purpose
        "GITHUB_APP_ID": "12345",
        "GITHUB_APP_SLUG": "coursekit-test",
        "GITHUB_APP_CLIENT_ID": "Iv23test",
        "GITHUB_APP_CLIENT_SECRET": "client-secret",
        "GITHUB_WEBHOOK_SECRET": WEBHOOK_SECRET,
        "GITHUB_APP_PRIVATE_KEY_PATH": str(key_file),
        "TOKEN_ENCRYPTION_KEY": TOKEN_KEY,
    }


@pytest.fixture
def app(environ):
    from webapp import config

    settings = config.load(environ)
    # CSRF is off for most tests; test_auth.py turns it on to check it.
    settings.update(TESTING=True, DEV_ROUTES=False, WTF_CSRF_ENABLED=False)
    app = create_app(settings)
    huey.immediate = True  # tasks run inline, in memory
    with app.app_context():
        db.create_all()
    yield app
    huey.immediate = False


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user(app):
    """make_user(login, mode=...) -> User, saved, with a stored token."""
    from webapp import auth
    from webapp.github.user_auth import TokenSet
    from webapp.models import User

    counter = iter(range(1000, 2000))

    def make(login="ada", mode="student", **fields):
        with app.app_context():
            fields.setdefault("github_id", next(counter))
            user = User(login=login, mode=mode, **fields)
            db.session.add(user)
            auth.store_tokens(user, TokenSet(f"ghu_{login}", None, None, None))
            db.session.commit()
            db.session.refresh(user)
            db.session.expunge(user)
            return user

    return make


def sign_in_as(client, user):
    """Sign a user in by writing the session directly (no OAuth round trip)."""
    with client.session_transaction() as s:
        s["user_id"] = user.id


# -- a connected offering and a fake org, for membership and repo tests --------

ORG = "cs108-26fa"  # the fake org


@pytest.fixture
def fake_org(http_mock):
    """A fake GitHub org, and its installation token. The offering from
    `org_offering` is connected to it. `members` maps lowercased login -> 'active' or 'pending';
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
def org_offering(app, make_user, client):
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
