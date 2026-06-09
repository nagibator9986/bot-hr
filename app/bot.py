"""Сборка Bot / Dispatcher и регистрация всех роутеров и middleware."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand, ErrorEvent, Message
from redis.asyncio import Redis

from app.config import settings
from app.core.exceptions import SmartChefError
from app.core.logger import get_logger
from app.handlers import (
    admin,
    browse,
    candidate,
    common,
    employer,
    interview,
    menu,
    referral,
    subscription,
)
from app.middlewares.conversation import ConversationMiddleware
from app.middlewares.db import DbSessionMiddleware
from app.middlewares.throttle import ThrottleMiddleware
from app.middlewares.user import UserMiddleware
from app.services.conversation import log_bot_message

BOT_COMMANDS = [
    BotCommand(command="start", description="Запуск / главное меню"),
    BotCommand(command="menu", description="Главное меню"),
    BotCommand(command="search", description="Листать карточки"),
    BotCommand(command="profile", description="Моя анкета"),
    BotCommand(command="subscription", description="Моя подписка"),
    BotCommand(command="invite", description="Пригласить друга"),
    BotCommand(command="myid", description="Мой Telegram ID"),
    BotCommand(command="cancel", description="Отменить текущее действие"),
    BotCommand(command="help", description="Помощь"),
]


class LoggingBot(Bot):
    async def send_message(  # type: ignore[override]
        self, chat_id: int | str, text: str, **kwargs: Any
    ) -> Message:
        msg = await super().send_message(chat_id, text, **kwargs)
        if isinstance(chat_id, int):
            await log_bot_message(
                tg_id=chat_id,
                message_type="text",
                text=text,
                telegram_message_id=msg.message_id,
            )
        return msg

    async def send_photo(  # type: ignore[override]
        self, chat_id: int | str, photo: Any, **kwargs: Any
    ) -> Message:
        msg = await super().send_photo(chat_id, photo, **kwargs)
        if isinstance(chat_id, int):
            await log_bot_message(
                tg_id=chat_id,
                message_type="photo",
                text=kwargs.get("caption"),
                telegram_message_id=msg.message_id,
            )
        return msg

    async def send_document(  # type: ignore[override]
        self, chat_id: int | str, document: Any, **kwargs: Any
    ) -> Message:
        msg = await super().send_document(chat_id, document, **kwargs)
        if isinstance(chat_id, int):
            await log_bot_message(
                tg_id=chat_id,
                message_type="document",
                text=kwargs.get("caption"),
                telegram_message_id=msg.message_id,
            )
        return msg


def build_bot() -> Bot:
    return LoggingBot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def setup_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)


async def on_error(event: ErrorEvent) -> None:
    """Глобальный обработчик: логирует исключение и не даёт боту «молча упасть»."""
    from app.locales import RU

    log = get_logger("error")
    exc = event.exception
    log.error("unhandled_exception", error=str(exc), exc_info=exc)

    update = event.update
    target: Message | None = None
    if update.message is not None:
        target = update.message
    elif update.callback_query is not None and isinstance(
        update.callback_query.message, Message
    ):
        target = update.callback_query.message

    if target is not None:
        text = exc.user_message if isinstance(exc, SmartChefError) else RU["error_generic"]
        with suppress(Exception):
            await target.answer(text)


def build_dispatcher(redis: Redis) -> Dispatcher:
    storage = RedisStorage(redis=redis)
    dp = Dispatcher(storage=storage)

    # ── Middlewares (order matters) ───────────────────────────────────────
    dp.update.outer_middleware(DbSessionMiddleware())
    dp.update.outer_middleware(UserMiddleware())
    dp.update.outer_middleware(ConversationMiddleware())
    # Один инстанс на message и callback — общий счётчик в Redis, лимит не удваивается.
    throttle = ThrottleMiddleware(redis)
    dp.message.middleware(throttle)
    dp.callback_query.middleware(throttle)

    # ── Routers (порядок важен) ───────────────────────────────────────────
    # FSM-формы выше меню; intent-fallback регистрируется последним.
    dp.include_routers(
        common.router,
        candidate.router,
        employer.router,
        browse.router,
        interview.router,
        subscription.router,
        referral.router,
        admin.router,
        menu.router,
        common.fallback_router,
    )

    dp.errors.register(on_error)
    return dp
