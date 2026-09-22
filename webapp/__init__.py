"""
webapp, the coursekit web server.
=================================

    docker compose up --build            # see expansion/agent-spec/create-environment.md

`create_app()` is the Flask entry point (`flask --app webapp ...`). Settings
come from the environment through config.load(); tests pass their own.
"""

from __future__ import annotations

import logging
import os

from flask import Flask

from . import config
from .extensions import csrf, db, migrate


def create_app(settings: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(config.load() if settings is None else settings)
    app.config.setdefault("DEV_ROUTES", os.environ.get("COURSEKIT_DEV_ROUTES") == "1")
    app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", {"connect_args": {"timeout": 15}})

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)  # batch mode: SQLite cannot ALTER much
    csrf.init_app(app)
    from . import models  # noqa: F401  (registers the tables with SQLAlchemy)
    from .access import load_current_user
    from .github.webhooks import bp as webhooks_bp
    from .routes.auth import bp as auth_bp
    from .routes.health import bp as health_bp
    from .routes.home import bp as home_bp

    app.before_request(load_current_user)
    app.register_blueprint(auth_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(webhooks_bp)
    csrf.exempt(webhooks_bp)  # GitHub signs its requests instead
    if app.config["DEV_ROUTES"]:
        from .routes.dev import bp as dev_bp

        app.register_blueprint(dev_bp)

    return app
