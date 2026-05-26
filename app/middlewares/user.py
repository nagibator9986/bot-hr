"""Middleware: get_or_create User по каждому update и кладёт его в data['user']."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.user import UserRepo


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = _extract_tg_user(event)
        if tg_user is None:
            return await handler(event, data)

        session: AsyncSession = data["session"]
        users = UserRepo(session)
        user = await users.get_or_create(
            tg_id=tg_user.id, tg_username=tg_user.username
        )
        data["user"] = user
        return await handler(event, data)


def _extract_tg_user(event: TelegramObject) -> Any:
    if isinstance(event, Update):
        if event.message:
            return event.message.from_user
        if event.callback_query:
            return event.callback_query.from_user
    if isinstance(event, (Message, CallbackQuery)):
        return event.from_user
    return None
