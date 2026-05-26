"""Свайп-просмотр карточек (Дайвинчик-стиль).

Кандидат листает вакансии, работодатель — кандидатов. Реакция ❤️/👎 пишется
в Match. Взаимный ❤️ → mutual match → уведомление обеим сторонам.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import Reaction, Role, VacancyStatus
from app.db.models.candidate import Candidate
from app.db.models.employer import Employer
from app.db.models.match import Match
from app.db.models.vacancy import Vacancy
from app.repositories.match import MatchRepo
from app.services.gemini import gemini
from app.services.matching import MatchingService
from app.services.profile import (
    fmt_money,
    fmt_salary_range,
    position_label,
    requirements_text,
    schedule_label,
)


@dataclass(slots=True)
class Card:
    """Одна карточка для показа: медиа + связанный Match.

    `ai_hint` — короткая подсказка Gemini «почему подходит» (None, если AI выключен).
    """

    match: Match
    vacancy: Vacancy | None = None
    candidate: Candidate | None = None
    ai_hint: str | None = None


def _describe_candidate(c: Candidate) -> str:
    base = (
        f"{position_label(c.position_normalized, c.desired_position)}, "
        f"опыт {c.experience_years} лет, график {schedule_label(c.schedule)}, "
        f"ожидает {fmt_money(c.expected_salary)} ₸"
    )
    return f"{base}. О себе: {c.about}" if c.about else base


def _describe_vacancy(v: Vacancy) -> str:
    base = (
        f"{position_label(v.position_normalized, v.position)}, "
        f"зарплата {fmt_salary_range(v)} ₸, график {schedule_label(v.schedule)}. "
        f"Требования: {requirements_text(v.requirements)}"
    )
    return f"{base}. Условия: {v.conditions}" if v.conditions else base


class BrowseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.matches = MatchRepo(session)
        self.matching = MatchingService(session)

    # ── Кандидат листает вакансии ─────────────────────────────────────────
    async def next_for_candidate(self, candidate: Candidate) -> Card | None:
        scored = await self.matching.find_vacancies_for_candidate(candidate)
        if not scored:
            return None
        seen = await self.matches.reacted_vacancy_ids(candidate.id)
        for vacancy, score in scored:
            if vacancy.id in seen:
                continue
            match = await self.matches.upsert(
                candidate_id=candidate.id, vacancy_id=vacancy.id, score=score
            )
            full_vacancy = await self._load_vacancy(vacancy.id)
            hint = await gemini.explain_match(
                viewer="candidate",
                candidate_desc=_describe_candidate(candidate),
                vacancy_desc=_describe_vacancy(full_vacancy or vacancy),
            )
            return Card(match=match, vacancy=full_vacancy, ai_hint=hint)
        return None

    # ── Работодатель листает кандидатов под свою вакансию ─────────────────
    async def next_for_employer(self, vacancy: Vacancy) -> Card | None:
        scored = await self.matching.find_candidates_for_vacancy(vacancy.id)
        if not scored:
            return None
        seen = await self.matches.reacted_candidate_ids(vacancy.id)
        for candidate, score in scored:
            if candidate.id in seen:
                continue
            match = await self.matches.upsert(
                candidate_id=candidate.id, vacancy_id=vacancy.id, score=score
            )
            hint = await gemini.explain_match(
                viewer="employer",
                candidate_desc=_describe_candidate(candidate),
                vacancy_desc=_describe_vacancy(vacancy),
            )
            return Card(match=match, candidate=candidate, ai_hint=hint)
        return None

    async def react(
        self, *, match_id: int, by_role: Role, reaction: Reaction
    ) -> tuple[bool, Match | None]:
        """Записывает реакцию. Возвращает (взаимный_ли_интерес, полный_Match)."""
        match = await self.matches.get(match_id)
        if match is None:
            return False, None
        is_mutual = await self.matches.react(match, by_role=by_role, reaction=reaction)
        if is_mutual:
            full = await self.matches.get_full(match_id)
            return True, full
        return False, match

    async def _load_vacancy(self, vacancy_id: int) -> Vacancy | None:
        stmt = (
            select(Vacancy)
            .where(Vacancy.id == vacancy_id)
            .options(selectinload(Vacancy.employer).selectinload(Employer.user))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def employer_active_vacancy(self, employer_id: int) -> Vacancy | None:
        """Последняя активная вакансия работодателя — для просмотра кандидатов."""
        stmt = (
            select(Vacancy)
            .where(
                Vacancy.employer_id == employer_id,
                Vacancy.status == VacancyStatus.ACTIVE,
            )
            .order_by(Vacancy.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
