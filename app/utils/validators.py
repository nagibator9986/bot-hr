"""Валидация и нормализация пользовательского ввода.

Парсеры устойчивы к «живому» вводу: «450 000 тг», «450к», «от 400000»,
«4 года», «нет опыта» и т.п. Возвращают None при невалидном вводе.
"""

from __future__ import annotations

import re

import phonenumbers

# Слова-валюты и шум, которые срезаем перед парсингом числа.
_CURRENCY_NOISE = re.compile(
    r"(тенге|тнг|тг|₸|kzt|руб(лей|ля)?|р\.|долл|usd|\$|зарплата|зп|оклад|от|до|"
    r"в\s*месяц|/мес|мес\.?|примерно|около)",
    re.IGNORECASE,
)


def _extract_number(text: str) -> int | None:
    """Достаёт число из строки. Понимает суффикс 'к'/'k' (тысячи)."""
    cleaned = _CURRENCY_NOISE.sub(" ", text.lower())
    # Диапазон «400-500»: берём нижнюю границу.
    cleaned = cleaned.split("-")[0].split("–")[0].split("—")[0]

    m = re.search(r"(\d[\d\s.,]*)\s*(к|k|тыс)?", cleaned)
    if not m:
        return None

    raw = m.group(1).replace(" ", "").replace(".", "").replace(",", "")
    if not raw.isdigit():
        return None

    value = int(raw)
    if m.group(2):  # суффикс «к» — тысячи
        value *= 1000
    return value


def parse_int(value: str, *, min_v: int | None = None, max_v: int | None = None) -> int | None:
    n = _extract_number(value)
    if n is None:
        return None
    if min_v is not None and n < min_v:
        return None
    if max_v is not None and n > max_v:
        return None
    return n


def parse_age(value: str) -> int | None:
    return parse_int(value, min_v=14, max_v=80)


def parse_salary(value: str) -> int | None:
    """Зарплата в тенге. Принимает «450000», «450 000 тг», «450к», «от 400000»."""
    return parse_int(value, min_v=1_000, max_v=100_000_000)


def parse_experience(value: str) -> int | None:
    """Опыт в годах. «4», «4 года», «нет»/«без опыта» → 0, «5+» → 5, «полгода» → 0."""
    low = value.strip().lower()
    if any(w in low for w in ("нет", "без опыта", "не работал", "первый", "ноль")):
        return 0
    if "полгода" in low or "пол года" in low or "месяц" in low:
        return 0
    n = _extract_number(low)
    if n is None:
        return None
    return n if 0 <= n <= 60 else None


def parse_phone(value: str, *, default_region: str = "KZ") -> str | None:
    try:
        parsed = phonenumbers.parse(value, default_region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def clean_text(value: str, *, max_len: int = 500) -> str:
    """Тримминг и ограничение длины свободного текста."""
    return value.strip()[:max_len]


def parse_bin(value: str) -> str | None:
    """БИН/ИИН Казахстана — ровно 12 цифр. Пробелы и дефисы убираем."""
    digits = re.sub(r"[\s\-]", "", value.strip())
    if re.fullmatch(r"\d{12}", digits):
        return digits
    return None
