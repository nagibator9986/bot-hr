"""AI-обогащение пользовательского ввода поверх rule-based логики.

Тонкая прослойка: сначала пробуем дешёвые правила (словари, regex), и только
если они не справились — обращаемся к Gemini. Так бот остаётся быстрым и
дешёвым на типовом вводе, а AI тратится точечно на сложные случаи.

Каждая функция возвращает результат всегда — даже без AI (graceful degradation).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.core.constants import HORECA_POSITIONS
from app.services.gemini import gemini
from app.utils.text import normalize_position
from app.utils.time import LOCAL_TZ, parse_slots

# Regex-фолбэк для опыта: «3 года», «опыт 5 лет», «от 2 г.».
_EXPERIENCE_RE = re.compile(r"(\d+)\s*(год|года|лет|г\.)", re.IGNORECASE)


async def resolve_position(raw_position: str) -> str:
    """Каноническая форма должности HoReCa.

    1. Rule-based (`normalize_position`) — словарь синонимов + морфология.
    2. Если результат не попал в известные должности — спрашиваем Gemini.
    3. AI не помог → возвращаем то, что дала нормализация (матчинг строгий
       по равенству, неизвестная форма просто не найдёт пар — это безопасно).
    """
    rule_based = normalize_position(raw_position)
    if rule_based in HORECA_POSITIONS:
        return rule_based

    ai_position = await gemini.normalize_position(raw_position)
    return ai_position or rule_based


def _experience_from_regex(raw_text: str) -> int:
    match = _EXPERIENCE_RE.search(raw_text)
    return int(match.group(1)) if match else 0


async def structure_requirements(raw_text: str) -> tuple[dict[str, Any], int]:
    """Разбирает текст требований вакансии.

    Возвращает (requirements_jsonb, experience_min):
      • requirements_jsonb — словарь для JSONB-поля Vacancy.requirements:
        всегда хранит исходный текст в `raw`; при успехе AI добавляет
        `skills` и `summary`;
      • experience_min — минимальный опыт в годах (AI → regex → 0).
    """
    raw_text = raw_text.strip()
    requirements: dict[str, Any] = {"raw": raw_text}
    regex_experience = _experience_from_regex(raw_text)

    structured = await gemini.structure_requirements(raw_text)
    if structured is None:
        return requirements, regex_experience

    requirements["skills"] = structured.skills
    requirements["summary"] = structured.summary
    # Опыт из AI приоритетнее; если AI вернул 0 — подстраховываемся regex-ом.
    experience = structured.experience_min or regex_experience
    return requirements, experience


def _parse_ai_slot(value: str) -> datetime | None:
    """Парсит 'YYYY-MM-DD HH:MM' (местное время) в aware-datetime."""
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
    except ValueError:
        return None


async def resolve_interview_slots(text: str) -> list[datetime]:
    """Разбирает слоты собеседования из текста работодателя (ТЗ §5.2).

    1. Строгий формат «ДД.ММ ЧЧ:ММ» — `parse_slots` (быстро, без сети).
    2. Не распознано → Gemini разбирает живую речь («завтра после обеда»).
    Возвращает до 3 будущих слотов в UTC, по возрастанию.
    """
    slots = parse_slots(text)
    if slots:
        return slots

    now_local = datetime.now(tz=LOCAL_TZ)
    ai_slots = await gemini.parse_interview_slots(
        text, now_local_iso=now_local.strftime("%Y-%m-%d %H:%M (%A)")
    )
    if not ai_slots:
        return []

    parsed: list[datetime] = []
    for raw in ai_slots:
        dt = _parse_ai_slot(raw)
        if dt is not None and dt > now_local:
            parsed.append(dt.astimezone(UTC))
    return sorted(set(parsed))[:3]
