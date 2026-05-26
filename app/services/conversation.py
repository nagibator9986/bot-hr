"""История диалога и контекст для поддержки."""

from __future__ import annotations

from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Role
from app.core.logger import get_logger
from app.db.session import SessionFactory
from app.repositories.conversation import ConversationRepo
from app.repositories.user import UserRepo

log = get_logger("conversation")

_MAX_TEXT = 2000


def _trim(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned[:_MAX_TEXT] if cleaned else None


def _message_payload(message: Message) -> tuple[str, str | None]:
    if message.text:
        return "text", _trim(message.text)
    if message.caption:
        if message.photo:
            return "photo", _trim(message.caption)
        if message.document:
            return "document", _trim(message.caption)
    if message.photo:
        return "photo", "Фото"
    if message.document is not None:
        name = message.document.file_name or "Документ"
        return "document", _trim(name)
    if message.contact is not None:
        return "contact", _trim(message.contact.phone_number)
    return message.content_type, None


class ConversationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ConversationRepo(session)

    async def log_incoming_message(self, user_id: int, role: Role | None, message: Message) -> None:
        message_type, text = _message_payload(message)
        await self.repo.create(
            user_id=user_id,
            direction="in",
            role=role.value if role is not None else None,
            message_type=message_type,
            telegram_chat_id=message.chat.id,
            telegram_message_id=message.message_id,
            text=text,
        )

    async def log_incoming_callback(
        self, user_id: int, role: Role | None, callback: CallbackQuery
    ) -> None:
        text = None
        if isinstance(callback.message, Message):
            text = _trim(callback.message.text or callback.message.caption)
        await self.repo.create(
            user_id=user_id,
            direction="in",
            role=role.value if role is not None else None,
            message_type="callback",
            telegram_chat_id=callback.from_user.id,
            telegram_message_id=callback.message.message_id if isinstance(callback.message, Message) else None,
            text=text,
            callback_data=_trim(callback.data),
        )

    async def recent_context(self, user_id: int, *, limit: int = 8) -> str:
        items = await self.repo.recent_for_user(user_id, limit=limit)
        lines: list[str] = []
        for item in items:
            payload = item.callback_data if item.message_type == "callback" else item.text
            if not payload:
                continue
            who = "Пользователь" if item.direction == "in" else "Бот"
            lines.append(f"{who}: {payload}")
        return "\n".join(lines[-limit:])

    async def history_lines(self, user_id: int, *, limit: int = 20) -> list[str]:
        items = await self.repo.recent_for_user(user_id, limit=limit)
        lines: list[str] = []
        for item in items:
            ts = item.created_at.strftime("%d.%m %H:%M")
            role = f" [{item.role}]" if item.role else ""
            payload = item.callback_data if item.message_type == "callback" else item.text
            payload = payload or "—"
            lines.append(
                f"{ts} · {item.direction}/{item.message_type}{role}\n{payload[:300]}"
            )
        return lines


async def log_bot_message(
    *,
    tg_id: int,
    message_type: str,
    text: str | None = None,
    telegram_message_id: int | None = None,
) -> None:
    """Логирует исходящие сообщения бота вне handler-контекста."""
    try:
        async with SessionFactory() as session:
            user = await UserRepo(session).get_by_tg_id(tg_id)
            if user is None:
                return
            await ConversationRepo(session).create(
                user_id=user.id,
                direction="out",
                role=user.role.value if isinstance(user.role, Role) else str(user.role) if user.role else None,
                message_type=message_type,
                telegram_chat_id=tg_id,
                telegram_message_id=telegram_message_id,
                text=_trim(text),
            )
            await session.commit()
    except Exception as exc:
        log.warning("conversation_log_failed", error=str(exc), tg_id=tg_id)
