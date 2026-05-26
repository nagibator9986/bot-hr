"""Репозитории реферальной системы."""

from __future__ import annotations

from sqlalchemy import select
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
        self.session.add(ref)
        try:
            await self.session.flush()
        except IntegrityError as e:
            await self.session.rollback()
            raise AlreadyReferredError() from e
        return ref

    async def get_pending_for_referee(self, referee_id: int) -> Referral | None:
        stmt = select(Referral).where(
            Referral.referee_id == referee_id,
            Referral.status == ReferralStatus.PENDING,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

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
