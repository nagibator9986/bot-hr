"""Промоутеры и промокоды.

Promoter — сотрудник/партнёр с особой реф-ссылкой (повышенный бонус).
PromoCode — код доступа: активирует подписку без оплаты деньгами.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import Tariff
from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    pass


class Promoter(Base, TimestampMixin):
    """Промоутер — приглашает друзей по особой ссылке с повышенным бонусом.

    `code` подставляется в ссылку: t.me/<bot>?start=promo_<code>.
    `user_id` — аккаунт, на баланс которого падает бонус (если промоутер сам
    пользуется ботом). Если не привязан — бонусы копятся как total_earned, а
    выплату админ делает вручную.
    """

    __tablename__ = "promoters"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    bonus_amount: Mapped[int] = mapped_column(Numeric(10, 0), nullable=False)
    total_earned: Mapped[int] = mapped_column(Numeric(10, 0), default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<Promoter id={self.id} code={self.code} name={self.name}>"


class PromoCode(Base, TimestampMixin):
    """Код доступа: активирует подписку выбранного тарифа без оплаты деньгами."""

    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    tariff: Mapped[Tariff] = mapped_column(String(32), nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # None → без ограничения числа активаций
    max_uses: Mapped[int | None] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<PromoCode code={self.code} tariff={self.tariff} used={self.used_count}>"
