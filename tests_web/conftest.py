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
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from webapp import create_app  # noqa: E402
from webapp.extensions import db  # noqa: E402
from webapp.tasks import huey  # noqa: E402

WEBHOOK_SECRET = "test-webhook-secret"


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
        "BASE_URL": "http://localhost:5000/",
        "GITHUB_APP_ID": "12345",
        "GITHUB_APP_SLUG": "coursekit-test",
        "GITHUB_APP_CLIENT_ID": "Iv23test",
        "GITHUB_APP_CLIENT_SECRET": "client-secret",
        "GITHUB_WEBHOOK_SECRET": WEBHOOK_SECRET,
        "GITHUB_APP_PRIVATE_KEY_PATH": str(key_file),
    }


@pytest.fixture
def app(environ):
    from webapp import config

    settings = config.load(environ)
    settings.update(TESTING=True, DEV_ROUTES=False)
    app = create_app(settings)
    huey.immediate = True  # tasks run inline, in memory
    with app.app_context():
        db.create_all()
    yield app
    huey.immediate = False


@pytest.fixture
def client(app):
    return app.test_client()
