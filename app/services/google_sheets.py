"""Зеркалирование данных в Google Sheets (ТЗ §9).

Используем gspread (sync) через asyncio.to_thread. Все ошибки ловим — синк с Sheets
не должен ломать пользовательский сценарий.
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import ValueInputOption
from pydantic import SecretStr

from app.config import settings
from app.core.logger import get_logger
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.db.models.candidate import Candidate
    from app.db.models.employer import Employer
    from app.db.models.vacancy import Vacancy

log = get_logger("sheets")

SHEET_APPLICANTS = "Applicants"
SHEET_EMPLOYERS = "Employers"
SHEET_VACANCIES = "Vacancies"
SHEET_INTERVIEWS = "Interviews"

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class GoogleSheetsService:
    """Тонкая обёртка над gspread с async-фасадом и устойчивостью к ошибкам."""

    def __init__(self) -> None:
        self._client: gspread.Client | None = None

    def _ensure_client(self) -> gspread.Client | None:
        if self._client is not None:
            return self._client
        if not settings.google_sheet_id:
            log.info("sheets_disabled", reason="missing config")
            return None
        creds = self._load_credentials()
        if creds is None:
            return None
        self._client = gspread.authorize(creds)
        return self._client

    def _load_credentials(self) -> Credentials | None:
        if settings.google_sa_json_path:
            creds = Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
                str(settings.google_sa_json_path), scopes=_SCOPES
            )
            return cast(Credentials, creds)

        raw_json = settings.google_sa_json
        if settings.google_sa_json_b64:
            try:
                raw_json = SecretStr(
                    base64.b64decode(
                        settings.google_sa_json_b64.get_secret_value()
                    ).decode("utf-8")
                )
            except (ValueError, UnicodeDecodeError) as exc:
                log.warning("sheets_credentials_invalid", error=str(exc))
                return None

        if raw_json is None:
            log.info("sheets_disabled", reason="missing credentials")
            return None

        try:
            parsed = json.loads(raw_json.get_secret_value())
        except json.JSONDecodeError as exc:
            log.warning("sheets_credentials_invalid", error=str(exc))
            return None
        if not isinstance(parsed, dict):
            log.warning("sheets_credentials_invalid", error="json must be an object")
            return None
        info = cast(dict[str, Any], parsed)
        creds = Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
            info, scopes=_SCOPES
        )
        return cast(Credentials, creds)

    @property
    def enabled(self) -> bool:
        return bool(settings.google_sheet_id)

    async def append_row(self, sheet_name: str, row: list[Any]) -> None:
        if not self.enabled:
            return  # синк не настроен — не тратим поток и не шумим в логах
        try:
            await asyncio.to_thread(self._append_sync, sheet_name, row)
        except Exception as e:
            log.warning("sheets_append_failed", sheet=sheet_name, error=str(e))

    def _append_sync(self, sheet_name: str, row: list[Any]) -> None:
        client = self._ensure_client()
        sheet_id = settings.google_sheet_id
        if client is None or sheet_id is None:
            return
        sheet = client.open_by_key(sheet_id).worksheet(sheet_name)
        sheet.append_row(
            [_stringify(v) for v in row],
            value_input_option=ValueInputOption.user_entered,
        )

    async def update_status(
        self, sheet_name: str, row_id: int, status: str, *, id_column: str = "A"
    ) -> None:
        if not self.enabled:
            return
        try:
            await asyncio.to_thread(self._update_status_sync, sheet_name, row_id, status, id_column)
        except Exception as e:
            log.warning("sheets_update_failed", sheet=sheet_name, id=row_id, error=str(e))

    def _update_status_sync(self, sheet_name: str, row_id: int, status: str, id_column: str) -> None:
        client = self._ensure_client()
        sheet_id = settings.google_sheet_id
        if client is None or sheet_id is None:
            return
        sheet = client.open_by_key(sheet_id).worksheet(sheet_name)
        # gspread 6.x: find() возвращает None если не нашёл (не бросает исключение).
        cell = sheet.find(str(row_id), in_column=ord(id_column.upper()) - 64)
        if cell is None:
            log.warning("sheets_row_not_found", sheet=sheet_name, id=row_id)
            return
        # Колонка статуса — для каждой таблицы своя позиция.
        status_col = {
            SHEET_APPLICANTS: 11,
            SHEET_VACANCIES: 9,
            SHEET_INTERVIEWS: 7,
        }.get(sheet_name)
        if status_col is None:
            return
        sheet.update_cell(cell.row, status_col, status)

    # ── Высокоуровневое зеркалирование доменных событий (см. docs/SHEETS.md) ──
    async def mirror_candidate(self, candidate: Candidate) -> None:
        """Создана анкета → строка в лист Applicants."""
        await self.append_row(
            SHEET_APPLICANTS,
            [
                candidate.id,
                candidate.name,
                candidate.age,
                candidate.city,
                candidate.desired_position,
                candidate.experience_years,
                int(candidate.expected_salary),
                candidate.schedule,
                candidate.contact,
                candidate.status,
                utcnow(),
            ],
        )

    async def mirror_employer(self, employer: Employer) -> None:
        """Создан работодатель → строка в лист Employers."""
        await self.append_row(
            SHEET_EMPLOYERS,
            [
                employer.id,
                employer.company_name,
                employer.city,
                employer.contact_person,
                employer.phone,
                utcnow(),
            ],
        )

    async def mirror_vacancy(self, vacancy: Vacancy, *, company: str) -> None:
        """Создана вакансия → строка в лист Vacancies."""
        await self.append_row(
            SHEET_VACANCIES,
            [
                vacancy.id,
                company,
                vacancy.position,
                f"{int(vacancy.salary_min)}–{int(vacancy.salary_max)}",
                vacancy.schedule,
                vacancy.address,
                _requirements_summary(vacancy.requirements),
                vacancy.status,
                utcnow(),
            ],
        )

    async def mirror_interview(
        self,
        *,
        interview_id: int,
        candidate_name: str,
        vacancy_position: str,
        company: str,
        scheduled_at: datetime,
        status: str,
    ) -> None:
        """Назначено собеседование → строка в лист Interviews."""
        await self.append_row(
            SHEET_INTERVIEWS,
            [
                interview_id,
                candidate_name,
                vacancy_position,
                company,
                scheduled_at.date().isoformat(),
                scheduled_at.strftime("%H:%M"),
                status,
            ],
        )


def _requirements_summary(requirements: Any) -> str:
    """JSONB требований вакансии → короткая строка для листа."""
    if not isinstance(requirements, dict):
        return ""
    skills = requirements.get("skills")
    if isinstance(skills, list) and skills:
        return ", ".join(str(s) for s in skills)
    return str(requirements.get("summary") or requirements.get("raw") or "")


def _stringify(v: Any) -> str:
    if isinstance(v, datetime):
        return v.isoformat(sep=" ", timespec="seconds")
    if v is None:
        return ""
    return str(v)


# Синглтон — импортируется хендлерами как `from app.services.google_sheets import google_sheets`.
google_sheets = GoogleSheetsService()
