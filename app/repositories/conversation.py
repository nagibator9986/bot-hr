"""Репозиторий истории диалога."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import ConversationMessage


class ConversationRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        direction: str,
        message_type: str,
        role: str | None = None,
        telegram_chat_id: int | None = None,
        telegram_message_id: int | None = None,
        text: str | None = None,
        callback_data: str | None = None,
    ) -> ConversationMessage:
        item = ConversationMessage(
            user_id=user_id,
            direction=direction,
            role=role,
            message_type=message_type,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            text=text,
            callback_data=callback_data,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def recent_for_user(
        self, user_id: int, *, limit: int = 20
    ) -> list[ConversationMessage]:
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.user_id == user_id)
            .order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        items.reverse()
        return items
