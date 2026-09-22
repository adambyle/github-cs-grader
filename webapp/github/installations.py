"""
installations.py, the local record of where the App is installed.
=================================================================

GitHub is the source of truth; the `installations` table is a copy kept
current three ways:

    webhooks       installation.* events (handlers.py), within seconds
    record()       whenever coursekit reads an installation anyway (the
                   setup URL, the connect dropdown)
    sync()         a full re-read from /app/installations, for anything
                   missed (run nightly, and by /dev/github)
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..extensions import db
from ..models import Installation
from .app_auth import GitHubApp


def _when(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def record(data: dict) -> Installation:
    """Create or refresh an Installation from GitHub's JSON for one (as in a
    webhook's `installation` field or /app/installations). Not committed."""
    inst = db.session.get(Installation, data["id"])
    if inst is None:
        inst = Installation(id=data["id"])
        db.session.add(inst)
    account = data.get("account") or {}
    inst.account_id = account.get("id", inst.account_id)
    inst.account_login = account.get("login", inst.account_login)
    inst.account_type = account.get("type", inst.account_type)
    inst.repository_selection = data.get("repository_selection", inst.repository_selection)
    if "permissions" in data:
        inst.permissions = data["permissions"]
    inst.suspended_at = _when(data.get("suspended_at"))
    inst.removed_at = None
    return inst


def mark_removed(installation_id: int) -> Installation | None:
    inst = db.session.get(Installation, installation_id)
    if inst is not None and inst.removed_at is None:
        inst.removed_at = datetime.now(UTC)
    return inst


def sync(gh: GitHubApp) -> list[Installation]:
    """Re-read every installation from GitHub; anything no longer listed is
    marked removed. Commits."""
    seen = {}
    for data in gh.installations():
        seen[data["id"]] = record(data)
    for inst in db.session.scalars(db.select(Installation)):
        if inst.id not in seen:
            mark_removed(inst.id)
    db.session.commit()
    return list(seen.values())
