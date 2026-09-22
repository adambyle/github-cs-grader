import hashlib
import hmac
import json

from conftest import WEBHOOK_SECRET

from webapp.extensions import db
from webapp.models import WebhookDelivery

PUSH = {
    "ref": "refs/heads/main",
    "repository": {"full_name": "coursekit-dev/cs108-a01-jsmith"},
    "head_commit": {"id": "abc1234def"},
    "installation": {"id": 42},
}


def post(client, payload, delivery="d-1", event="push", secret=WEBHOOK_SECRET, signature=None):
    body = json.dumps(payload).encode()
    if signature is None:
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "Content-Type": "application/json",
    }
    if signature:
        headers["X-Hub-Signature-256"] = signature
    return client.post("/webhooks/github", data=body, headers=headers)


def deliveries(app):
    with app.app_context():
        return db.session.scalars(db.select(WebhookDelivery)).all()


def test_signed_delivery_is_recorded_and_processed(app, client, caplog):
    caplog.set_level("INFO")
    resp = post(client, PUSH)
    assert resp.status_code == 202
    [d] = deliveries(app)
    assert (d.event, d.installation_id) == ("push", 42)
    # huey runs inline in tests, so the worker's log line is already there
    assert "push to coursekit-dev/cs108-a01-jsmith" in caplog.text


def test_redelivery_is_ignored(app, client):
    assert post(client, PUSH).status_code == 202
    assert post(client, PUSH).status_code == 200
    assert len(deliveries(app)) == 1


def test_wrong_secret_is_rejected(app, client):
    assert post(client, PUSH, secret="not-the-secret").status_code == 401
    assert deliveries(app) == []


def test_unsigned_is_rejected(app, client):
    assert post(client, PUSH, signature="").status_code == 401


def test_missing_delivery_id_is_a_bad_request(client):
    assert post(client, PUSH, delivery="").status_code == 400
