"""Промокоды: активация подписки без оплаты деньгами.

Важно: активация по промокоду — это БЕСПЛАТНЫЙ доступ, поэтому реферальный
бонус за неё НЕ начисляется (см. ReferralService.grant_on_payment, который
зовётся только на реальной оплате Kaspi).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Tariff
from app.core.exceptions import PromoAlreadyUsedError, PromoInvalidError
from app.db.models.subscription import Subscription
from app.repositories.promo import PromoCodeRepo
from app.repositories.subscription import PaymentRepo, SubscriptionRepo
from app.utils.time import utcnow


class PromoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.codes = PromoCodeRepo(session)
        self.subscriptions = SubscriptionRepo(session)
        self.payments = PaymentRepo(session)

    async def redeem(self, *, user_id: int, code: str) -> Subscription:
        """Активирует подписку по промокоду. Идемпотентно по (код, пользователь)."""
        promo = await self.codes.get_by_code(code.strip())
        now = utcnow()
        if (
            promo is None
            or not promo.is_active
            or (promo.expires_at is not None and promo.expires_at <= now)
            or (promo.max_uses is not None and promo.used_count >= promo.max_uses)
        ):
            raise PromoInvalidError()

        tariff = Tariff(promo.tariff)
        # Запись-платёж промокода: уникальный id гарантирует одну активацию на юзера.
        payment = await self.payments.record(
            user_id=user_id,
            provider="promo",
            provider_payment_id=f"promo:{promo.code}:{user_id}",
            amount=0,
            tariff=tariff,
            raw_payload='{"mode":"promo"}',
        )
        if payment is None:
            raise PromoAlreadyUsedError()

        await self.codes.increment_used(promo)
        sub = await self.subscriptions.create(
            user_id=user_id,
            tariff=tariff,
            started_at=now,
            expires_at=now + timedelta(days=promo.duration_days),
        )
        payment.subscription_id = sub.id
        await self.session.flush()
        return sub
