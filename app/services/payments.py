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

    async def create_payment_link(self, *, user_id: int, tariff: Tariff) -> str:
        """Создаёт ссылку/QR для оплаты у провайдера.

        MVP: provider=manual → возвращаем плейсхолдер. Для Telegram Payments/Kaspi
        реализуй отдельный класс-провайдер (см. провайдер-паттерн).
        """
        info = tariff_info(tariff)
        if settings.payment_provider in {"manual", "simulation"}:
            return f"https://example.com/pay?user={user_id}&amount={info.price}"
        # TODO: подключить реальные провайдеры
        raise NotImplementedError(f"Provider {settings.payment_provider} not implemented")

    async def simulate_payment(self, *, user_id: int, tariff: Tariff) -> Subscription:
        """Тестовая активация подписки без внешнего провайдера."""
        info = tariff_info(tariff)
        now = utcnow()
        return await self.confirm_payment(
            user_id=user_id,
            tariff=tariff,
            provider="simulation",
            provider_payment_id=f"simulation:{user_id}:{tariff.value}:{now.isoformat()}",
            amount=info.price,
            raw_payload='{"mode":"simulation"}',
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
