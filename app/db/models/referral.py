"""Referral, ReferralBalance, WithdrawalRequest — реферальная программа."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import ReferralStatus, WithdrawalStatus
from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class Referral(Base, TimestampMixin):
    """Кто-то привёл нового пользователя.

    Источник — ровно один из двух: обычный пользователь (`referrer_id`) или
    промоутер (`promoter_id`). Уникальность `referee_id` гарантирует один
    источник на приглашённого, независимо от типа.
    """

    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("referrer_id", "referee_id", name="uq_referrer_referee"),
        UniqueConstraint("referee_id", name="uq_referee_once"),  # один источник на пользователя
        CheckConstraint("referrer_id <> referee_id", name="no_self_referral"),
        # ровно один источник: либо обычный реферер, либо промоутер
        CheckConstraint(
            "(referrer_id IS NOT NULL) <> (promoter_id IS NOT NULL)",
            name="exactly_one_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    promoter_id: Mapped[int | None] = mapped_column(
        ForeignKey("promoters.id", ondelete="CASCADE"), index=True
    )
    referee_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    bonus_amount: Mapped[int] = mapped_column(Numeric(10, 0), nullable=False)
    status: Mapped[ReferralStatus] = mapped_column(
        String(16), default=ReferralStatus.PENDING, nullable=False, index=True
    )
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<Referral {self.referrer_id}→{self.referee_id} status={self.status}>"


class ReferralBalance(Base, TimestampMixin):
    """Баланс пользователя по реферальной программе."""

    __tablename__ = "referral_balances"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    balance: Mapped[int] = mapped_column(Numeric(10, 0), default=0, nullable=False)
    total_earned: Mapped[int] = mapped_column(Numeric(10, 0), default=0, nullable=False)
    total_withdrawn: Mapped[int] = mapped_column(Numeric(10, 0), default=0, nullable=False)

    user: Mapped[User] = relationship(back_populates="referral_balance")

    def __repr__(self) -> str:
        return f"<ReferralBalance user={self.user_id} balance={self.balance}>"


class WithdrawalRequest(Base, TimestampMixin):
    """Заявка на вывод реф-бонуса (Kaspi)."""

    __tablename__ = "withdrawal_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(Numeric(10, 0), nullable=False)
    kaspi_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[WithdrawalStatus] = mapped_column(
        String(16), default=WithdrawalStatus.PENDING, nullable=False, index=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admin_note: Mapped[str | None] = mapped_column(String(256))

    def __repr__(self) -> str:
        return f"<WithdrawalRequest id={self.id} user={self.user_id} amount={self.amount}>"
