"""
webhooks.py, POST /webhooks/github.
===================================

GitHub sends every event for every organization that installed the App to
this one URL (through smee.io in development). The handler does as little
as possible, because GitHub waits only ten seconds for an answer:

    1. verify the signature (X-Hub-Signature-256, HMAC of the raw body with
       GITHUB_WEBHOOK_SECRET); anything unsigned or mis-signed gets 401
    2. record the delivery, once: a redelivery with the same ID is a no-op
    3. hand it to the worker and answer 202

GitHub does not retry failed deliveries by itself. Anything slow belongs in
tasks.py, never here.

When CSRF protection arrives (Flask-WTF), this endpoint must be exempt: the
signature is its protection.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from flask import Blueprint, current_app, request

from ..extensions import db
from ..models import WebhookDelivery

log = logging.getLogger(__name__)

bp = Blueprint("webhooks", __name__)


def signature_valid(secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@bp.post("/webhooks/github")
def receive():
    from ..tasks import process_webhook

    body = request.get_data()
    if not signature_valid(
        current_app.config["GITHUB_WEBHOOK_SECRET"],
        body,
        request.headers.get("X-Hub-Signature-256"),
    ):
        log.warning(
            "webhook rejected: signature missing or invalid "
            "(does GITHUB_WEBHOOK_SECRET match the App's webhook secret?)"
        )
        return "invalid signature\n", 401

    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    event = request.headers.get("X-GitHub-Event", "")
    if not delivery_id or not event:
        return "missing X-GitHub-Delivery or X-GitHub-Event\n", 400

    if (
        db.session.scalar(
            db.select(WebhookDelivery.id).where(WebhookDelivery.delivery_id == delivery_id)
        )
        is not None
    ):
        log.info("webhook %s (%s) already received; ignored", delivery_id, event)
        return "already received\n", 200

    payload = request.get_json(silent=True) or {}
    delivery = WebhookDelivery(
        delivery_id=delivery_id,
        event=event,
        action=payload.get("action"),
        installation_id=(payload.get("installation") or {}).get("id"),
        payload=payload,
    )
    db.session.add(delivery)
    db.session.commit()
    log.info(
        "webhook %s received: %s%s, signature valid",
        delivery_id,
        event,
        f".{delivery.action}" if delivery.action else "",
    )

    process_webhook(delivery.id)
    return "accepted\n", 202
