"""Database models."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db


def _now() -> datetime:
    return datetime.now(UTC)


MODES = ("student", "instructor")


class User(db.Model):
    """Someone who has signed in with GitHub.

    Found by `github_id`, GitHub's numeric account id, which survives a
    rename; `login` is refreshed at every sign-in. `mode` is the view they
    chose (student or instructor). It grants nothing by itself: see access.py.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    login: Mapped[str] = mapped_column(String(39))
    name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    mode: Mapped[str] = mapped_column(String(16), default="student")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    token: Mapped[UserToken | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def display_name(self) -> str:
        return self.name or self.login


class UserToken(db.Model):
    """The user's GitHub access and refresh tokens, Fernet-encrypted
    (crypto.py). Needed when coursekit acts as the person rather than as the
    App: listing the orgs they can install into, accepting their invitation."""

    __tablename__ = "user_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    access_token_enc: Mapped[str] = mapped_column(Text)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="token")


class WebhookDelivery(db.Model):
    """One webhook GitHub delivered, after its signature checked out.

    Keyed by GitHub's delivery ID, so a redelivery (from the App's Recent
    Deliveries page) is recognized rather than processed twice.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[str] = mapped_column(String(64), unique=True)
    event: Mapped[str] = mapped_column(String(64))
    action: Mapped[str | None] = mapped_column(String(64))
    installation_id: Mapped[int | None]
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    payload: Mapped[dict] = mapped_column(JSON)


class Installation(db.Model):
    """One org (or account) that installed the GitHub App. The primary key is
    GitHub's installation id. Kept current by installation webhooks
    (github/handlers.py) and by github/installations.sync()."""

    __tablename__ = "installations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    account_id: Mapped[int] = mapped_column(BigInteger)
    account_login: Mapped[str] = mapped_column(String(39))
    account_type: Mapped[str] = mapped_column(String(32))  # "Organization" or "User"
    repository_selection: Mapped[str] = mapped_column(String(16))  # "all" or "selected"
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    @property
    def state(self) -> str:
        """connected | suspended | removed"""
        if self.removed_at is not None:
            return "removed"
        if self.suspended_at is not None:
            return "suspended"
        return "connected"


class Course(db.Model):
    """A course that is taught again and again (CS 108). Semesters are
    Offerings. Managed by its staff; see access.py."""

    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    staff: Mapped[list[CourseStaff]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    offerings: Mapped[list[Offering]] = relationship(
        back_populates="course", cascade="all, delete-orphan", order_by="Offering.created_at.desc()"
    )


STAFF_ROLES = ("owner", "instructor")


class CourseStaff(db.Model):
    """Who may manage a course: its creator (owner) and co-instructors."""

    __tablename__ = "course_staff"
    __table_args__ = (UniqueConstraint("course_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16), default="instructor")

    course: Mapped[Course] = relationship(back_populates="staff")
    user: Mapped[User] = relationship()


class Offering(db.Model):
    """One semester of a course (Fall 2026), with its own GitHub org
    (through the App's installation there) and, later, its own roster."""

    __tablename__ = "offerings"
    __table_args__ = (UniqueConstraint("course_id", "label"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(64))
    installation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("installations.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    course: Mapped[Course] = relationship(back_populates="offerings")
    installation: Mapped[Installation | None] = relationship()

    @property
    def org_login(self) -> str | None:
        return self.installation.account_login if self.installation else None
