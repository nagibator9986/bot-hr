"""Репозиторий User."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Role
from app.db.models.user import User


class UserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_tg_id(self, tg_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.tg_id == tg_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_or_create(self, tg_id: int, *, tg_username: str | None = None) -> User:
        user = await self.get_by_tg_id(tg_id)
        if user is None:
            user = User(tg_id=tg_id, tg_username=tg_username)
            self.session.add(user)
            await self.session.flush()
        elif tg_username and user.tg_username != tg_username:
            user.tg_username = tg_username
        return user

    async def set_role(self, user: User, role: Role) -> None:
        user.role = role
        await self.session.flush()
