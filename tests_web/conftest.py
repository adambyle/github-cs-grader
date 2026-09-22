"""
Shared fixtures. No network and no .env: every test builds its own settings,
a throwaway RSA key and a SQLite file in a temporary folder, and GitHub is
faked with respx.

    docker compose run --rm web pytest
"""

from __future__ import annotations

import os
import tempfile

# Before anything imports webapp.tasks: keep the queue out of /data.
os.environ["HUEY_DB"] = os.path.join(tempfile.mkdtemp(prefix="coursekit-test-"), "huey.db")

import pytest  # noqa: E402
import respx  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from webapp import create_app  # noqa: E402
from webapp.extensions import db  # noqa: E402
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
            user = User(github_id=next(counter), login=login, mode=mode, **fields)
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
