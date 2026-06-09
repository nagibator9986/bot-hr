"""Throttle на Redis: не больше N апдейтов в M секунд на пользователя.

Счётчик хранится в Redis (INCR + EXPIRE), а не в памяти процесса:
  • переживает рестарт бота;
  • не течёт по памяти (TTL сам удаляет ключи);
  • общий для message и callback — оба инкрементируют один ключ, поэтому
    реальный лимит не удваивается.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from redis.asyncio import Redis

DEFAULT_LIMIT = 10
DEFAULT_WINDOW = 5  # секунд


class ThrottleMiddleware(BaseMiddleware):
    def __init__(
        self, redis: Redis, *, limit: int = DEFAULT_LIMIT, window: int = DEFAULT_WINDOW
    ) -> None:
        self.redis = redis
        self.limit = limit
        self.window = window

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = _get_user(event)
        if user is None:
            return await handler(event, data)

        key = f"throttle:{user.id}"
        count = await self.redis.incr(key)
        # EXPIRE ... NX выставляет TTL только когда его ещё нет: один раз за окно
        # и устойчиво к гонке «процесс умер между INCR и EXPIRE» (на следующем
        # апдейте TTL доставится, ключ не зависнет навсегда).
        await self.redis.expire(key, self.window, nx=True)

        if count > self.limit:
            if isinstance(event, CallbackQuery):
                await event.answer("Слишком часто. Подождите немного.", show_alert=False)
            return None

        return await handler(event, data)


def _get_user(event: TelegramObject) -> Any:
    if isinstance(event, (Message, CallbackQuery)):
        return event.from_user
    return None
