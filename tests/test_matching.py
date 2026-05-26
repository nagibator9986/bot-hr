"""Тесты scoring-логики матчинга (ТЗ §4) — вилка зарплат с допуском."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.core.constants import Schedule
from app.services.matching import normalize_position, salary_fits, score_pair


def _candidate(**kwargs: object) -> SimpleNamespace:
    defaults = {
        "city": "Алматы",
        "position_normalized": "повар",
        "experience_years": 3,
        "expected_salary": 250_000,
        "schedule": Schedule.SHIFT.value,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _vacancy(**kwargs: object) -> SimpleNamespace:
    defaults = {
        "city": "Алматы",
        "position_normalized": "повар",
        "experience_min": 1,
        "salary_min": 250_000,
        "salary_max": 300_000,
        "schedule": Schedule.SHIFT.value,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_perfect_match_passes_threshold() -> None:
    s = score_pair(_candidate(), _vacancy())
    assert s.score == 100
    assert s.passes_threshold


def test_different_city_returns_zero() -> None:
    s = score_pair(_candidate(city="Алматы"), _vacancy(city="Астана"))
    assert s.score == 0


def test_different_position_returns_zero() -> None:
    s = score_pair(
        _candidate(position_normalized="повар"),
        _vacancy(position_normalized="бариста"),
    )
    assert s.score == 0


def test_low_experience_does_not_exclude() -> None:
    # Опыт — мягкий критерий: меньше требуемого не отсекает, только -15 баллов.
    s = score_pair(_candidate(experience_years=0), _vacancy(experience_min=5))
    assert s.passes_threshold
    assert s.breakdown["experience"] == 0


# ── Зарплатная вилка с допуском ─────────────────────────────────────────────
def test_salary_within_range_full_points() -> None:
    # Ожидание 250к, вилка 250–300к → в бюджете, полные баллы.
    s = score_pair(_candidate(expected_salary=250_000), _vacancy())
    assert s.breakdown["salary"] == 10


def test_salary_slightly_over_still_shows() -> None:
    # Ожидание 320к, верх вилки 300к (+6.7%, в пределах допуска 20%) → показываем без баллов.
    s = score_pair(_candidate(expected_salary=320_000), _vacancy(salary_max=300_000))
    assert s.passes_threshold
    assert s.breakdown["salary"] == 0


def test_salary_far_over_excluded() -> None:
    # Ожидание 400к, верх вилки 300к (+33%, сверх допуска) → пара отброшена.
    s = score_pair(_candidate(expected_salary=400_000), _vacancy(salary_max=300_000))
    assert s.score == 0
    assert not s.passes_threshold


@pytest.mark.parametrize(
    "expected,show,in_budget",
    [
        (250_000, True, True),    # ниже верха вилки
        (300_000, True, True),    # ровно верх вилки
        (330_000, True, False),   # +10% — показываем, без баллов
        (360_000, True, False),   # +20% ровно — граница допуска
        (380_000, False, False),  # +27% — сверх допуска
    ],
)
def test_salary_fits_tolerance(expected: int, show: bool, in_budget: bool) -> None:
    vacancy = _vacancy(salary_max=300_000)
    assert salary_fits(expected, vacancy) == (show, in_budget)


def test_normalize_position_synonyms() -> None:
    assert normalize_position("повар") == "повар"
    assert normalize_position("Бариста") == "бариста"
    assert normalize_position("chef") == "шеф-повар"
    assert normalize_position("повар-универсал") == "повар"
    assert normalize_position("мойщик посуды") == "посудомойщик"
