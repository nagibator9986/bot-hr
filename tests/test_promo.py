"""Активация подписки по промокоду: валидация, идемпотентность, гонка max_uses."""

from __future__ import annotations

from datetime import timedelta

import pytest
from app.core.exceptions import PromoAlreadyUsedError, PromoInvalidError
from app.services.promo import PromoService
from app.utils.time import utcnow

from tests.fakes import (
    FakePaymentRepo,
    FakePromoCodeRepo,
    FakeSession,
    FakeSubscriptionRepo,
    make_promo_code,
)


def _service(
    *, promo: object, increment_ok: bool = True, seen_payment: str | None = None
) -> PromoService:
    svc = PromoService(session=FakeSession())  # type: ignore[arg-type]
    svc.codes = FakePromoCodeRepo(promo=promo, increment_ok=increment_ok)  # type: ignore[arg-type,assignment]
    payments = FakePaymentRepo()
    if seen_payment is not None:
        payments.seen.add(seen_payment)
    svc.payments = payments  # type: ignore[assignment]
    svc.subscriptions = FakeSubscriptionRepo()  # type: ignore[assignment]
    return svc


async def test_unknown_code_rejected() -> None:
    svc = _service(promo=None)
    with pytest.raises(PromoInvalidError):
        await svc.redeem(user_id=1, code="NOPE")


async def test_inactive_code_rejected() -> None:
    svc = _service(promo=make_promo_code(is_active=False))
    with pytest.raises(PromoInvalidError):
        await svc.redeem(user_id=1, code="ABC123")


async def test_expired_code_rejected() -> None:
    svc = _service(promo=make_promo_code(expires_at=utcnow() - timedelta(days=1)))
    with pytest.raises(PromoInvalidError):
        await svc.redeem(user_id=1, code="ABC123")


async def test_exhausted_code_rejected() -> None:
    svc = _service(promo=make_promo_code(max_uses=5, used_count=5))
    with pytest.raises(PromoInvalidError):
        await svc.redeem(user_id=1, code="ABC123")


async def test_already_used_by_user_rejected() -> None:
    promo = make_promo_code(code="ABC123")
    svc = _service(promo=promo, seen_payment="promo:ABC123:1")
    with pytest.raises(PromoAlreadyUsedError):
        await svc.redeem(user_id=1, code="ABC123")


async def test_lost_max_uses_race_rejected() -> None:
    """increment_used вернул False (последний слот занят другой активацией)."""
    svc = _service(promo=make_promo_code(max_uses=1), increment_ok=False)
    with pytest.raises(PromoInvalidError):
        await svc.redeem(user_id=1, code="ABC123")


async def test_redeem_success_activates_subscription() -> None:
    svc = _service(promo=make_promo_code(tariff="candidate", duration_days=30))
    sub = await svc.redeem(user_id=1, code="ABC123")
    assert sub.user_id == 1
    assert sub.is_active
    assert svc.codes.incremented == 1  # type: ignore[attr-defined]
