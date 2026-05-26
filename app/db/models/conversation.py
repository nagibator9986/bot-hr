"""Хранилище истории диалога пользователя с ботом."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ConversationMessage(Base, TimestampMixin):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_conversation_messages_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    direction: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    role: Mapped[str | None] = mapped_column(String(16))
    message_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)

    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)

    text: Mapped[str | None] = mapped_column(Text)
    callback_data: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<ConversationMessage id={self.id} user={self.user_id} {self.direction}>"
