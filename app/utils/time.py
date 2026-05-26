"""Утилиты времени. Всё внутри — UTC; для UI — Asia/Almaty."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import settings

LOCAL_TZ = ZoneInfo(settings.timezone)

# Форматы ввода слота времени работодателем — с указанием года.
_SLOT_FORMATS_WITH_YEAR = ("%d.%m.%Y %H:%M", "%d.%m.%y %H:%M")
# Слот без года: «ДД.ММ ЧЧ:ММ» — год подставляем сами.
_SLOT_NO_YEAR_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})")
_MAX_SLOTS = 3


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(LOCAL_TZ)


def format_dt(dt: datetime, fmt: str = "%d.%m %H:%M") -> str:
    return to_local(dt).strftime(fmt)


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def parse_slots(text: str) -> list[datetime]:
    """Разбирает слоты собеседования из текста работодателя.

    Понимает строки вида «21.05 14:00» / «21.05.2026 14:00», разделённые
    переводом строки, запятой или «;». Возвращает до 3 будущих слотов в UTC,
    отсортированных по возрастанию. Время трактуется как местное (Asia/Almaty).
    """
    now_local = datetime.now(tz=LOCAL_TZ)
    slots: list[datetime] = []
    for raw in re.split(r"[\n,;]+", text):
        chunk = raw.strip()
        if not chunk:
            continue
        parsed = _parse_one_slot(chunk, now_local)
        if parsed is not None and parsed > now_local:
            slots.append(parsed.astimezone(UTC))
    # уникальные, отсортированные, не больше лимита
    unique = sorted(set(slots))
    return unique[:_MAX_SLOTS]


def _parse_one_slot(chunk: str, now_local: datetime) -> datetime | None:
    # 1. Формат с указанным годом.
    for fmt in _SLOT_FORMATS_WITH_YEAR:
        try:
            return datetime.strptime(chunk, fmt).replace(tzinfo=LOCAL_TZ)
        except ValueError:
            continue
    # 2. Формат без года — подставляем текущий, при прошедшей дате — следующий.
    m = _SLOT_NO_YEAR_RE.fullmatch(chunk)
    if m is None:
        return None
    day, month, hour, minute = (int(g) for g in m.groups())
    try:
        dt = datetime(now_local.year, month, day, hour, minute, tzinfo=LOCAL_TZ)
    except ValueError:
        return None
    if dt < now_local:
        dt = dt.replace(year=now_local.year + 1)
    return dt
