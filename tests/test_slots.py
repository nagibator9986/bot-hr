"""Тесты парсинга слотов времени собеседования."""

from __future__ import annotations

from datetime import UTC

from app.utils.time import parse_slots


def test_parse_multiple_slots() -> None:
    slots = parse_slots("22.12 14:00\n23.12 11:30")
    assert len(slots) == 2
    assert all(s.tzinfo == UTC for s in slots)
    assert slots[0] < slots[1]  # отсортированы


def test_parse_comma_separated() -> None:
    slots = parse_slots("22.12 09:00, 22.12 18:00")
    assert len(slots) == 2


def test_parse_limits_to_three() -> None:
    slots = parse_slots("22.12 09:00\n23.12 09:00\n24.12 09:00\n25.12 09:00")
    assert len(slots) == 3


def test_parse_garbage_returns_empty() -> None:
    assert parse_slots("завтра вечером") == []
    assert parse_slots("") == []


def test_parse_deduplicates() -> None:
    slots = parse_slots("22.12 14:00\n22.12 14:00")
    assert len(slots) == 1


def test_local_time_converted_to_utc() -> None:
    # 14:00 в Алматы (UTC+5) → 09:00 UTC.
    slots = parse_slots("22.12.2026 14:00")
    assert len(slots) == 1
    assert slots[0].hour == 9
