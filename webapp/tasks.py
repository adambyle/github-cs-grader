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


@huey.periodic_task(crontab(hour="3", minute="15"))
def nightly_sync() -> None:
    """Re-read everything GitHub might have told us about by a webhook we
    missed (GitHub does not retry failed deliveries)."""
    from .github import installations
    from .github.app_auth import github_app

    with app_context():
        installations.sync(github_app())
        log.info("nightly sync: installations refreshed")
