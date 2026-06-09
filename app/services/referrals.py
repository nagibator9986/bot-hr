"""Реферальная программа (ТЗ §11).

Кешбек начисляется только после оплаты friend'ом. Защита от накрутки —
уникальность пары и проверка self-referral на уровне БД.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import InsufficientBalanceError
from app.db.models.promo import Promoter
from app.db.models.referral import Referral, WithdrawalRequest
from app.repositories.promo import PromoterRepo
from app.repositories.referral import (
    BalanceRepo,
    ReferralRepo,
    WithdrawalRepo,
)


def make_referral_link(bot_username: str, user_id: int) -> str:
    return f"https://t.me/{bot_username}?start=ref_{user_id}"


def make_promoter_link(bot_username: str, code: str) -> str:
    return f"https://t.me/{bot_username}?start=promo_{code}"


def parse_start_param(param: str | None) -> int | None:
    """Из 'ref_12345' → 12345. Возвращает None если не реф-параметр."""
    if not param or not param.startswith("ref_"):
        return None
    try:
        return int(param[4:])
    except ValueError:
        return None


def parse_promoter_param(param: str | None) -> str | None:
    """Из 'promo_<code>' → '<code>'. Возвращает None, если не промоутерский параметр."""
    if not param or not param.startswith("promo_"):
        return None
    code = param[len("promo_"):].strip()
    return code or None


class ReferralService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.referrals = ReferralRepo(session)
        self.balances = BalanceRepo(session)
        self.withdrawals = WithdrawalRepo(session)
        self.promoters = PromoterRepo(session)

    async def attach_referrer(
        self, *, referrer_id: int, referee_id: int
    ) -> Referral:
        """Привязывает referee к обычному referrer. Бонус НЕ начисляется до оплаты."""
        return await self.referrals.link(
            referrer_id=referrer_id,
            referee_id=referee_id,
            bonus_amount=settings.referral_bonus,
        )

    async def attach_promoter(self, *, promoter: Promoter, referee_id: int) -> Referral:
        """Привязывает referee к промоутеру (повышенный бонус из promoter.bonus_amount)."""
        return await self.referrals.link_promoter(
            promoter_id=promoter.id,
            referee_id=referee_id,
            bonus_amount=int(promoter.bonus_amount),
        )

    async def grant_on_payment(self, referee_id: int) -> Referral | None:
        """Вызвать ТОЛЬКО после реальной оплаты деньгами (Kaspi).

        Начисляет бонус источнику: обычному рефереру — на баланс; промоутеру —
        на баланс привязанного аккаунта (если есть) и в его total_earned.
        Бесплатные активации (промокод) сюда не приходят — бонус за них не платим.
        """
        ref = await self.referrals.get_pending_for_referee(referee_id)
        if ref is None:
            return None
        bonus = int(ref.bonus_amount)
        if ref.referrer_id is not None:
            await self.balances.credit(ref.referrer_id, bonus)
        elif ref.promoter_id is not None:
            promoter = await self.promoters.get(ref.promoter_id)
            if promoter is not None:
                await self.promoters.add_earned(promoter, bonus)
                if promoter.user_id is not None:
                    await self.balances.credit(promoter.user_id, bonus)
        await self.referrals.mark_granted(ref)
        return ref

    async def request_withdrawal(
        self, *, user_id: int, amount: int, kaspi_phone: str
    ) -> WithdrawalRequest:
        if amount < settings.referral_min_withdrawal:
            raise InsufficientBalanceError(
                f"min withdrawal {settings.referral_min_withdrawal}"
            )
        balance = await self.balances.get_or_create(user_id)
        if balance.balance < amount:
            raise InsufficientBalanceError()

        await self.balances.debit(user_id, amount)
        return await self.withdrawals.create(
            user_id=user_id, amount=amount, kaspi_phone=kaspi_phone
        )

    async def get_balance(self, user_id: int) -> int:
        balance = await self.balances.get_or_create(user_id)
        return int(balance.balance)

    async def referrer_stats(self, user_id: int) -> tuple[int, int, int]:
        """(приглашено, оформили подписку, текущий баланс) — для карточки /invite."""
        invited, granted = await self.referrals.count_for_referrer(user_id)
        return invited, granted, await self.get_balance(user_id)
