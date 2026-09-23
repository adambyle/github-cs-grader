"""
tasks.py, background jobs, run by the worker (`huey_consumer webapp.tasks.huey`).
================================================================================

Anything slow or triggered by GitHub runs here rather than in a web request:
GitHub gives a webhook ten seconds, and grading takes longer than a page
should. The queue is a SQLite file (HUEY_DB), so there is no extra server.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager

from flask import current_app, has_app_context
from huey import SqliteHuey, crontab

log = logging.getLogger(__name__)

huey = SqliteHuey("coursekit", filename=os.environ.get("HUEY_DB", "/data/huey.db"))

_worker_app = None


@contextmanager
def app_context():
    """The Flask app, for database access. Inside a request (or a test) that
    is the current app; in the worker process, one app built on first use."""
    if has_app_context():
        yield current_app
        return
    global _worker_app
    if _worker_app is None:
        from . import create_app

        _worker_app = create_app()
        # create_app() configures root logging; huey's consumer already has
        # its own handler, so stop its lines from printing twice.
        huey_log = logging.getLogger("huey")
        if huey_log.handlers:
            huey_log.propagate = False
    with _worker_app.app_context():
        yield _worker_app


@huey.task()
def ping() -> str:
    """Proves the worker is running; enqueued by /dev/worker."""
    log.info("ping task ran")
    return "pong"


@huey.task()
def process_webhook(delivery_pk: int) -> None:
    """Act on one recorded webhook: github/handlers.py decides what."""
    from .extensions import db
    from .github import handlers
    from .models import WebhookDelivery

    with app_context():
        delivery = db.session.get(WebhookDelivery, delivery_pk)
        if delivery is None:
            log.warning("webhook %s vanished before it was processed", delivery_pk)
            return
        handlers.dispatch(delivery)


@huey.task()
def send_invitations(offering_id: int) -> None:
    """Invite an offering's queued roster rows (membership.py). If GitHub's
    cap stops it, it schedules itself again for when GitHub says."""
    from . import membership
    from .extensions import db
    from .github.app_auth import GitHubError
    from .models import Offering

    with app_context():
        offering = db.session.get(Offering, offering_id)
        if offering is None:
            return
        try:
            resume = membership.send_invitations(offering)
        except (GitHubError, membership.NotConnected) as exc:
            db.session.rollback()
            log.warning("invitations for offering %s stopped: %s", offering_id, exc)
            return
        if resume is not None:
            send_invitations.schedule(args=(offering_id,), eta=resume)


@huey.task()
def check_memberships(offering_id: int) -> None:
    """Re-read which roster rows are in the offering's org."""
    from . import membership
    from .extensions import db
    from .models import Offering

    with app_context():
        offering = db.session.get(Offering, offering_id)
        if offering is not None:
            membership.safe_check(offering)


@huey.periodic_task(crontab(hour="3", minute="15"))
def nightly_sync() -> None:
    """Re-read everything GitHub might have told us about by a webhook we
    missed (GitHub does not retry failed deliveries)."""
    from . import membership
    from .extensions import db
    from .github import installations
    from .github.app_auth import github_app
    from .models import Offering

    with app_context():
        installations.sync(github_app())
        log.info("nightly sync: installations refreshed")
        for offering in db.session.scalars(db.select(Offering)):
            if offering.installation is None or offering.installation.state != "connected":
                continue
            membership.safe_check(offering)
            if any(e.membership == "queued" for e in offering.roster):
                send_invitations(offering.id)
        log.info("nightly sync: memberships rechecked")
