"""Реферальные начисления и вывод (CLAUDE.md §6.5, §9).

Кешбек платится один раз и только за реальную оплату; вывод — не ниже минимума
и не больше баланса.
"""

from __future__ import annotations

import pytest
from app.config import settings
from app.core.exceptions import InsufficientBalanceError
from app.services.referrals import ReferralService

from tests.fakes import (
    FakeBalanceRepo,
    FakePromoterRepo,
    FakeReferralRepo,
    FakeSession,
    FakeWithdrawalRepo,
    make_promoter,
    make_referral,
)


def _service(
    *,
    pending: object = None,
    balance: int = 0,
    promoter: object = None,
) -> ReferralService:
    svc = ReferralService(session=FakeSession())  # type: ignore[arg-type]
    svc.referrals = FakeReferralRepo(pending=pending)  # type: ignore[arg-type,assignment]
    svc.balances = FakeBalanceRepo(balance=balance)  # type: ignore[assignment]
    svc.promoters = FakePromoterRepo(promoter=promoter)  # type: ignore[arg-type,assignment]
    svc.withdrawals = FakeWithdrawalRepo()  # type: ignore[assignment]
    return svc


async def test_grant_without_pending_returns_none() -> None:
    svc = _service(pending=None)
    assert await svc.grant_on_payment(referee_id=2) is None
    assert svc.balances.credits == []  # type: ignore[attr-defined]


async def test_grant_credits_regular_referrer_once() -> None:
    ref = make_referral(referrer_id=10, referee_id=2, bonus_amount=300)
    svc = _service(pending=ref)
    result = await svc.grant_on_payment(referee_id=2)
    assert result is ref
    assert svc.balances.credits == [(10, 300)]  # type: ignore[attr-defined]
    assert ref.status == "granted"
    # Повторно бонус не начисляется (referral больше не pending).
    assert await svc.grant_on_payment(referee_id=2) is None
    assert svc.balances.credits == [(10, 300)]  # type: ignore[attr-defined]


async def test_grant_pays_promoter_account() -> None:
    promoter = make_promoter(promoter_id=5, user_id=77)
    ref = make_referral(promoter_id=5, referee_id=2, bonus_amount=1000)
    svc = _service(pending=ref, promoter=promoter)
    await svc.grant_on_payment(referee_id=2)
    assert promoter.total_earned == 1000
    assert svc.balances.credits == [(77, 1000)]  # type: ignore[attr-defined]


async def test_withdrawal_below_minimum_rejected() -> None:
    svc = _service(balance=10_000)
    with pytest.raises(InsufficientBalanceError):
        await svc.request_withdrawal(
            user_id=1, amount=settings.referral_min_withdrawal - 1, kaspi_phone="+7700"
        )


async def test_withdrawal_above_balance_rejected() -> None:
    svc = _service(balance=500)
    with pytest.raises(InsufficientBalanceError):
        await svc.request_withdrawal(user_id=1, amount=2000, kaspi_phone="+7700")
    assert svc.balances.debits == []  # type: ignore[attr-defined]


async def test_withdrawal_success_debits_and_creates_request() -> None:
    svc = _service(balance=5000)
    req = await svc.request_withdrawal(user_id=1, amount=2000, kaspi_phone="+7700")
    assert req.amount == 2000
    assert svc.balances.debits == [(1, 2000)]  # type: ignore[attr-defined]
    assert svc.balances.balance_obj.balance == 3000  # type: ignore[attr-defined]
