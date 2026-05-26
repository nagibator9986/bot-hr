"""Глобальные фикстуры pytest."""

from __future__ import annotations

import os

# Подменяем env ДО импорта app.config — Settings жадно читает .env
os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("DB_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("BOT_USERNAME", "TestBot")
os.environ.setdefault("ENVIRONMENT", "dev")
