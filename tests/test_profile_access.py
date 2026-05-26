from __future__ import annotations

from types import SimpleNamespace

from app.services.matching import preferred_area_matches
from app.services.profile import (
    render_candidate_card,
    render_candidate_summary,
    render_vacancy_card,
)


def _candidate(**kwargs: object) -> SimpleNamespace:
    defaults = {
        "name": "Айдар",
        "age": 25,
        "city": "Алматы",
        "preferred_area": "Абая",
        "desired_position": "Повар",
        "position_normalized": "повар",
        "experience_years": 3,
        "schedule": "shift",
        "expected_salary": 320_000,
        "contact": "+77001234567",
        "about": "Спокойный и аккуратный.",
        "previous_jobs": None,
        "resume_file_id": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _vacancy(**kwargs: object) -> SimpleNamespace:
    employer = kwargs.pop(
        "employer",
        SimpleNamespace(company_name="Sunrise", is_verified=True, phone="+77005554433"),
    )
    defaults = {
        "position": "Повар",
        "position_normalized": "повар",
        "city": "Алматы",
        "salary_min": 300_000,
        "salary_max": 380_000,
        "schedule": "shift",
        "address": "ул. Абая, 100",
        "conditions": "Питание и форма",
        "requirements": {"raw": "Опыт от 2 лет"},
        "employer": employer,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_render_candidate_card_preview_hides_name_and_contact() -> None:
    card = render_candidate_card(_candidate(), preview=True)
    assert "А***" in card
    assert "+77001234567" not in card
    assert "контакт откроется после подписки" in card


def test_render_vacancy_card_preview_masks_company_and_address() -> None:
    card = render_vacancy_card(_vacancy(), preview=True)
    assert "***" in card
    assert "район Абая" in card
    assert "ул. Абая, 100" not in card


def test_candidate_summary_shows_area_and_missing_resume() -> None:
    summary = render_candidate_summary(_candidate())
    assert "Район / адрес поиска" in summary
    assert "Резюме: не прикреплено" in summary


def test_preferred_area_match_detects_address_overlap() -> None:
    assert preferred_area_matches(_candidate(preferred_area="Абая"), _vacancy(address="пр. Абая, 15"))
    assert not preferred_area_matches(_candidate(preferred_area="Самал"), _vacancy(address="ул. Абая, 15"))
