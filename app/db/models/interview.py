"""Interview — собеседование по матчу (предложение слотов → подтверждение)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import InterviewStatus
from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.match import Match


class Interview(Base, TimestampMixin):
    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # Слоты, предложенные работодателем (ISO-строки). Актуальны в статусе PROPOSED.
    proposed_slots: Mapped[list[str] | None] = mapped_column(JSONB)
    # Итоговое время — заполняется, когда кандидат выбрал слот.
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    address: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[InterviewStatus] = mapped_column(
        String(24), default=InterviewStatus.PROPOSED, nullable=False, index=True
    )

    match: Mapped[Match] = relationship(back_populates="interview")

    def __repr__(self) -> str:
        return f"<Interview id={self.id} match={self.match_id} status={self.status}>"
