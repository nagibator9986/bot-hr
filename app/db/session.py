"""Async-engine и фабрика сессий."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings


def _make_engine() -> AsyncEngine:
    return create_async_engine(
        settings.async_db_url,
        echo=settings.db_echo,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=10,
    )


engine: AsyncEngine = _make_engine()

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def dispose_engine(eng: AsyncEngine) -> None:
    await eng.dispose()
