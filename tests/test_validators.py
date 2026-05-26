"""Тесты валидаторов пользовательского ввода."""

from __future__ import annotations

import pytest
from app.utils.validators import parse_age, parse_phone, parse_salary


@pytest.mark.parametrize(
    "value,expected",
    [
        ("25", 25),
        ("14", 14),
        ("80", 80),
        ("13", None),  # ниже границы
        ("81", None),  # выше границы
        ("мне 30 лет", 30),
        ("abc", None),
        ("", None),
    ],
)
def test_parse_age(value: str, expected: int | None) -> None:
    assert parse_age(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("250000", 250_000),
        ("250 000", 250_000),
        ("250,000", 250_000),
        ("450000 тг", 450_000),
        ("450 000 тенge".replace("ge", "ге"), 450_000),
        ("250к", 250_000),
        ("250 тыс", 250_000),
        ("от 400000", 400_000),
        ("100", None),  # ниже мин (1000)
        ("abc", None),
    ],
)
def test_parse_salary(value: str, expected: int | None) -> None:
    assert parse_salary(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("4", 4),
        ("4 года", 4),
        ("нет", 0),
        ("без опыта", 0),
        ("5+", 5),
        ("полгода", 0),
    ],
)
def test_parse_experience(value: str, expected: int | None) -> None:
    from app.utils.validators import parse_experience

    assert parse_experience(value) == expected


def test_parse_phone_kz_format() -> None:
    assert parse_phone("+77001234567") == "+77001234567"
    assert parse_phone("87001234567") == "+77001234567"
    assert parse_phone("8 700 123 45 67") == "+77001234567"


def test_parse_phone_invalid() -> None:
    assert parse_phone("123") is None
    assert parse_phone("not a phone") is None
