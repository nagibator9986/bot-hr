"""Candidate — анкета соискателя."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import CandidateStatus, Schedule
from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class Candidate(Base, TimestampMixin):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # ── Анкета ────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    city: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    preferred_area: Mapped[str | None] = mapped_column(String(128))
    desired_position: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    position_normalized: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    experience_years: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    previous_jobs: Mapped[str | None] = mapped_column(Text)
    schedule: Mapped[Schedule] = mapped_column(String(16), nullable=False)
    expected_salary: Mapped[int] = mapped_column(Numeric(10, 0), nullable=False)
    contact: Mapped[str] = mapped_column(String(64), nullable=False)

    # ── Медиа анкеты (обязательны, ТЗ-улучшение) ──────────────────────────
    photo_file_id: Mapped[str] = mapped_column(String(256), nullable=False)
    resume_file_id: Mapped[str | None] = mapped_column(String(256))
    resume_file_name: Mapped[str | None] = mapped_column(String(256))
    about: Mapped[str | None] = mapped_column(Text)  # «о себе», свободный текст

    # ── Состояние ─────────────────────────────────────────────────────────
    status: Mapped[CandidateStatus] = mapped_column(
        String(24), default=CandidateStatus.NEW, nullable=False, index=True
    )

    user: Mapped[User] = relationship(back_populates="candidate")

    def __repr__(self) -> str:
        return f"<Candidate id={self.id} name={self.name} position={self.desired_position}>"
