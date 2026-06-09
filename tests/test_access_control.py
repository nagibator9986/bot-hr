"""Доступ и лимиты: подписка обязательна, лимит работодателя, истечение (§10)."""

from __future__ import annotations

import pytest
from app.core.exceptions import (
    CandidateLimitReachedError,
    SubscriptionExpiredError,
    SubscriptionRequiredError,
)
from app.services.access_control import AccessControlService

from tests.fakes import FakeSession, FakeSubscriptionRepo, make_subscription


def _service(active: object) -> tuple[AccessControlService, FakeSubscriptionRepo]:
    svc = AccessControlService(session=FakeSession())  # type: ignore[arg-type]
    repo = FakeSubscriptionRepo(active=active)  # type: ignore[arg-type]
    svc.subscriptions = repo  # type: ignore[assignment]
    return svc, repo


async def test_require_active_without_subscription_raises() -> None:
    svc, _ = _service(None)
    with pytest.raises(SubscriptionRequiredError):
        await svc.require_active(user_id=1)


async def test_require_active_deactivates_expired() -> None:
    sub = make_subscription(expires_in_days=-1)
    svc, repo = _service(sub)
    with pytest.raises(SubscriptionExpiredError):
        await svc.require_active(user_id=1)
    assert sub in repo.deactivated


async def test_get_active_returns_none_for_expired() -> None:
    sub = make_subscription(expires_in_days=-1)
    svc, repo = _service(sub)
    assert await svc.get_active_subscription(user_id=1) is None
    assert sub in repo.deactivated


async def test_can_view_candidate_blocks_at_limit() -> None:
    sub = make_subscription(tariff="employer_basic", candidates_viewed=20)
    svc, _ = _service(sub)
    with pytest.raises(CandidateLimitReachedError):
        await svc.can_view_candidate(user_id=1)


async def test_can_view_candidate_allows_below_limit() -> None:
    sub = make_subscription(tariff="employer_basic", candidates_viewed=19)
    svc, _ = _service(sub)
    assert await svc.can_view_candidate(user_id=1) is sub


async def test_candidate_tariff_has_no_view_limit() -> None:
    sub = make_subscription(tariff="candidate", candidates_viewed=999)
    svc, _ = _service(sub)
    assert await svc.can_view_candidate(user_id=1) is sub


async def test_consume_increments_view_counter() -> None:
    sub = make_subscription(tariff="employer_basic", candidates_viewed=5)
    svc, _ = _service(sub)
    await svc.consume_candidate_view(sub)
    assert sub.candidates_viewed == 6
