"""
dev.py, pages that prove the development setup works.
=====================================================

Registered only when COURSEKIT_DEV_ROUTES=1 (compose.yaml sets it for the
web service). Never enable in production: /dev/github shows which
organizations installed the App.

    /dev/github   the App's installations, and whether a token can be minted
                  for each: proves the App ID and private key
    /dev/worker   enqueues the ping task and waits for the answer: proves the
                  worker is running and shares the queue with the web server
"""

from __future__ import annotations

from flask import Blueprint, current_app, render_template
from huey.exceptions import HueyException

from ..github import installations
from ..github.app_auth import GitHubError, github_app

bp = Blueprint("dev", __name__, url_prefix="/dev")


@bp.get("/github")
def github():
    gh = github_app()
    error, rows = None, []
    try:
        installations.sync(gh)  # keep the installations table honest too
        for inst in gh.installations():
            row = {
                "id": inst["id"],
                "account": inst["account"]["login"],
                "type": inst["account"]["type"],
                "selection": inst["repository_selection"],
                "repos": None,
                "error": None,
            }
            try:
                row["repos"] = gh.installation_get(
                    inst["id"], "/installation/repositories?per_page=1"
                )["total_count"]
            except GitHubError as exc:
                row["error"] = str(exc)
            rows.append(row)
    except (GitHubError, OSError, ValueError) as exc:
        error = str(exc)
    install_url = (
        f"https://github.com/apps/{current_app.config['GITHUB_APP_SLUG']}/installations/new"
    )
    return render_template("dev_github.html", rows=rows, error=error, install_url=install_url)


@bp.get("/worker")
def worker():
    from ..tasks import ping

    try:
        answer = ping().get(blocking=True, timeout=10)
        return f"worker answered: {answer}\n", 200, {"Content-Type": "text/plain"}
    except HueyException:
        return (
            "no answer from the worker within 10 seconds; is it running? "
            "(docker compose logs worker)\n",
            503,
            {"Content-Type": "text/plain"},
        )
