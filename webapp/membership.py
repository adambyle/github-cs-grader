"""
membership.py, whether each roster row is in the offering's GitHub org.
=======================================================================

Plan: expansion/agent-spec/github-integration.md, sections 6.2 to 6.4.

A row's `membership` is one of unknown, none, queued, invited, active or
failed (models.MEMBERSHIPS). It is learned three ways:

    check()            GET /orgs/{org}/memberships/{login}, for the whole
                       roster: in the background when the roster page is
                       opened (at most every CHECK_EVERY), and nightly
    webhooks           organization.member_invited / member_added /
                       member_removed (github/handlers.py), within seconds
    send_invitations() which checks each row again just before inviting

INVITING
    Only rows that participate (student or test, not dropped) and whose
    GitHub username was found (so the numeric id is known) are invited, by
    id, as the CLI's `assign` did. The Send button marks them `queued`; the
    task works through the queued rows, one commit per row so the page can
    show progress. Running it again is always safe: anyone already invited
    or a member is skipped.

    New free-plan orgs may send 50 invitations a day (spike S3). When GitHub
    refuses for that reason, or any rate limit, the task stops, records
    when to resume (Offering.invites_resume_at), and is scheduled again for
    then. The rest stay queued.

REMOVING
    Only ever by an explicit action (a button, with a confirmation). It also
    cancels a pending invitation, and ends access to the org's repos.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from .extensions import db
from .github import api
from .github.app_auth import GitHubError, github_app
from .models import Installation, Offering, RosterEntry

log = logging.getLogger(__name__)

CHECK_EVERY = timedelta(minutes=10)
DEFAULT_BACKOFF = timedelta(hours=24)

STATE_FROM_GITHUB = {"active": "active", "pending": "invited", "none": "none"}


class NotConnected(RuntimeError):
    """The offering has no working GitHub org."""


def _now() -> datetime:
    return datetime.now(UTC)


def aware(when: datetime | None) -> datetime | None:
    # SQLite hands datetimes back without a timezone; they were stored in UTC.
    return when.replace(tzinfo=UTC) if when is not None and when.tzinfo is None else when


def org_token(offering: Offering) -> tuple[str, str]:
    """(installation token, org login) for acting in the offering's org."""
    inst = offering.installation
    if inst is None or inst.state != "connected":
        raise NotConnected(f"{offering.course.code} {offering.label} has no connected org")
    return github_app().installation_token(inst.id), inst.account_login


def can_invite(entry: RosterEntry) -> bool:
    return entry.participates and entry.github_status == "ok" and entry.github_user_id is not None


def to_invite(offering: Offering) -> list[RosterEntry]:
    """Rows the Send invitations button would invite."""
    return [e for e in offering.roster if can_invite(e) and e.membership in ("unknown", "none")]


def set_state(entry: RosterEntry, state: str, error: str | None = None) -> None:
    entry.membership = state
    entry.membership_error = error
    entry.checked_at = _now()
    if state == "invited" and entry.invited_at is None:
        entry.invited_at = _now()


def queue(entries: list[RosterEntry]) -> int:
    """Mark rows to be invited by the next send_invitations(). Not committed."""
    for e in entries:
        e.membership, e.membership_error = "queued", None
    return len(entries)


def check_due(offering: Offering) -> bool:
    """Should the roster page ask for a background check?"""
    last = aware(offering.memberships_checked_at)
    return (
        offering.installation is not None
        and offering.installation.state == "connected"
        and (last is None or _now() - last > CHECK_EVERY)
        and any(e.github_login and e.github_status == "ok" for e in offering.roster)
    )


def check(offering: Offering) -> None:
    """Re-read the membership of every row with a known GitHub username.
    Queued rows stay queued unless they turn out to be invited or members
    already. Commits."""
    token, org = org_token(offering)
    offering.memberships_checked_at = _now()
    for e in offering.roster:
        if e.github_status != "ok":
            continue
        state = STATE_FROM_GITHUB[api.membership_state(token, org, e.github_login)]
        if e.membership == "queued" and state == "none":
            continue
        if e.membership == "failed" and state == "none":
            continue  # keep the reason until someone resends
        set_state(e, state)
    db.session.commit()


def send_invitations(offering: Offering) -> datetime | None:
    """Invite every queued row. Returns when to try again if GitHub's cap or
    a rate limit stopped it, else None. Commits after each row."""
    resume = aware(offering.invites_resume_at)
    if resume is not None and resume > _now():
        return resume
    offering.invites_resume_at = None
    db.session.commit()
    token, org = org_token(offering)

    for e in sorted(offering.roster, key=lambda x: x.id):
        if e.membership != "queued":
            continue
        if not can_invite(e):  # dropped or changed since it was queued
            set_state(e, "none")
            db.session.commit()
            continue
        state = STATE_FROM_GITHUB[api.membership_state(token, org, e.github_login)]
        if state != "none":
            set_state(e, state)
            db.session.commit()
            continue
        try:
            api.invite(token, org, e.github_user_id)
        except api.InviteRefused as exc:
            if exc.limited:
                when = (
                    datetime.fromtimestamp(exc.retry_at, UTC)
                    if exc.retry_at
                    else _now() + DEFAULT_BACKOFF
                )
                offering.invites_resume_at = when
                db.session.commit()
                log.info("invitations for offering %s paused until %s: %s", offering.id, when, exc)
                return when
            set_state(e, "failed", str(exc)[:500])
        else:
            set_state(e, "invited")
        db.session.commit()
    return None


def remove(offering: Offering, entry: RosterEntry) -> None:
    """Take someone out of the org (or cancel their invitation). Commits."""
    token, org = org_token(offering)
    api.remove_member(token, org, entry.github_login)
    set_state(entry, "none")
    db.session.commit()


def removable(offering: Offering) -> list[RosterEntry]:
    """Dropped rows still in the org or invited to it."""
    return [
        e
        for e in offering.roster
        if e.dropped_at is not None and e.membership in ("invited", "active")
    ]


def from_webhook(installation_id: int, user: dict | None, login: str | None, state: str) -> int:
    """Record a membership change GitHub told us about, on every offering
    using that org. Returns the number of rows changed. Commits."""
    user_id = (user or {}).get("id")
    login = ((user or {}).get("login") or login or "").lower()
    if not user_id and not login:
        return 0
    changed = 0
    offerings = db.session.scalars(
        db.select(Offering).join(Installation).where(Installation.id == installation_id)
    )
    for offering in offerings:
        for e in offering.roster:
            if (user_id and e.github_user_id == user_id) or (
                login and e.github_login.lower() == login
            ):
                set_state(e, state)
                changed += 1
    db.session.commit()
    return changed


def summary(offering: Offering) -> dict:
    """Counts for the roster page and the offering page."""
    out = {"active": 0, "invited": 0, "queued": 0, "failed": 0, "not_invited": 0, "cannot": 0}
    for e in offering.roster:
        if not e.participates:
            continue
        if e.membership in ("active", "invited", "queued", "failed"):
            out[e.membership] += 1
        elif can_invite(e):
            out["not_invited"] += 1
        else:
            out["cannot"] += 1  # no GitHub username, or not found
    out["removable"] = len(removable(offering))
    return out


def safe_check(offering: Offering) -> None:
    """check(), logging instead of raising: for background jobs."""
    try:
        check(offering)
    except (GitHubError, NotConnected) as exc:
        db.session.rollback()
        log.warning("membership check for offering %s failed: %s", offering.id, exc)
