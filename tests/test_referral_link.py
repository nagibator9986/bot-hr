"""Парсинг реферальных и промоутерских deeplink-ов."""

from __future__ import annotations

import pytest
from app.services.referrals import (
    make_promoter_link,
    make_referral_link,
    parse_promoter_param,
    parse_start_param,
)


def test_make_link_format() -> None:
    link = make_referral_link("SmartChefHR_bot", 12345)
    assert link == "https://t.me/SmartChefHR_bot?start=ref_12345"


def test_make_promoter_link_format() -> None:
    link = make_promoter_link("SmartChefHR_bot", "aidos9f3a")
    assert link == "https://t.me/SmartChefHR_bot?start=promo_aidos9f3a"


@pytest.mark.parametrize(
    "param,expected",
    [
        ("ref_42", 42),
        ("ref_0", 0),
        ("ref_abc", None),
        ("hello", None),
        ("promo_abc", None),  # промо-параметр — не обычный реферал
        ("", None),
        (None, None),
    ],
)
def test_parse_start_param(param: str | None, expected: int | None) -> None:
    assert parse_start_param(param) == expected


@pytest.mark.parametrize(
    "param,expected",
    [
        ("promo_aidos", "aidos"),
        ("promo_9f3a2b", "9f3a2b"),
        ("promo_", None),       # пустой код
        ("ref_42", None),       # обычный реферал — не промо
        ("hello", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_promoter_param(param: str | None, expected: str | None) -> None:
    assert parse_promoter_param(param) == expected
