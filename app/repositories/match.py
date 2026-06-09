"""Репозитории Match и Interview."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import InterviewStatus, MatchDecision, Reaction, Role
from app.db.models.candidate import Candidate
from app.db.models.employer import Employer
from app.db.models.interview import Interview
from app.db.models.match import Match
from app.db.models.vacancy import Vacancy
from app.utils.time import utcnow


class MatchRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, *, candidate_id: int, vacancy_id: int, score: int) -> Match:
        """Идемпотентно создаёт Match. Повторный вызов не меняет existing."""
        stmt = (
            pg_insert(Match)
            .values(candidate_id=candidate_id, vacancy_id=vacancy_id, score=score)
            .on_conflict_do_nothing(index_elements=["candidate_id", "vacancy_id"])
            .returning(Match.id)
        )
        result = await self.session.execute(stmt)
        row = result.first()
        if row is not None:
            await self.session.flush()
            return await self.get(row.id)  # type: ignore[return-value]
        # уже существует — загружаем
        existing = await self.session.execute(
            select(Match).where(
                Match.candidate_id == candidate_id, Match.vacancy_id == vacancy_id
            )
        )
        return existing.scalar_one()

    async def get(self, match_id: int) -> Match | None:
        return await self.session.get(Match, match_id)

    async def get_full(self, match_id: int) -> Match | None:
        stmt = (
            select(Match)
            .where(Match.id == match_id)
            .options(
                selectinload(Match.candidate).selectinload(Candidate.user),
                selectinload(Match.vacancy)
                .selectinload(Vacancy.employer)
                .selectinload(Employer.user),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_decision(self, match: Match, decision: MatchDecision) -> None:
        match.decision = decision
        await self.session.flush()

    # ── Свайп-просмотр ────────────────────────────────────────────────────
    async def reacted_vacancy_ids(self, candidate_id: int) -> set[int]:
        """ID вакансий, на которые кандидат уже отреагировал (не показывать снова)."""
        stmt = select(Match.vacancy_id).where(
            Match.candidate_id == candidate_id,
            Match.candidate_reaction.is_not(None),
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def reacted_candidate_ids(self, vacancy_id: int) -> set[int]:
        """ID кандидатов, на которых работодатель уже отреагировал."""
        stmt = select(Match.candidate_id).where(
            Match.vacancy_id == vacancy_id,
            Match.employer_reaction.is_not(None),
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def react(self, match: Match, *, by_role: Role, reaction: Reaction) -> bool:
        """Фиксирует реакцию одной стороны. Возвращает True, если интерес взаимный."""
        now = utcnow()
        if by_role == Role.CANDIDATE:
            match.candidate_reaction = reaction
            match.candidate_seen_at = now
        else:
            match.employer_reaction = reaction
            match.employer_seen_at = now
        if match.is_mutual:
            match.decision = MatchDecision.MUTUAL
        await self.session.flush()
        return match.is_mutual

    async def list_mutual_for_user(
        self,
        *,
        candidate_id: int | None = None,
        employer_id: int | None = None,
        limit: int = 50,
    ) -> list[Match]:
        """Взаимные матчи пользователя — для экрана «Мои отклики»."""
        stmt = (
            select(Match)
            .where(Match.decision == MatchDecision.MUTUAL)
            .options(
                selectinload(Match.candidate).selectinload(Candidate.user),
                selectinload(Match.interview),
                selectinload(Match.vacancy)
                .selectinload(Vacancy.employer)
                .selectinload(Employer.user),
            )
        )
        if candidate_id is not None:
            stmt = stmt.where(Match.candidate_id == candidate_id)
        if employer_id is not None:
            stmt = stmt.join(Vacancy).where(Vacancy.employer_id == employer_id)
        stmt = stmt.order_by(Match.updated_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_candidate_applications(self, *, limit: int = 20) -> list[Match]:
        """Матчи, где кандидат проявил интерес или уже есть взаимный отклик."""
        stmt = (
            select(Match)
            .where(
                Match.candidate_reaction == Reaction.LIKE,
            )
            .options(
                selectinload(Match.candidate).selectinload(Candidate.user),
                selectinload(Match.vacancy)
                .selectinload(Vacancy.employer)
                .selectinload(Employer.user),
                selectinload(Match.interview),
            )
            .order_by(Match.updated_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class InterviewRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, interview_id: int) -> Interview | None:
        return await self.session.get(Interview, interview_id)

    async def get_by_match(self, match_id: int) -> Interview | None:
        result = await self.session.execute(
            select(Interview).where(Interview.match_id == match_id)
        )
        return result.scalar_one_or_none()

    async def get_full(self, interview_id: int) -> Interview | None:
        """Собеседование вместе с кандидатом и работодателем (для уведомлений)."""
        stmt = (
            select(Interview)
            .where(Interview.id == interview_id)
            .options(
                selectinload(Interview.match)
                .selectinload(Match.candidate)
                .selectinload(Candidate.user),
                selectinload(Interview.match)
                .selectinload(Match.vacancy)
                .selectinload(Vacancy.employer)
                .selectinload(Employer.user),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_proposal(
        self, *, match_id: int, proposed_slots: list[str], address: str
    ) -> Interview:
        """Работодатель предложил слоты — создаём/обновляем запись со статусом PROPOSED."""
        interview = await self.get_by_match(match_id)
        if interview is None:
            interview = Interview(
                match_id=match_id,
                proposed_slots=proposed_slots,
                address=address,
                status=InterviewStatus.PROPOSED,
            )
            self.session.add(interview)
        else:
            interview.proposed_slots = proposed_slots
            interview.address = address
            interview.scheduled_at = None
            interview.status = InterviewStatus.PROPOSED
        await self.session.flush()
        return interview

    async def confirm(self, interview: Interview, scheduled_at: datetime) -> None:
        """Кандидат выбрал слот — фиксируем время собеседования."""
        interview.scheduled_at = scheduled_at
        interview.proposed_slots = None
        interview.status = InterviewStatus.SCHEDULED
        await self.session.flush()

    async def set_status(self, interview: Interview, status: InterviewStatus) -> None:
        interview.status = status
        await self.session.flush()
