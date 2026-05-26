"""Тесты текстовых утилит."""

from __future__ import annotations

from app.utils.text import mask_address, mask_name, normalize


def test_normalize_brings_to_lemma() -> None:
    result = normalize("Ищу работу поваром")
    assert "работа" in result
    assert "повар" in result


def test_mask_name() -> None:
    assert mask_name("Айдар") == "А***"
    assert mask_name("") == "***"


def test_mask_address_removes_house_numbers() -> None:
    masked = mask_address("ул. Абая, 100")
    assert "100" not in masked
    assert "Абая" in masked
    assert masked.startswith("район")
