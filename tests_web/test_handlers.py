import hashlib
import hmac
import itertools
import json

from conftest import WEBHOOK_SECRET

from webapp.extensions import db
from webapp.models import Installation

INSTALL = {
    "id": 777,
    "account": {"id": 55, "login": "cs108-26fa", "type": "Organization"},
    "repository_selection": "all",
    "permissions": {"members": "write"},
    "suspended_at": None,
}
_ids = itertools.count()


def deliver(client, event, payload):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    headers = {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": f"d-{next(_ids)}",
        "X-Hub-Signature-256": sig,
        "Content-Type": "application/json",
    }
    assert client.post("/webhooks/github", data=body, headers=headers).status_code == 202


def installation(app):
    with app.app_context():
        return db.session.get(Installation, 777)


def test_install_suspend_unsuspend_uninstall_reinstall(app, client):
    deliver(client, "installation", {"action": "created", "installation": INSTALL})
    assert installation(app).state == "connected"
    suspended = {**INSTALL, "suspended_at": "2026-09-22T12:00:00Z"}
    deliver(client, "installation", {"action": "suspend", "installation": suspended})
    assert installation(app).state == "suspended"
    deliver(client, "installation", {"action": "unsuspend", "installation": INSTALL})
    assert installation(app).state == "connected"
    deliver(client, "installation", {"action": "deleted", "installation": INSTALL})
    assert installation(app).state == "removed"
    deliver(client, "installation", {"action": "created", "installation": INSTALL})
    assert installation(app).state == "connected"


def test_repository_selection_change(app, client):
    deliver(client, "installation", {"action": "created", "installation": INSTALL})
    selected = {**INSTALL, "repository_selection": "selected"}
    deliver(client, "installation_repositories", {"action": "removed", "installation": selected})
    assert installation(app).repository_selection == "selected"


def test_org_rename(app, client):
    deliver(client, "installation", {"action": "created", "installation": INSTALL})
    deliver(
        client,
        "organization",
        {
            "action": "renamed",
            "installation": {"id": 777},
            "organization": {"id": 55, "login": "cs108-fall26"},
        },
    )
    assert installation(app).account_login == "cs108-fall26"


def test_unknown_events_are_ignored(client, caplog):
    caplog.set_level("INFO")
    deliver(client, "star", {"action": "created"})
    assert "no handler for star.created" in caplog.text
