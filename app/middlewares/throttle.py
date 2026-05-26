"""Простой throttle: не больше N апдейтов в M секунд на пользователя.

Хранит счётчики в памяти процесса (для прод-нагрузки заменить на Redis).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

DEFAULT_LIMIT = 10
DEFAULT_WINDOW = 5.0  # секунд


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, limit: int = DEFAULT_LIMIT, window: float = DEFAULT_WINDOW) -> None:
        self.limit = limit
        self.window = window
        self._buckets: dict[int, deque[float]] = defaultdict(deque)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = _get_user(event)
        if user is None:
            return await handler(event, data)

        now = time.monotonic()
        bucket = self._buckets[user.id]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()

        if len(bucket) >= self.limit:
            if isinstance(event, CallbackQuery):
                await event.answer("Слишком часто. Подождите немного.", show_alert=False)
            return None

        bucket.append(now)
        return await handler(event, data)


def _get_user(event: TelegramObject) -> Any:
    if isinstance(event, (Message, CallbackQuery)):
        return event.from_user
    return None
