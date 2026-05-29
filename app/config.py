"""Конфигурация приложения. Источник правды — переменные окружения (.env)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, RedisDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _replace_url_scheme(url: str, replacements: tuple[tuple[str, str], ...]) -> str:
    for source, target in replacements:
        if url.startswith(source):
            return f"{target}{url[len(source):]}"
    return url


class Settings(BaseSettings):
    # ── Telegram ──────────────────────────────────────────────────────────
    bot_token: SecretStr
    bot_username: str = "SmartChefHR_bot"
    admin_ids: list[int] = Field(default_factory=list)

    # ── Database ──────────────────────────────────────────────────────────
    db_url: str = Field(validation_alias=AliasChoices("DB_URL", "DATABASE_URL"))
    db_echo: bool = False

    # ── Redis ─────────────────────────────────────────────────────────────
    redis_url: RedisDsn

    # ── Google Sheets ─────────────────────────────────────────────────────
    google_sa_json_path: Path | None = None
    google_sa_json: SecretStr | None = None
    google_sa_json_b64: SecretStr | None = None
    google_sheet_id: str | None = None

    # ── Payments ──────────────────────────────────────────────────────────
    payment_provider: Literal["manual", "telegram", "kaspi", "simulation"] = "manual"
    telegram_payment_token: SecretStr | None = None
    kaspi_api_key: SecretStr | None = None
    kaspi_merchant_id: str | None = None

    # ── Tariffs (KZT/month) ───────────────────────────────────────────────
    tariff_candidate: int = 1_000
    tariff_employer_basic: int = 10_000
    tariff_employer_extended: int = 20_000
    employer_basic_limit: int = 20
    employer_extended_limit: int = 50

    # ── Referral ──────────────────────────────────────────────────────────
    referral_bonus: int = 300
    referral_min_withdrawal: int = 1_000
    referral_withdrawal_delay_hours: int = 24

    # ── Google Gemini (генеративный AI) ───────────────────────────────────
    # Ключ из Google AI Studio (https://aistudio.google.com/apikey).
    # Если не задан — AI-функции выключаются, бот работает по rule-based логике.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_enabled: bool = True          # мастер-выключатель AI-функций
    gemini_timeout: float = 12.0         # таймаут одного запроса, сек

    # ── Misc ──────────────────────────────────────────────────────────────
    environment: Literal["dev", "stage", "prod"] = "dev"
    log_level: str = "INFO"
    timezone: str = "Asia/Almaty"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator(
        "gemini_api_key",
        "google_sa_json",
        "google_sa_json_b64",
        "telegram_payment_token",
        "kaspi_api_key",
        mode="before",
    )
    @classmethod
    def _blank_secret_is_none(cls, v: object) -> object:
        # Пустые optional-секреты в .env → None.
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator(
        "google_sa_json_path",
        "google_sheet_id",
        "kaspi_merchant_id",
        mode="before",
    )
    @classmethod
    def _blank_optional_is_none(cls, v: object) -> object:
        # Пустые optional-строки/пути из .env → None (иначе Path('') == Path('.')).
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, v: object) -> object:
        # Поддержка форматов: [1,2,3] / "1,2,3" / "[1,2,3]"
        if isinstance(v, str):
            cleaned = v.strip().strip("[]")
            if not cleaned:
                return []
            return [int(x.strip()) for x in cleaned.split(",") if x.strip()]
        return v

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"

    @property
    def async_db_url(self) -> str:
        """DB URL для SQLAlchemy async engine.

        Railway PostgreSQL обычно отдаёт DATABASE_URL как postgresql://... без
        async-драйвера. Приложению нужен asyncpg, поэтому нормализуем схему.
        """
        return _replace_url_scheme(
            self.db_url,
            (
                ("postgresql+asyncpg://", "postgresql+asyncpg://"),
                ("postgresql+psycopg2://", "postgresql+asyncpg://"),
                ("postgresql+psycopg://", "postgresql+asyncpg://"),
                ("postgresql://", "postgresql+asyncpg://"),
                ("postgres://", "postgresql+asyncpg://"),
            ),
        )

    @property
    def sync_db_url(self) -> str:
        """DB URL для sync-библиотек вроде APScheduler SQLAlchemyJobStore."""
        return _replace_url_scheme(
            self.db_url,
            (
                ("postgresql+psycopg2://", "postgresql+psycopg2://"),
                ("postgresql+asyncpg://", "postgresql+psycopg2://"),
                ("postgresql+psycopg://", "postgresql+psycopg2://"),
                ("postgresql://", "postgresql+psycopg2://"),
                ("postgres://", "postgresql+psycopg2://"),
            ),
        )

    @property
    def ai_available(self) -> bool:
        """True, если AI-функции можно использовать (есть ключ и не выключены)."""
        return self.gemini_enabled and self.gemini_api_key is not None


settings = Settings()
