"""User — единая точка для любого Telegram-пользователя."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import Role
from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.candidate import Candidate
    from app.db.models.conversation import ConversationMessage
    from app.db.models.employer import Employer
    from app.db.models.referral import ReferralBalance


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    tg_username: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[Role | None] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(8), default="ru", nullable=False)
    is_blocked: Mapped[bool] = mapped_column(default=False, nullable=False)

    # ── Связи ─────────────────────────────────────────────────────────────
    candidate: Mapped[Candidate | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    employer: Mapped[Employer | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    referral_balance: Mapped[ReferralBalance | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    conversation_messages: Mapped[list[ConversationMessage]] = relationship(
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} tg_id={self.tg_id} role={self.role}>"
