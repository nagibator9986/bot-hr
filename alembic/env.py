"""Async-friendly Alembic env. Подхватывает URL и метаданные из app.config / app.db."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from app.config import settings
from app.db.base import Base
from app.db.models import *  # регистрируем все таблицы
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

# URL берём из настроек приложения, чтобы не дублировать в alembic.ini.
config.set_main_option("sqlalchemy.url", settings.async_db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Таблицы, которыми управляют сторонние библиотеки — autogenerate их игнорирует.
_EXTERNAL_TABLES = {"apscheduler_jobs"}


def _include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name in _EXTERNAL_TABLES:
        return False
    if type_ == "index" and getattr(obj, "table", None) is not None:
        return obj.table.name not in _EXTERNAL_TABLES
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.async_db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
