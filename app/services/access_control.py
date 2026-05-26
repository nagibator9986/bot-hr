"""Проверка прав доступа: активная подписка + лимит просмотров.

См. ТЗ §10.4, §10.5. Контакт/адрес/телефон отдаём только при активной подписке.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import TARIFF_LIMITS, Tariff
from app.core.exceptions import (
    CandidateLimitReachedError,
    SubscriptionExpiredError,
    SubscriptionRequiredError,
)
from app.db.models.subscription import Subscription
from app.repositories.subscription import SubscriptionRepo
from app.utils.time import utcnow


class AccessControlService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.subscriptions = SubscriptionRepo(session)

    async def get_active_subscription(self, user_id: int) -> Subscription | None:
        sub = await self.subscriptions.get_active(user_id)
        if sub is None:
            return None
        if sub.expires_at <= utcnow():
            await self.subscriptions.deactivate(sub)
            return None
        return sub

    async def require_active(self, user_id: int) -> Subscription:
        sub = await self.subscriptions.get_active(user_id)
        if sub is None:
            raise SubscriptionRequiredError()
        if sub.expires_at <= utcnow():
            await self.subscriptions.deactivate(sub)
            raise SubscriptionExpiredError()
        return sub

    async def has_full_access(self, user_id: int) -> bool:
        return await self.get_active_subscription(user_id) is not None

    async def can_view_candidate(self, user_id: int) -> Subscription:
        """Проверка перед раскрытием контакта. Лимит на просмотр НЕ инкрементируется."""
        sub = await self.require_active(user_id)
        limit = TARIFF_LIMITS.get(Tariff(sub.tariff))
        if limit is not None and sub.candidates_viewed >= limit:
            raise CandidateLimitReachedError()
        return sub

    async def consume_candidate_view(self, sub: Subscription) -> None:
        """Инкремент счётчика. Вызывать в транзакции после успешного раскрытия."""
        await self.subscriptions.increment_viewed(sub)
