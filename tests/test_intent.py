"""Тесты intent recognition (ТЗ §1.1)."""

from __future__ import annotations

import pytest
from app.core.constants import Intent
from app.services.intent import detect_intent


@pytest.mark.parametrize(
    "text,expected",
    [
        # Соискатели
        ("Ищу работу", Intent.SEEKING_JOB),
        ("Хочу устроиться на работу", Intent.SEEKING_JOB),
        ("Есть вакансии?", Intent.SEEKING_JOB),
        ("Нужна подработка", Intent.SEEKING_JOB),
        # Работодатели
        ("Нужен повар", Intent.SEEKING_EMPLOYEE),
        ("Хочу разместить вакансию", Intent.SEEKING_EMPLOYEE),
        ("Ищу сотрудника", Intent.SEEKING_EMPLOYEE),
        ("Требуется бариста", Intent.SEEKING_EMPLOYEE),
        # Неоднозначные
        ("Привет", Intent.UNKNOWN),
        ("", Intent.UNKNOWN),
    ],
)
def test_detect_intent(text: str, expected: Intent) -> None:
    result = detect_intent(text)
    assert result.intent == expected


def test_confidence_is_normalized() -> None:
    result = detect_intent("Ищу работу повара")
    assert 0.0 <= result.confidence <= 1.0
