"""Репозитории Employer + Vacancy."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import VacancyStatus, VerificationStatus
from app.db.models.employer import Employer
from app.db.models.vacancy import Vacancy


class EmployerRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user_id(self, user_id: int) -> Employer | None:
        result = await self.session.execute(select(Employer).where(Employer.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, employer_id: int) -> Employer | None:
        return await self.session.get(Employer, employer_id)

    async def list_pending(self, *, limit: int = 50) -> list[Employer]:
        """Работодатели, ожидающие HR-проверки (verification_status = pending)."""
        stmt = (
            select(Employer)
            .where(Employer.verification_status == VerificationStatus.PENDING)
            .order_by(Employer.created_at)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert(self, user_id: int, **fields: object) -> Employer:
        employer = await self.get_by_user_id(user_id)
        if employer is None:
            employer = Employer(user_id=user_id, **fields)
            self.session.add(employer)
        else:
            for k, v in fields.items():
                setattr(employer, k, v)
        await self.session.flush()
        return employer


class VacancyRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, employer_id: int, **fields: object) -> Vacancy:
        vacancy = Vacancy(employer_id=employer_id, **fields)
        self.session.add(vacancy)
        await self.session.flush()
        return vacancy

    async def get(self, vacancy_id: int) -> Vacancy | None:
        return await self.session.get(Vacancy, vacancy_id)

    async def get_with_employer(self, vacancy_id: int) -> Vacancy | None:
        stmt = (
            select(Vacancy)
            .where(Vacancy.id == vacancy_id)
            .options(selectinload(Vacancy.employer).selectinload(Employer.user))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Vacancy]:
        stmt = select(Vacancy).where(Vacancy.status == VacancyStatus.ACTIVE)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def search_for_candidate(
        self, *, city: str, position_normalized: str
    ) -> list[Vacancy]:
        """Дешёвая предвыборка вакансий: город + должность + активный статус.

        Зарплата/опыт/график оцениваются в matching.score_pair.
        """
        stmt = (
            select(Vacancy)
            .where(
                Vacancy.city == city,
                Vacancy.position_normalized == position_normalized,
                Vacancy.status == VacancyStatus.ACTIVE,
            )
            .options(selectinload(Vacancy.employer))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_employer(self, employer_id: int) -> list[Vacancy]:
        stmt = (
            select(Vacancy)
            .where(Vacancy.employer_id == employer_id)
            .order_by(Vacancy.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def set_status(self, vacancy: Vacancy, status: VacancyStatus) -> None:
        vacancy.status = status
        await self.session.flush()

    async def list_by_statuses(
        self, statuses: list[VacancyStatus], *, limit: int = 20
    ) -> list[Vacancy]:
        stmt = (
            select(Vacancy)
            .options(selectinload(Vacancy.employer))
            .where(Vacancy.status.in_(statuses))
            .order_by(Vacancy.updated_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
