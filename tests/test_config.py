"""Тесты production-конфигурации."""

from __future__ import annotations

from app.config import Settings


def _settings(db_url: str) -> Settings:
    return Settings(
        bot_token="123:test",
        db_url=db_url,
        redis_url="redis://localhost:6379/0",
        _env_file=None,
    )


def test_railway_database_url_alias(monkeypatch) -> None:
    monkeypatch.delenv("DB_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host:5432/db")

    settings = Settings(
        bot_token="123:test",
        redis_url="redis://localhost:6379/0",
        _env_file=None,
    )

    assert settings.db_url == "postgresql://u:p@host:5432/db"
    assert settings.async_db_url == "postgresql+asyncpg://u:p@host:5432/db"


def test_postgres_urls_are_normalized_for_async_and_sync_engines() -> None:
    settings = _settings("postgres://u:p@host:5432/db")

    assert settings.async_db_url == "postgresql+asyncpg://u:p@host:5432/db"
    assert settings.sync_db_url == "postgresql+psycopg2://u:p@host:5432/db"


def test_asyncpg_url_is_preserved_for_app_and_converted_for_scheduler() -> None:
    settings = _settings("postgresql+asyncpg://u:p@host:5432/db")

    assert settings.async_db_url == "postgresql+asyncpg://u:p@host:5432/db"
    assert settings.sync_db_url == "postgresql+psycopg2://u:p@host:5432/db"
