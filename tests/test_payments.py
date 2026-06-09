"""Идемпотентность активации подписки (CLAUDE.md §4.6, §9)."""

from __future__ import annotations

import pytest
from app.core.constants import Tariff
from app.core.exceptions import DuplicatePaymentError
from app.services.payments import PaymentService, tariff_info

from tests.fakes import FakePaymentRepo, FakeSession, FakeSubscriptionRepo


def _service() -> PaymentService:
    svc = PaymentService(session=FakeSession())  # type: ignore[arg-type]
    svc.payments = FakePaymentRepo()  # type: ignore[assignment]
    svc.subscriptions = FakeSubscriptionRepo()  # type: ignore[assignment]
    return svc


async def test_confirm_payment_activates_subscription() -> None:
    svc = _service()
    price = tariff_info(Tariff.CANDIDATE).price
    sub = await svc.confirm_payment(
        user_id=7,
        tariff=Tariff.CANDIDATE,
        provider="kaspi",
        provider_payment_id="kaspi:claim:1",
        amount=price,
    )
    assert sub.is_active
    assert sub.user_id == 7


async def test_confirm_payment_is_idempotent() -> None:
    """Повторная нотификация с тем же provider_payment_id не продлевает дважды."""
    svc = _service()
    price = tariff_info(Tariff.EMPLOYER_BASIC).price
    args = {
        "user_id": 1,
        "tariff": Tariff.EMPLOYER_BASIC,
        "provider": "kaspi",
        "provider_payment_id": "dup-id",
        "amount": price,
    }
    await svc.confirm_payment(**args)
    with pytest.raises(DuplicatePaymentError):
        await svc.confirm_payment(**args)
    # Подписка создана ровно одна.
    assert len(svc.subscriptions.created) == 1  # type: ignore[attr-defined]


async def test_confirm_payment_rejects_underpayment() -> None:
    svc = _service()
    price = tariff_info(Tariff.EMPLOYER_EXTENDED).price
    with pytest.raises(ValueError, match="tariff price"):
        await svc.confirm_payment(
            user_id=1,
            tariff=Tariff.EMPLOYER_EXTENDED,
            provider="kaspi",
            provider_payment_id="low",
            amount=price - 1,
        )


async def test_confirm_kaspi_claim_uses_claim_scoped_id() -> None:
    svc = _service()
    sub = await svc.confirm_kaspi_claim(user_id=3, tariff=Tariff.CANDIDATE, claim_id=42)
    assert sub.user_id == 3
    assert "kaspi:claim:42" in svc.payments.seen  # type: ignore[attr-defined]
