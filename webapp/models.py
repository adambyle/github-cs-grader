"""Database models. Only what the scaffolding needs so far."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from .extensions import db


def _now() -> datetime:
    return datetime.now(UTC)


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
