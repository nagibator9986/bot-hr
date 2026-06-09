"""Репозитории промоутеров, промокодов и заявок на оплату Kaspi."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import PaymentClaimStatus, Tariff
from app.db.models.payment import PaymentClaim
from app.db.models.promo import PromoCode, Promoter
from app.utils.time import utcnow


class PromoterRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, *, name: str, code: str, bonus_amount: int, user_id: int | None = None
    ) -> Promoter:
        promoter = Promoter(name=name, code=code, bonus_amount=bonus_amount, user_id=user_id)
        self.session.add(promoter)
        await self.session.flush()
        return promoter

    async def get(self, promoter_id: int) -> Promoter | None:
        return await self.session.get(Promoter, promoter_id)

    async def get_by_code(self, code: str) -> Promoter | None:
        stmt = select(Promoter).where(Promoter.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_all(self) -> list[Promoter]:
        stmt = select(Promoter).order_by(Promoter.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def add_earned(self, promoter: Promoter, amount: int) -> None:
        """Атомарное начисление заработка промоутеру (без read-modify-write)."""
        await self.session.execute(
            update(Promoter)
            .where(Promoter.id == promoter.id)
            .values(total_earned=Promoter.total_earned + amount)
            .execution_options(synchronize_session=False)
        )
        await self.session.refresh(promoter, ["total_earned"])

    async def bind_user(self, promoter: Promoter, user_id: int) -> None:
        promoter.user_id = user_id
        await self.session.flush()


class PromoCodeRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        code: str,
        tariff: Tariff,
        duration_days: int,
        max_uses: int | None,
        expires_at: datetime | None = None,
    ) -> PromoCode:
        promo = PromoCode(
            code=code,
            tariff=tariff,
            duration_days=duration_days,
            max_uses=max_uses,
            expires_at=expires_at,
        )
        self.session.add(promo)
        await self.session.flush()
        return promo

    async def get_by_code(self, code: str) -> PromoCode | None:
        stmt = select(PromoCode).where(PromoCode.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_active(self) -> list[PromoCode]:
        stmt = (
            select(PromoCode)
            .where(PromoCode.is_active.is_(True))
            .order_by(PromoCode.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def increment_used(self, promo: PromoCode) -> bool:
        """Атомарно увеличивает счётчик активаций с учётом max_uses.

        Возвращает False, если лимит уже исчерпан (например, параллельной
        активацией) — вызывающий код обязан отказать в выдаче подписки.
        """
        row = (
            await self.session.execute(
                update(PromoCode)
                .where(
                    PromoCode.id == promo.id,
                    or_(
                        PromoCode.max_uses.is_(None),
                        PromoCode.used_count < PromoCode.max_uses,
                    ),
                )
                .values(used_count=PromoCode.used_count + 1)
                .returning(PromoCode.id)
                .execution_options(synchronize_session=False)
            )
        ).first()
        if row is None:
            return False
        await self.session.refresh(promo, ["used_count"])
        return True


class PaymentClaimRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, user_id: int, tariff: Tariff, amount: int) -> PaymentClaim:
        claim = PaymentClaim(user_id=user_id, tariff=tariff, amount=amount)
        self.session.add(claim)
        await self.session.flush()
        return claim

    async def get(self, claim_id: int) -> PaymentClaim | None:
        return await self.session.get(PaymentClaim, claim_id)

    async def list_pending(self) -> list[PaymentClaim]:
        stmt = (
            select(PaymentClaim)
            .where(PaymentClaim.status == PaymentClaimStatus.PENDING)
            .order_by(PaymentClaim.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def set_status(
        self, claim: PaymentClaim, status: PaymentClaimStatus, *, admin_id: int | None
    ) -> None:
        claim.status = status
        claim.admin_id = admin_id
        claim.processed_at = utcnow()
        await self.session.flush()
