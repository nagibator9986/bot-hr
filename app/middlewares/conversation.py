"""Middleware логирования входящих сообщений и callback'ов."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.core.logger import get_logger
from app.db.models.user import User
from app.services.conversation import ConversationService

log = get_logger("conversation_middleware")


class ConversationMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session = data.get("session")
        user = data.get("user")
        if session is not None and isinstance(user, User):
            try:
                await _log_event(event, data, user)
            except Exception as exc:
                log.warning("incoming_log_failed", error=str(exc), user_id=user.id)
        return await handler(event, data)


async def _log_event(event: TelegramObject, data: dict[str, Any], user: User) -> None:
    service = ConversationService(data["session"])
    update = event if isinstance(event, Update) else None

    if update is not None:
        if isinstance(update.message, Message):
            await service.log_incoming_message(user.id, user.role, update.message)
            return
        if isinstance(update.callback_query, CallbackQuery):
            await service.log_incoming_callback(user.id, user.role, update.callback_query)
            return

    if isinstance(event, Message):
        await service.log_incoming_message(user.id, user.role, event)
    elif isinstance(event, CallbackQuery):
        await service.log_incoming_callback(user.id, user.role, event)
