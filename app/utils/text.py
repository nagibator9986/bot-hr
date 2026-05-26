"""Текстовые утилиты: нормализация, лемматизация, маскирование."""

from __future__ import annotations

import re
from functools import lru_cache

import pymorphy3

_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)

_morph = pymorphy3.MorphAnalyzer()


def tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD_RE.finditer(text)]


@lru_cache(maxsize=10_000)
def lemma(word: str) -> str:
    return str(_morph.parse(word)[0].normal_form)


def normalize(text: str) -> str:
    """Возвращает строку из лемм через пробел. Для intent / сравнения должностей."""
    return " ".join(lemma(t) for t in tokenize(text))


def normalize_position(position: str) -> str:
    """Канонизирует название должности HoReCa для матчинга.

    Сначала ищем точный синоним, затем лемматизируем. Возвращает канонич. форму
    (напр. «шеф повар», «повар-универсал» → «шеф-повар» / «повар»).
    """
    from app.core.constants import HORECA_POSITIONS, POSITION_SYNONYMS

    low = position.strip().lower()

    # 1. Прямое совпадение с синонимом или канонич. должностью.
    if low in POSITION_SYNONYMS:
        return POSITION_SYNONYMS[low]
    if low in HORECA_POSITIONS:
        return low

    # 2. Лемматизированная форма.
    norm = normalize(low)
    if norm in POSITION_SYNONYMS:
        return POSITION_SYNONYMS[norm]
    if norm in HORECA_POSITIONS:
        return norm

    # 3. Частичное вхождение известной должности.
    for canonical in HORECA_POSITIONS:
        if canonical in norm or canonical in low:
            return canonical

    return norm


def mask_name(name: str) -> str:
    if not name:
        return "***"
    return f"{name[0]}***"


def mask_address(address: str) -> str:
    """Оставляем только район/улицу без номера дома. Грубо, но достаточно для preview."""
    # «ул. Абая, 100» → «район Абая»; «мкр. Самал-2, 30» → «район Самал»
    cleaned = re.sub(r"[\d/]+", "", address)
    parts = re.split(r"[,;]", cleaned)
    head = parts[0].strip() if parts else address
    head = re.sub(r"^(ул\.?|улица|пр\.?|проспект|мкр\.?|микрорайон|просп\.?)\s+", "", head, flags=re.I)
    return f"район {head.strip()}".rstrip()
