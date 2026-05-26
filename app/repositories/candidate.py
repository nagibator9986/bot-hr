"""Репозиторий Candidate."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import CandidateStatus
from app.db.models.candidate import Candidate


class CandidateRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user_id(self, user_id: int) -> Candidate | None:
        result = await self.session.execute(select(Candidate).where(Candidate.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, candidate_id: int) -> Candidate | None:
        return await self.session.get(Candidate, candidate_id)

    async def upsert(self, user_id: int, **fields: object) -> Candidate:
        candidate = await self.get_by_user_id(user_id)
        if candidate is None:
            candidate = Candidate(user_id=user_id, **fields)
            self.session.add(candidate)
        else:
            for k, v in fields.items():
                setattr(candidate, k, v)
        await self.session.flush()
        return candidate

    async def search_for_vacancy(
        self, *, city: str, position_normalized: str
    ) -> list[Candidate]:
        """Дешёвая предвыборка: город + должность + активный статус.

        Зарплата, опыт и график оцениваются в matching.score_pair — здесь не
        фильтруются, чтобы HR и кандидат видели согласованные результаты.
        """
        stmt = select(Candidate).where(
            Candidate.city == city,
            Candidate.position_normalized == position_normalized,
            Candidate.status.in_(
                [CandidateStatus.NEW, CandidateStatus.SEARCHING, CandidateStatus.OFFERED]
            ),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def set_status(self, candidate: Candidate, status: CandidateStatus) -> None:
        candidate.status = status
        await self.session.flush()

    async def list_active(self, *, limit: int = 20) -> list[Candidate]:
        stmt = (
            select(Candidate)
            .where(
                Candidate.status.in_(
                    [
                        CandidateStatus.NEW,
                        CandidateStatus.SEARCHING,
                        CandidateStatus.OFFERED,
                        CandidateStatus.INVITED,
                    ]
                )
            )
            .order_by(Candidate.updated_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
