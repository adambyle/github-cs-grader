"""
config.py, every setting the web app reads, from the environment.
================================================================

All settings come from environment variables (compose.yaml loads them from
.env; see .env.example). `load()` reads them all at once and raises
ConfigError naming EVERY missing one, so a half-filled .env fails at startup
with one readable message instead of a KeyError in the middle of a request.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

# The fixed path compose.yaml mounts the App's private key at.
DEFAULT_PRIVATE_KEY_PATH = "/run/secrets/github-app.pem"

REQUIRED = [
    "FLASK_SECRET_KEY",
    "DATABASE_URL",
    "BASE_URL",
    "GITHUB_APP_ID",
    "GITHUB_APP_SLUG",
    "GITHUB_APP_CLIENT_ID",
    "GITHUB_APP_CLIENT_SECRET",
    "GITHUB_WEBHOOK_SECRET",
]


class ConfigError(RuntimeError):
    pass


def load(environ: Mapping[str, str] = os.environ) -> dict:
    """Flask config values from the environment. Raises ConfigError."""
    missing = [name for name in REQUIRED if not environ.get(name, "").strip()]
    key_path = Path(environ.get("GITHUB_APP_PRIVATE_KEY_PATH") or DEFAULT_PRIVATE_KEY_PATH)
    problems = []
    if missing:
        problems.append("missing from the environment (fill them in .env): " + ", ".join(missing))
    if not key_path.is_file():
        problems.append(
            f"no GitHub App private key at {key_path} (check GITHUB_APP_PRIVATE_KEY_FILE in .env)"
        )
    if problems:
        raise ConfigError("; ".join(problems))

    return {
        "SECRET_KEY": environ["FLASK_SECRET_KEY"],
        "SQLALCHEMY_DATABASE_URI": environ["DATABASE_URL"],
        "BASE_URL": environ["BASE_URL"].rstrip("/"),
        "GITHUB_APP_ID": environ["GITHUB_APP_ID"],
        "GITHUB_APP_SLUG": environ["GITHUB_APP_SLUG"],
        "GITHUB_APP_CLIENT_ID": environ["GITHUB_APP_CLIENT_ID"],
        "GITHUB_APP_CLIENT_SECRET": environ["GITHUB_APP_CLIENT_SECRET"],
        "GITHUB_WEBHOOK_SECRET": environ["GITHUB_WEBHOOK_SECRET"],
        "GITHUB_APP_PRIVATE_KEY_PATH": str(key_path),
    }
