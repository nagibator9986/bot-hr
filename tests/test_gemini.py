"""Тесты AI-слоя: чистые helpers, GeminiService, graceful degradation, обёртки."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.config import settings
from app.core.constants import HORECA_POSITIONS, Intent
from app.services import enrichment
from app.services.gemini import (
    GeminiService,
    RequirementsData,
    _LRUCache,
    extract_text,
    gemini,
    parse_json_object,
    strip_code_fences,
)
from app.services.intent import resolve_intent
from pydantic import SecretStr


# ─────────────────────────── чистые helpers ────────────────────────────────
class TestPureHelpers:
    def test_extract_text_happy(self):
        payload = {"candidates": [{"content": {"parts": [{"text": "привет"}]}}]}
        assert extract_text(payload) == "привет"

    def test_extract_text_joins_parts(self):
        payload = {"candidates": [{"content": {"parts": [{"text": "a"}, {"text": "b"}]}}]}
        assert extract_text(payload) == "ab"

    @pytest.mark.parametrize("payload", [{}, {"candidates": []}, {"candidates": [{}]}, None])
    def test_extract_text_bad_payloads(self, payload):
        assert extract_text(payload or {}) is None

    def test_strip_code_fences(self):
        assert strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
        assert strip_code_fences('{"a": 1}') == '{"a": 1}'

    def test_parse_json_object(self):
        assert parse_json_object('{"intent": "seeking_job"}') == {"intent": "seeking_job"}
        assert parse_json_object('```json\n{"x": 2}\n```') == {"x": 2}

    def test_parse_json_object_rejects_non_object(self):
        assert parse_json_object("[1, 2, 3]") is None
        assert parse_json_object("не json") is None


class TestLRUCache:
    def test_get_put(self):
        cache = _LRUCache(maxsize=2)
        cache.put("a", 1)
        assert cache.get("a") == 1
        assert cache.get("missing") is None

    def test_eviction_is_lru(self):
        cache = _LRUCache(maxsize=2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")          # «a» становится свежим
        cache.put("c", 3)       # вытесняется «b» — самый старый
        assert cache.get("b") is None
        assert cache.get("a") == 1
        assert cache.get("c") == 3


# ──────────────── graceful degradation: без ключа AI молчит ─────────────────
@pytest.mark.asyncio
class TestDisabled:
    async def test_all_methods_return_none_without_key(self, monkeypatch):
        # Явно гасим ключ — тест не должен зависеть от содержимого .env.
        monkeypatch.setattr(settings, "gemini_api_key", None)
        assert settings.ai_available is False
        svc = GeminiService()
        assert await svc.classify_intent("ищу работу") is None
        assert await svc.normalize_position("повар") is None
        assert await svc.structure_requirements("опыт 2 года") is None
        assert await svc.explain_match(viewer="candidate", candidate_desc="x", vacancy_desc="y") is None
        assert await svc.polish_about("я хороший повар умею всё") is None
        assert await svc.parse_interview_slots("завтра", now_local_iso="2026-05-21 10:00") is None
        assert await svc.answer_support("как работает бот?") is None


# ─────────────── фикстура: включаем AI и подменяем транспорт ────────────────
@pytest.fixture
def ai_on(monkeypatch):
    """Включает AI (фейковый ключ) и чистит кеш синглтона между тестами."""
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("test-key"))
    gemini._cache.clear()
    yield
    gemini._cache.clear()


@pytest.mark.asyncio
class TestGeminiServiceParsing:
    """Методы сервиса при замоканном транспорте `_generate`."""

    async def test_classify_intent_parses_response(self, ai_on, monkeypatch):
        async def fake(prompt, **kw):
            return '{"intent": "seeking_employee", "confidence": 0.91}'

        monkeypatch.setattr(gemini, "_generate", fake)
        result = await gemini.classify_intent("возьмём пару рук на кухню")
        assert result == (Intent.SEEKING_EMPLOYEE, 0.91)

    async def test_classify_intent_clamps_confidence(self, ai_on, monkeypatch):
        async def fake(prompt, **kw):
            return '{"intent": "seeking_job", "confidence": 5}'

        monkeypatch.setattr(gemini, "_generate", fake)
        intent, confidence = await gemini.classify_intent("хочу к вам")
        assert intent is Intent.SEEKING_JOB
        assert confidence == 1.0

    async def test_classify_intent_uses_cache(self, ai_on, monkeypatch):
        calls = []

        async def fake(prompt, **kw):
            calls.append(prompt)
            return '{"intent": "seeking_job", "confidence": 0.8}'

        monkeypatch.setattr(gemini, "_generate", fake)
        await gemini.classify_intent("одинаковый текст")
        await gemini.classify_intent("одинаковый текст")
        assert len(calls) == 1  # второй вызов обслужен из кеша

    async def test_normalize_position_known(self, ai_on, monkeypatch):
        async def fake(prompt, **kw):
            return '{"position": "повар"}'

        monkeypatch.setattr(gemini, "_generate", fake)
        assert await gemini.normalize_position("пиццайоло") == "повар"
        assert "повар" in HORECA_POSITIONS

    async def test_normalize_position_unknown(self, ai_on, monkeypatch):
        async def fake(prompt, **kw):
            return '{"position": "unknown"}'

        monkeypatch.setattr(gemini, "_generate", fake)
        assert await gemini.normalize_position("программист") is None

    async def test_structure_requirements(self, ai_on, monkeypatch):
        async def fake(prompt, **kw):
            return '{"experience_min": 3, "skills": ["латте-арт", "касса"], "summary": "Опытный бариста"}'

        monkeypatch.setattr(gemini, "_generate", fake)
        data = await gemini.structure_requirements("нужен бариста с опытом")
        assert isinstance(data, RequirementsData)
        assert data.experience_min == 3
        assert data.skills == ["латте-арт", "касса"]
        assert data.summary == "Опытный бариста"

    async def test_explain_match_one_line(self, ai_on, monkeypatch):
        async def fake(prompt, **kw):
            return '  Отличный матч по городу и опыту.\nлишняя строка  '

        monkeypatch.setattr(gemini, "_generate", fake)
        hint = await gemini.explain_match(
            viewer="candidate", candidate_desc="повар", vacancy_desc="повар"
        )
        assert hint == "Отличный матч по городу и опыту."

    async def test_polish_about(self, ai_on, monkeypatch):
        async def fake(prompt, **kw):
            return "Я ответственный повар с опытом работы в кафе."

        monkeypatch.setattr(gemini, "_generate", fake)
        polished = await gemini.polish_about("повар умею готовить норм")
        assert polished == "Я ответственный повар с опытом работы в кафе."

    async def test_polish_about_skips_short_text(self, ai_on, monkeypatch):
        async def fake(prompt, **kw):  # не должен вызваться
            raise AssertionError("AI не должен вызываться на коротком тексте")

        monkeypatch.setattr(gemini, "_generate", fake)
        assert await gemini.polish_about("ок") is None

    async def test_parse_interview_slots(self, ai_on, monkeypatch):
        async def fake(prompt, **kw):
            return '{"slots": ["2026-05-22 14:00", "2026-05-23 11:30"]}'

        monkeypatch.setattr(gemini, "_generate", fake)
        slots = await gemini.parse_interview_slots(
            "завтра в два или послезавтра в полдвенадцатого",
            now_local_iso="2026-05-21 10:00",
        )
        assert slots == ["2026-05-22 14:00", "2026-05-23 11:30"]

    async def test_answer_support(self, ai_on, monkeypatch):
        async def fake(prompt, **kw):
            return "Бот подбирает персонал в общепите. Откройте /menu."

        monkeypatch.setattr(gemini, "_generate", fake)
        answer = await gemini.answer_support("что умеет этот бот?")
        assert "общепит" in answer.lower()


# ─────────────── resolve_intent: правила + AI-подстраховка ──────────────────
@pytest.mark.asyncio
class TestResolveIntent:
    async def test_confident_rule_skips_ai(self, monkeypatch):
        async def fail(text):
            raise AssertionError("AI не должен вызываться при уверенных правилах")

        monkeypatch.setattr(gemini, "classify_intent", fail)
        result = await resolve_intent("ищу работу поваром")
        assert result.intent is Intent.SEEKING_JOB

    async def test_ai_fallback_on_unknown(self, monkeypatch):
        async def fake(text):
            return (Intent.SEEKING_JOB, 0.88)

        monkeypatch.setattr(gemini, "classify_intent", fake)
        # Фраза без ключевых слов — rule-based вернёт UNKNOWN.
        result = await resolve_intent("надоело без дела дома сидеть")
        assert result.intent is Intent.SEEKING_JOB
        assert result.confidence == 0.88

    async def test_ai_unavailable_keeps_rule_result(self, monkeypatch):
        async def none(text):
            return None

        monkeypatch.setattr(gemini, "classify_intent", none)
        result = await resolve_intent("абвгде")
        assert result.intent is Intent.UNKNOWN


# ───────────────────── enrichment: обёртки правила+AI ───────────────────────
@pytest.mark.asyncio
class TestEnrichment:
    async def test_resolve_position_rule_based_no_ai(self, monkeypatch):
        async def fail(raw):
            raise AssertionError("AI не нужен — справились правила")

        monkeypatch.setattr(gemini, "normalize_position", fail)
        assert await enrichment.resolve_position("шеф") == "шеф-повар"

    async def test_resolve_position_ai_fallback(self, monkeypatch):
        async def fake(raw):
            return "официант"

        monkeypatch.setattr(gemini, "normalize_position", fake)
        assert await enrichment.resolve_position("человек подавать блюда") == "официант"

    async def test_structure_requirements_regex_fallback(self, monkeypatch):
        async def none(raw):
            return None

        monkeypatch.setattr(gemini, "structure_requirements", none)
        req, exp = await enrichment.structure_requirements("опыт 4 года, ответственность")
        assert req == {"raw": "опыт 4 года, ответственность"}
        assert exp == 4

    async def test_structure_requirements_ai(self, monkeypatch):
        async def fake(raw):
            return RequirementsData(experience_min=2, skills=["мойка"], summary="Аккуратность")

        monkeypatch.setattr(gemini, "structure_requirements", fake)
        req, exp = await enrichment.structure_requirements("нужен помощник")
        assert req["skills"] == ["мойка"]
        assert req["summary"] == "Аккуратность"
        assert req["raw"] == "нужен помощник"
        assert exp == 2

    async def test_resolve_slots_strict_format_no_ai(self, monkeypatch):
        async def fail(text, **kw):
            raise AssertionError("AI не нужен — строгий формат распознан")

        monkeypatch.setattr(gemini, "parse_interview_slots", fail)
        slots = await enrichment.resolve_interview_slots("22.12 14:00")
        assert len(slots) == 1
        assert slots[0].tzinfo is not None

    async def test_resolve_slots_ai_fallback(self, monkeypatch):
        async def fake(text, **kw):
            return ["2026-12-25 10:00"]

        monkeypatch.setattr(gemini, "parse_interview_slots", fake)
        slots = await enrichment.resolve_interview_slots("ближе к рождеству утром")
        assert len(slots) == 1
        assert slots[0].tzinfo is UTC

    async def test_resolve_slots_drops_past_ai_slots(self, monkeypatch):
        async def fake(text, **kw):
            return ["2000-01-01 10:00"]  # прошедшая дата отбрасывается

        monkeypatch.setattr(gemini, "parse_interview_slots", fake)
        assert await enrichment.resolve_interview_slots("когда-то давно") == []


def test_now_is_after_2026():
    """Страховка: слоты-тесты опираются на даты 2026 года как будущее."""
    assert datetime.now(tz=UTC).year >= 2026


# ─────────────── транспорт _generate: сборка запроса и разбор ───────────────
class _FakeResp:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        import json as _json

        return _json.dumps(self._payload)


class _FakeSession:
    def __init__(self, resp):
        self._resp = resp
        self.last_call = None

    def post(self, url, *, json, headers, timeout):
        self.last_call = {"url": url, "json": json, "headers": headers}
        return self._resp


@pytest.mark.asyncio
class TestGenerateTransport:
    """Проверяем сам HTTP-слой `_generate` на фейковой aiohttp-сессии."""

    async def test_builds_request_and_parses_ok(self, ai_on, monkeypatch):
        payload = {"candidates": [{"content": {"parts": [{"text": "ответ"}]}}]}
        fake = _FakeSession(_FakeResp(200, payload))

        async def fake_session():
            return fake

        monkeypatch.setattr(gemini, "_ensure_session", fake_session)
        out = await gemini._generate(
            "запрос", system="инструкция", schema={"type": "OBJECT"}
        )
        assert out == "ответ"
        call = fake.last_call
        assert call["url"].endswith(":generateContent")
        assert "x-goog-api-key" in call["headers"]
        assert call["json"]["systemInstruction"]["parts"][0]["text"] == "инструкция"
        gen = call["json"]["generationConfig"]
        assert gen["responseMimeType"] == "application/json"
        assert gen["responseSchema"] == {"type": "OBJECT"}
        assert gen["thinkingConfig"]["thinkingBudget"] == 0

    async def test_http_error_returns_none(self, ai_on, monkeypatch):
        fake = _FakeSession(_FakeResp(500, {"error": "boom"}))

        async def fake_session():
            return fake

        monkeypatch.setattr(gemini, "_ensure_session", fake_session)
        assert await gemini._generate("запрос") is None
