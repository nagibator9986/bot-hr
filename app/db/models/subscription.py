"""Subscription — активная платная подписка пользователя."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import Tariff
from app.db.base import Base, TimestampMixin


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("expires_at > started_at", name="dates_ordered"),
        # один активный тариф на пользователя
        Index(
            "uq_subscriptions_user_active",
            "user_id",
            unique=True,
            postgresql_where="is_active = true",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tariff: Mapped[Tariff] = mapped_column(String(32), nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)

    # Лимиты использования (для работодателя)
    candidates_viewed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Уведомления об окончании (битовая маска по дням: 3, 0)
    reminders_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<Subscription id={self.id} user={self.user_id} tariff={self.tariff}>"
