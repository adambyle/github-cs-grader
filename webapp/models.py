"""Database models. Only what the scaffolding needs so far."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, Text
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
