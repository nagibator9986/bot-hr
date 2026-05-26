"""Работа с ролями пользователя.

Пользователь может иметь и анкету соискателя, и профиль работодателя.
`User.role` в этом случае означает текущую активную роль интерфейса.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Role
from app.repositories.candidate import CandidateRepo
from app.repositories.vacancy import EmployerRepo


async def has_profile(session: AsyncSession, user_id: int, role: Role) -> bool:
    if role == Role.CANDIDATE:
        return await CandidateRepo(session).get_by_user_id(user_id) is not None
    if role == Role.EMPLOYER:
        return await EmployerRepo(session).get_by_user_id(user_id) is not None
    return False


async def available_roles(session: AsyncSession, user_id: int) -> list[Role]:
    roles: list[Role] = []
    if await has_profile(session, user_id, Role.CANDIDATE):
        roles.append(Role.CANDIDATE)
    if await has_profile(session, user_id, Role.EMPLOYER):
        roles.append(Role.EMPLOYER)
    return roles


async def preferred_role(session: AsyncSession, user_id: int, current: Role | None) -> Role | None:
    if current is not None and await has_profile(session, user_id, current):
        return current
    roles = await available_roles(session, user_id)
    if roles:
        return roles[0]
    return None
