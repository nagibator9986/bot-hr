"""Payment — лог всех транзакций. Идемпотентность через provider_payment_id."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import PaymentClaimStatus, PaymentPurpose, PaymentStatus, Tariff
from app.db.base import Base, TimestampMixin


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_payment_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )

    amount: Mapped[int] = mapped_column(Numeric(10, 0), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="KZT", nullable=False)

    tariff: Mapped[Tariff] = mapped_column(String(32), nullable=False)
    purpose: Mapped[PaymentPurpose] = mapped_column(
        String(16), default=PaymentPurpose.SUBSCRIPTION, nullable=False
    )
    status: Mapped[PaymentStatus] = mapped_column(
        String(16), default=PaymentStatus.PENDING, nullable=False, index=True
    )

    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), index=True
    )

    raw_payload: Mapped[str | None] = mapped_column(String)

    def __repr__(self) -> str:
        return f"<Payment id={self.id} user={self.user_id} {self.amount}{self.currency}>"


class PaymentClaim(Base, TimestampMixin):
    """Заявка «Я оплатил через Kaspi». Ждёт ручного подтверждения админом.

    Статическая Kaspi-ссылка не уведомляет бота об оплате, поэтому факт оплаты
    подтверждает админ: при approve создаётся реальный Payment + подписка.
    """

    __tablename__ = "payment_claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tariff: Mapped[Tariff] = mapped_column(String(32), nullable=False)
    amount: Mapped[int] = mapped_column(Numeric(10, 0), nullable=False)
    status: Mapped[PaymentClaimStatus] = mapped_column(
        String(16), default=PaymentClaimStatus.PENDING, nullable=False, index=True
    )
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<PaymentClaim id={self.id} user={self.user_id} status={self.status}>"
