"""Платежи и активация подписок. Идемпотентно по provider_payment_id (ТЗ §10)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.constants import SUBSCRIPTION_DAYS, PaymentStatus, Tariff
from app.core.exceptions import DuplicatePaymentError
from app.db.models.subscription import Subscription
from app.repositories.subscription import PaymentRepo, SubscriptionRepo
from app.utils.time import utcnow


@dataclass(frozen=True, slots=True)
class TariffInfo:
    tariff: Tariff
    price: int
    label: str


def tariff_info(tariff: Tariff) -> TariffInfo:
    table = {
        Tariff.CANDIDATE: TariffInfo(Tariff.CANDIDATE, settings.tariff_candidate, "Кандидат"),
        Tariff.EMPLOYER_BASIC: TariffInfo(
            Tariff.EMPLOYER_BASIC, settings.tariff_employer_basic, "Базовый"
        ),
        Tariff.EMPLOYER_EXTENDED: TariffInfo(
            Tariff.EMPLOYER_EXTENDED, settings.tariff_employer_extended, "Расширенный"
        ),
    }
    return table[tariff]


class PaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.subscriptions = SubscriptionRepo(session)
        self.payments = PaymentRepo(session)

    def kaspi_link(self) -> str | None:
        """Статическая ссылка/QR Kaspi для оплаты (одна на все тарифы)."""
        return settings.kaspi_payment_url

    async def confirm_kaspi_claim(
        self, *, user_id: int, tariff: Tariff, claim_id: int
    ) -> Subscription:
        """Подтверждение оплаты Kaspi админом → активация подписки.

        Идемпотентно по номеру заявки: повторное подтверждение не продлевает.
        """
        info = tariff_info(tariff)
        return await self.confirm_payment(
            user_id=user_id,
            tariff=tariff,
            provider="kaspi",
            provider_payment_id=f"kaspi:claim:{claim_id}",
            amount=info.price,
            raw_payload='{"mode":"kaspi_claim"}',
        )

    async def confirm_payment(
        self,
        *,
        user_id: int,
        tariff: Tariff,
        provider: str,
        provider_payment_id: str,
        amount: int,
        raw_payload: str | None = None,
    ) -> Subscription:
        """Идемпотентно фиксирует платёж и активирует подписку.

        Если такой provider_payment_id уже был — кидаем DuplicatePaymentError.
        """
        info = tariff_info(tariff)
        if amount < info.price:
            raise ValueError(f"amount {amount} < tariff price {info.price}")

        payment = await self.payments.record(
            user_id=user_id,
            provider=provider,
            provider_payment_id=provider_payment_id,
            amount=amount,
            tariff=tariff,
            status=PaymentStatus.SUCCESS,
            raw_payload=raw_payload,
        )
        if payment is None:
            raise DuplicatePaymentError(f"payment {provider_payment_id} already processed")

        now = utcnow()
        sub = await self.subscriptions.create(
            user_id=user_id,
            tariff=tariff,
            started_at=now,
            expires_at=now + timedelta(days=SUBSCRIPTION_DAYS),
        )
        payment.subscription_id = sub.id
        await self.session.flush()
        return sub
