"""Vacancy — вакансия работодателя."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import Schedule, VacancyStatus
from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.employer import Employer
    from app.db.models.match import Match


class Vacancy(Base, TimestampMixin):
    __tablename__ = "vacancies"
    __table_args__ = (
        CheckConstraint("salary_max >= salary_min", name="salary_range_ordered"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employer_id: Mapped[int] = mapped_column(
        ForeignKey("employers.id", ondelete="CASCADE"), nullable=False, index=True
    )

    position: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    position_normalized: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    city: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Вилка зарплаты «от … до …» (тенге).
    salary_min: Mapped[int] = mapped_column(Numeric(10, 0), nullable=False)
    salary_max: Mapped[int] = mapped_column(Numeric(10, 0), nullable=False)
    schedule: Mapped[Schedule] = mapped_column(String(16), nullable=False)
    address: Mapped[str] = mapped_column(String(256), nullable=False)
    conditions: Mapped[str | None] = mapped_column(Text)
    experience_min: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Фото заведения для карточки (опционально).
    photo_file_id: Mapped[str | None] = mapped_column(String(256))

    requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    status: Mapped[VacancyStatus] = mapped_column(
        String(16), default=VacancyStatus.ACTIVE, nullable=False, index=True
    )

    employer: Mapped[Employer] = relationship(back_populates="vacancies")
    matches: Mapped[list[Match]] = relationship(
        back_populates="vacancy", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Vacancy id={self.id} position={self.position}>"
