"""Зеркалирование данных в Google Sheets (ТЗ §9).

Используем gspread (sync) через asyncio.to_thread. Все ошибки ловим — синк с Sheets
не должен ломать пользовательский сценарий.
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime
from typing import Any, cast

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import ValueInputOption
from pydantic import SecretStr

from app.config import settings
from app.core.logger import get_logger

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

    async def append_row(self, sheet_name: str, row: list[Any]) -> None:
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


def _stringify(v: Any) -> str:
    if isinstance(v, datetime):
        return v.isoformat(sep=" ", timespec="seconds")
    if v is None:
        return ""
    return str(v)
