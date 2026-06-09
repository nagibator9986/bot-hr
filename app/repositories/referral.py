"""Репозитории реферальной системы."""

from __future__ import annotations

from sqlalchemy import case as sa_case
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ReferralStatus, WithdrawalStatus
from app.core.exceptions import (
    AlreadyReferredError,
    SelfReferralError,
)
from app.db.models.referral import Referral, ReferralBalance, WithdrawalRequest


class ReferralRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def link(
        self,
        *,
        referrer_id: int,
        referee_id: int,
        bonus_amount: int,
    ) -> Referral:
        if referrer_id == referee_id:
            raise SelfReferralError()

        ref = Referral(
            referrer_id=referrer_id,
            referee_id=referee_id,
            bonus_amount=bonus_amount,
            status=ReferralStatus.PENDING,
        )
        # SAVEPOINT, а не session.rollback(): при дубликате откатываем только
        # вставку реферала, не трогая остальную транзакцию /start
        # (в частности, только что созданного UserMiddleware пользователя).
        try:
            async with self.session.begin_nested():
                self.session.add(ref)
                await self.session.flush()
        except IntegrityError as e:
            raise AlreadyReferredError() from e
        return ref

    async def link_promoter(
        self, *, promoter_id: int, referee_id: int, bonus_amount: int
    ) -> Referral:
        """Привязывает приглашённого к промоутеру (источник — промоутер, не юзер)."""
        ref = Referral(
            promoter_id=promoter_id,
            referee_id=referee_id,
            bonus_amount=bonus_amount,
            status=ReferralStatus.PENDING,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(ref)
                await self.session.flush()
        except IntegrityError as e:
            raise AlreadyReferredError() from e
        return ref

    async def get_pending_for_referee(self, referee_id: int) -> Referral | None:
        stmt = select(Referral).where(
            Referral.referee_id == referee_id,
            Referral.status == ReferralStatus.PENDING,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_for_referrer(self, referrer_id: int) -> tuple[int, int]:
        """(всего приглашено, из них оформили подписку) для реферера."""
        total = await self.session.scalar(
            select(func.count())
            .select_from(Referral)
            .where(Referral.referrer_id == referrer_id)
        )
        granted = await self.session.scalar(
            select(func.count())
            .select_from(Referral)
            .where(
                Referral.referrer_id == referrer_id,
                Referral.status == ReferralStatus.GRANTED,
            )
        )
        return int(total or 0), int(granted or 0)

    async def count_for_promoter(self, promoter_id: int) -> tuple[int, int]:
        """(всего привёл, из них оплатили) для промоутера."""
        total = await self.session.scalar(
            select(func.count())
            .select_from(Referral)
            .where(Referral.promoter_id == promoter_id)
        )
        granted = await self.session.scalar(
            select(func.count())
            .select_from(Referral)
            .where(
                Referral.promoter_id == promoter_id,
                Referral.status == ReferralStatus.GRANTED,
            )
        )
        return int(total or 0), int(granted or 0)

    async def top_referrers(self, *, limit: int = 20) -> list[tuple[int, int, int]]:
        """[(referrer_id, всего, оплатили), ...] — обычные пользователи, по убыванию."""
        granted_case = func.sum(
            sa_case((Referral.status == ReferralStatus.GRANTED, 1), else_=0)
        )
        stmt = (
            select(Referral.referrer_id, func.count(), granted_case)
            .where(Referral.referrer_id.is_not(None))
            .group_by(Referral.referrer_id)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(int(r[0]), int(r[1]), int(r[2] or 0)) for r in rows]

    async def list_for_referrer(self, referrer_id: int) -> list[Referral]:
        stmt = (
            select(Referral)
            .where(Referral.referrer_id == referrer_id)
            .order_by(Referral.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def mark_granted(self, ref: Referral) -> None:
        from app.utils.time import utcnow

        ref.status = ReferralStatus.GRANTED
        ref.granted_at = utcnow()
        await self.session.flush()


class BalanceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(self, user_id: int) -> ReferralBalance:
        stmt = (
            pg_insert(ReferralBalance)
            .values(user_id=user_id)
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        await self.session.execute(stmt)
        result = await self.session.execute(
            select(ReferralBalance).where(ReferralBalance.user_id == user_id)
        )
        return result.scalar_one()

    async def credit(self, user_id: int, amount: int) -> ReferralBalance:
        balance = await self.get_or_create(user_id)
        balance.balance += amount
        balance.total_earned += amount
        await self.session.flush()
        return balance

    async def debit(self, user_id: int, amount: int) -> ReferralBalance:
        balance = await self.get_or_create(user_id)
        balance.balance -= amount
        balance.total_withdrawn += amount
        await self.session.flush()
        return balance


class WithdrawalRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, *, user_id: int, amount: int, kaspi_phone: str
    ) -> WithdrawalRequest:
        req = WithdrawalRequest(
            user_id=user_id,
            amount=amount,
            kaspi_phone=kaspi_phone,
            status=WithdrawalStatus.PENDING,
        )
        self.session.add(req)
        await self.session.flush()
        return req

    async def list_pending(self) -> list[WithdrawalRequest]:
        stmt = select(WithdrawalRequest).where(
            WithdrawalRequest.status == WithdrawalStatus.PENDING
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def set_status(
        self, req: WithdrawalRequest, status: WithdrawalStatus, *, note: str | None = None
    ) -> None:
        from app.utils.time import utcnow

        req.status = status
        req.processed_at = utcnow()
        if note:
            req.admin_note = note
        await self.session.flush()
