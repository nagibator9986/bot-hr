"""Match — связь кандидат ↔ вакансия. Создаётся matcher-ом."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import MatchDecision, Reaction
from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.candidate import Candidate
    from app.db.models.interview import Interview
    from app.db.models.vacancy import Vacancy


class Match(Base, TimestampMixin):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("candidate_id", "vacancy_id", name="uq_matches_candidate_vacancy"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vacancy_id: Mapped[int] = mapped_column(
        ForeignKey("vacancies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    score: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[MatchDecision] = mapped_column(
        String(32), default=MatchDecision.PENDING, nullable=False, index=True
    )

    # ── Свайп-реакции (Дайвинчик-стиль) ───────────────────────────────────
    # NULL = ещё не показывали / не отреагировал.
    candidate_reaction: Mapped[Reaction | None] = mapped_column(String(8), index=True)
    employer_reaction: Mapped[Reaction | None] = mapped_column(String(8), index=True)
    candidate_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    employer_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    candidate: Mapped[Candidate] = relationship()
    vacancy: Mapped[Vacancy] = relationship(back_populates="matches")
    interview: Mapped[Interview | None] = relationship(
        back_populates="match", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def is_mutual(self) -> bool:
        return (
            self.candidate_reaction == Reaction.LIKE
            and self.employer_reaction == Reaction.LIKE
        )

    def __repr__(self) -> str:
        return f"<Match id={self.id} c={self.candidate_id} v={self.vacancy_id} score={self.score}>"
