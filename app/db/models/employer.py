"""Employer — компания-работодатель (HR-сторона) с верификацией."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import VerificationStatus
from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.user import User
    from app.db.models.vacancy import Vacancy


class Employer(Base, TimestampMixin):
    __tablename__ = "employers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    company_name: Mapped[str] = mapped_column(String(128), nullable=False)
    city: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    contact_person: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)

    # ── Верификация HR (БИН + подтверждённый телефон + модерация) ─────────
    bin: Mapped[str | None] = mapped_column(String(12), index=True)
    phone_verified: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        String(16),
        default=VerificationStatus.PENDING,
        server_default=VerificationStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_note: Mapped[str | None] = mapped_column(String(256))

    user: Mapped[User] = relationship(back_populates="employer")
    vacancies: Mapped[list[Vacancy]] = relationship(
        back_populates="employer", cascade="all, delete-orphan"
    )

    @property
    def is_verified(self) -> bool:
        return self.verification_status == VerificationStatus.APPROVED

    def __repr__(self) -> str:
        return f"<Employer id={self.id} company={self.company_name} {self.verification_status}>"
