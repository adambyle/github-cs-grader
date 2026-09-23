"""
handlers.py, what each webhook event does.
==========================================

tasks.process_webhook() calls dispatch() in the worker. One function per
event, registered with @on("event") (every action) or @on("event", "action").
Events nobody handles are logged and dropped. Handlers run inside an app
context and may commit.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from ..extensions import db
from ..models import Installation, WebhookDelivery
from . import installations
from .app_auth import github_app

log = logging.getLogger(__name__)

Handler = Callable[[dict], None]
_handlers: dict[tuple[str, str | None], Handler] = {}


def on(event: str, *actions: str):
    def register(fn: Handler) -> Handler:
        for action in actions or (None,):
            _handlers[(event, action)] = fn
        return fn

    return register


def dispatch(delivery: WebhookDelivery) -> None:
    handler = _handlers.get((delivery.event, delivery.action)) or _handlers.get(
        (delivery.event, None)
    )
    label = delivery.event + (f".{delivery.action}" if delivery.action else "")
    if handler is None:
        log.info("no handler for %s; ignored", label)
        return
    handler(delivery.payload)


@on("installation", "created", "unsuspend", "new_permissions_accepted")
def installation_refreshed(payload: dict) -> None:
    inst = installations.record(payload["installation"])
    db.session.commit()
    log.info("installation %s on %s: %s", inst.id, inst.account_login, payload["action"])


@on("installation", "suspend")
def installation_suspended(payload: dict) -> None:
    inst = installations.record(payload["installation"])
    github_app().forget_token(inst.id)
    db.session.commit()
    log.info("installation %s on %s suspended", inst.id, inst.account_login)


@on("installation", "deleted")
def installation_deleted(payload: dict) -> None:
    inst = installations.mark_removed(payload["installation"]["id"])
    github_app().forget_token(payload["installation"]["id"])
    db.session.commit()
    who = inst.account_login if inst else payload["installation"]["id"]
    log.info("the App was uninstalled from %s", who)


@on("installation_repositories")
def installation_repositories(payload: dict) -> None:
    installations.record(payload["installation"])
    db.session.commit()


@on("organization", "renamed")
def organization_renamed(payload: dict) -> None:
    # Organization events carry only the installation's id, not its record.
    inst = db.session.get(Installation, payload["installation"]["id"])
    if inst is not None:
        inst.account_login = payload["organization"]["login"]
        db.session.commit()
    log.info("org renamed to %s", payload["organization"]["login"])


@on("organization", "member_invited", "member_added", "member_removed")
def organization_membership(payload: dict) -> None:
    from .. import membership

    action = payload["action"]
    if action == "member_invited":
        invitation = payload.get("invitation") or {}
        user, login, state = payload.get("user"), invitation.get("login"), "invited"
    else:
        user = (payload.get("membership") or {}).get("user")
        login, state = None, "active" if action == "member_added" else "none"
    changed = membership.from_webhook(payload["installation"]["id"], user, login, state)
    log.info(
        "%s in %s: %s roster row(s) now %s",
        action,
        payload["organization"]["login"],
        changed,
        state,
    )


@on("ping")
def ping(payload: dict) -> None:
    log.info("GitHub says hello: %s", payload.get("zen", ""))


@on("push")
def push(payload: dict) -> None:
    repo = (payload.get("repository") or {}).get("full_name", "-")
    head = (payload.get("head_commit") or {}).get("id", "")[:7] or "-"
    log.info("push to %s (%s), head %s", repo, payload.get("ref"), head)
