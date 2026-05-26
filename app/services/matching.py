"""Матчер кандидатов и вакансий (ТЗ §4).

Единое правило для обеих сторон просмотра — вся логика совместимости в score_pair:
  • Город и должность — обязательны (не совпали → score 0, пара отброшена).
  • Зарплата — вилка вакансии [salary_min, salary_max]. Если ожидание кандидата
    превышает верх вилки больше чем на SALARY_TOLERANCE → пара отброшена.
  • Опыт и график — мягкие критерии: влияют только на ранжирование, не отсекают.

Репозитории делают лишь дешёвую предвыборку (город+должность+статус), а
окончательное решение принимает score_pair — поэтому HR и кандидат видят
симметрично согласованные результаты.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    MATCH_THRESHOLD,
    MATCH_WEIGHTS,
    SALARY_TOLERANCE,
    Schedule,
)
from app.db.models.candidate import Candidate
from app.db.models.vacancy import Vacancy
from app.repositories.candidate import CandidateRepo
from app.repositories.match import MatchRepo
from app.repositories.vacancy import VacancyRepo

# ── Совместимость графиков ──────────────────────────────────────────────────
_SCHEDULE_COMPATIBLE: dict[Schedule, frozenset[Schedule]] = {
    Schedule.FULL_TIME: frozenset({Schedule.FULL_TIME, Schedule.SHIFT}),
    Schedule.SHIFT: frozenset({Schedule.SHIFT, Schedule.FULL_TIME, Schedule.FLEXIBLE}),
    Schedule.PART_TIME: frozenset({Schedule.PART_TIME, Schedule.FLEXIBLE}),
    Schedule.FLEXIBLE: frozenset({Schedule.FLEXIBLE, Schedule.SHIFT, Schedule.PART_TIME}),
}


@dataclass(frozen=True, slots=True)
class MatchScore:
    score: int
    breakdown: dict[str, int]

    @property
    def passes_threshold(self) -> bool:
        return self.score >= MATCH_THRESHOLD


def salary_fits(expected: int, vacancy: Vacancy) -> tuple[bool, bool]:
    """Сравнивает ожидание кандидата с вилкой вакансии.

    Возвращает (показывать_ли, в_бюджете_ли):
      • показывать — ожидание не выше верха вилки с учётом допуска;
      • в_бюджете — ожидание не превышает верх вилки (полные баллы за зарплату).
    """
    cap = float(vacancy.salary_max)
    if expected <= cap:
        return True, True
    if expected <= cap * (1.0 + SALARY_TOLERANCE):
        return True, False  # чуть выше бюджета — показываем, но без баллов
    return False, False     # сильно выше бюджета — пара несовместима


def score_pair(candidate: Candidate, vacancy: Vacancy) -> MatchScore:
    """Скорит пару (кандидат, вакансия). См. CLAUDE.md §6.2."""
    breakdown: dict[str, int] = {}

    # Город — обязателен.
    if candidate.city.strip().lower() != vacancy.city.strip().lower():
        return MatchScore(score=0, breakdown={"city": 0})
    breakdown["city"] = MATCH_WEIGHTS["city"]

    # Должность — обязательна (по нормализованному виду).
    if candidate.position_normalized != vacancy.position_normalized:
        return MatchScore(score=0, breakdown=breakdown | {"position": 0})
    breakdown["position"] = MATCH_WEIGHTS["position"]

    # Зарплата — вилка с допуском. Сильное превышение бюджета отбрасывает пару.
    show, in_budget = salary_fits(int(candidate.expected_salary), vacancy)
    if not show:
        return MatchScore(score=0, breakdown=breakdown | {"salary": 0})
    breakdown["salary"] = MATCH_WEIGHTS["salary"] if in_budget else 0

    # Опыт — мягкий критерий (не отсекает, только ранжирует).
    breakdown["experience"] = (
        MATCH_WEIGHTS["experience"]
        if candidate.experience_years >= vacancy.experience_min
        else 0
    )

    # График — мягкий критерий.
    candidate_schedule = Schedule(candidate.schedule)
    vacancy_schedule = Schedule(vacancy.schedule)
    breakdown["schedule"] = (
        MATCH_WEIGHTS["schedule"]
        if vacancy_schedule in _SCHEDULE_COMPATIBLE.get(candidate_schedule, frozenset())
        else 0
    )

    return MatchScore(score=sum(breakdown.values()), breakdown=breakdown)


def preferred_area_matches(candidate: Candidate, vacancy: Vacancy) -> bool:
    area = (candidate.preferred_area or "").strip().lower()
    if not area:
        return False
    address = vacancy.address.strip().lower()
    return area in address or address in area


class MatchingService:
    """Бизнес-логика подбора. Хендлеры дёргают именно её."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.candidates = CandidateRepo(session)
        self.vacancies = VacancyRepo(session)
        self.matches = MatchRepo(session)

    async def find_candidates_for_vacancy(self, vacancy_id: int) -> list[tuple[Candidate, int]]:
        """[(candidate, score), ...] выше порога, по убыванию score."""
        vacancy = await self.vacancies.get(vacancy_id)
        if vacancy is None:
            return []
        candidates = await self.candidates.search_for_vacancy(
            city=vacancy.city, position_normalized=vacancy.position_normalized
        )
        scored = [
            (c, s.score)
            for c in candidates
            if (s := score_pair(c, vacancy)).passes_threshold
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    async def find_vacancies_for_candidate(
        self, candidate: Candidate
    ) -> list[tuple[Vacancy, int]]:
        """[(vacancy, score), ...] выше порога, по убыванию score."""
        vacancies = await self.vacancies.search_for_candidate(
            city=candidate.city, position_normalized=candidate.position_normalized
        )
        scored = [
            (v, s.score)
            for v in vacancies
            if (s := score_pair(candidate, v)).passes_threshold
        ]
        scored.sort(
            key=lambda item: (preferred_area_matches(candidate, item[0]), item[1]),
            reverse=True,
        )
        return scored

    async def persist_match(self, *, candidate_id: int, vacancy_id: int, score: int) -> None:
        await self.matches.upsert(
            candidate_id=candidate_id, vacancy_id=vacancy_id, score=score
        )


# Канонизация должности — единая реализация в utils.text (словарь HoReCa-синонимов).
from app.utils.text import normalize_position as normalize_position  # noqa: E402
