"""Парсинг реферальных deeplink-ов."""

from __future__ import annotations

import pytest
from app.services.referrals import make_referral_link, parse_start_param


def test_make_link_format() -> None:
    link = make_referral_link("SmartChefHR_bot", 12345)
    assert link == "https://t.me/SmartChefHR_bot?start=ref_12345"


@pytest.mark.parametrize(
    "param,expected",
    [
        ("ref_42", 42),
        ("ref_0", 0),
        ("ref_abc", None),
        ("hello", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_start_param(param: str | None, expected: int | None) -> None:
    assert parse_start_param(param) == expected
