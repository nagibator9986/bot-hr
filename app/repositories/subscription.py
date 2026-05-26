"""Репозитории Subscription и Payment."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import PaymentStatus, Tariff
from app.db.models.payment import Payment
from app.db.models.subscription import Subscription


class SubscriptionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active(self, user_id: int) -> Subscription | None:
        stmt = (
            select(Subscription)
            .where(Subscription.user_id == user_id, Subscription.is_active.is_(True))
            .order_by(Subscription.expires_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: int,
        tariff: Tariff,
        started_at: datetime,
        expires_at: datetime,
    ) -> Subscription:
        # Деактивируем предыдущие активные подписки
        prev = await self.get_active(user_id)
        if prev is not None:
            prev.is_active = False

        sub = Subscription(
            user_id=user_id,
            tariff=tariff,
            started_at=started_at,
            expires_at=expires_at,
            is_active=True,
        )
        self.session.add(sub)
        await self.session.flush()
        return sub

    async def increment_viewed(self, sub: Subscription) -> None:
        sub.candidates_viewed += 1
        await self.session.flush()

    async def deactivate(self, sub: Subscription) -> None:
        sub.is_active = False
        await self.session.flush()

    async def list_expiring(self, *, within_days: int, now: datetime) -> list[Subscription]:
        from datetime import timedelta

        stmt = select(Subscription).where(
            Subscription.is_active.is_(True),
            Subscription.expires_at <= now + timedelta(days=within_days),
            Subscription.expires_at > now,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_active(self, *, limit: int = 20) -> list[Subscription]:
        stmt = (
            select(Subscription)
            .where(Subscription.is_active.is_(True))
            .order_by(Subscription.expires_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class PaymentRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        user_id: int,
        provider: str,
        provider_payment_id: str,
        amount: int,
        tariff: Tariff,
        status: PaymentStatus = PaymentStatus.SUCCESS,
        raw_payload: str | None = None,
    ) -> Payment | None:
        """Идемпотентная запись платежа. Возвращает None, если такой уже был."""
        stmt = (
            pg_insert(Payment)
            .values(
                user_id=user_id,
                provider=provider,
                provider_payment_id=provider_payment_id,
                amount=amount,
                tariff=tariff,
                status=status,
                raw_payload=raw_payload,
            )
            .on_conflict_do_nothing(index_elements=["provider_payment_id"])
            .returning(Payment.id)
        )
        result = await self.session.execute(stmt)
        row = result.first()
        if row is None:
            return None
        return await self.session.get(Payment, row.id)

    async def list_success(self, *, limit: int = 20) -> list[Payment]:
        stmt = (
            select(Payment)
            .where(Payment.status == PaymentStatus.SUCCESS)
            .order_by(Payment.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
