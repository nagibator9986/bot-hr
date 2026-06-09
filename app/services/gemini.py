"""Интеграция с Google Gemini API — генеративный AI как «умный слой» бота.

Зачем это нужно (бизнес-обоснование):
  ТЗ §7.1 прямо требует «NLP — понимание текста». Rule-based intent покрывает
  ~85 % коротких фраз, но ломается на живой речи («надоело дома сидеть»,
  «возьмём пару рук на кухню»). Gemini закрывает именно этот хвост, а заодно
  усиливает места, где словари бессильны: нестандартные должности, разбор
  требований вакансии, объяснение совместимости, разбор времени из речи,
  ответы на вопросы пользователей.

Где AI подключён (см. соответствующие сервисы/хендлеры):
  • intent.resolve_intent        — распознавание намерения (§1.1, §7.1);
  • enrichment.resolve_position  — канонизация должности HoReCa (§4);
  • enrichment.structure_requirements — требования → навыки (§3.1);
  • browse                       — «почему подходит» на карточках (💡 усиление ТЗ);
  • candidate                    — «причёсывание» текста «о себе»;
  • interview                    — разбор времени собеседования из речи (§5.2);
  • common                       — AI-поддержка: ответы на вопросы (§6, §10.10).

Принципы реализации:
  • **Graceful degradation.** Нет ключа / запрос упал / выключено флагом —
    каждый метод возвращает None, вызывающий код откатывается на старую логику.
    AI *улучшает* бота, но никогда не является единственной точкой отказа.
  • **Чистый сервис.** Модуль не знает про aiogram и БД — на входе текст,
    на выходе структура. Транспорт — aiohttp (уже в стеке через aiogram),
    никаких новых тяжёлых зависимостей и блокировок event-loop.
  • **Бюджет и латентность.** Жёсткий таймаут, отключённый «thinking», LRU-кеш
    идемпотентных запросов (intent/должность/требования/поддержка).
"""

from __future__ import annotations

import json
import ssl
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, cast

import aiohttp
import certifi

from app.config import settings
from app.core.constants import COMPANY_INFO, HORECA_POSITIONS, Intent
from app.core.logger import get_logger

log = get_logger("gemini")

_API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

# Канонические должности для enum-схемы (ключи HORECA_POSITIONS) + «unknown».
_POSITION_ENUM: list[str] = [*HORECA_POSITIONS.keys(), "unknown"]


# ─────────────────────────── структуры результатов ─────────────────────────
@dataclass(frozen=True, slots=True)
class RequirementsData:
    """Структурированные требования вакансии, извлечённые из свободного текста."""

    experience_min: int
    skills: list[str] = field(default_factory=list)
    summary: str = ""


# ─────────────────────── чистые helpers (тестируются) ──────────────────────
def extract_text(payload: dict[str, Any]) -> str | None:
    """Достаёт текст ответа из JSON-ответа generateContent. Не бросает исключений."""
    try:
        candidates = payload.get("candidates") or []
        if not candidates:
            return None
        parts = (candidates[0].get("content") or {}).get("parts") or []
        joined = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
        return joined or None
    except (AttributeError, IndexError, TypeError):
        return None


def strip_code_fences(text: str) -> str:
    """Убирает обрамление ```json … ``` — Gemini иногда добавляет его даже в JSON-режиме."""
    t = text.strip()
    if t.startswith("```"):
        t = t[3:]
        if "\n" in t:
            t = t.split("\n", 1)[1]
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def parse_json_object(text: str) -> dict[str, Any] | None:
    """Безопасно парсит JSON-объект из ответа модели."""
    try:
        data = json.loads(strip_code_fences(text))
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _intent_from_label(label: str) -> Intent:
    return {
        "seeking_job": Intent.SEEKING_JOB,
        "seeking_employee": Intent.SEEKING_EMPLOYEE,
    }.get(label, Intent.UNKNOWN)


# ──────────────────────────────── LRU-кеш ──────────────────────────────────
class _LRUCache:
    """Маленький in-memory LRU. Бот однопроцессный async — блокировки не нужны."""

    def __init__(self, maxsize: int = 512) -> None:
        self._data: OrderedDict[str, Any] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> Any | None:
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self._maxsize:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()


# ──────────────────────────────── сервис ───────────────────────────────────
class GeminiService:
    """Высокоуровневые AI-операции бота. Используется как синглтон `gemini`."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._cache = _LRUCache()

    # ── инфраструктура ──────────────────────────────────────────────────────
    @property
    def available(self) -> bool:
        return settings.ai_available

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # Явный CA-бандл из certifi: системный набор сертификатов может быть
            # неполным (типично для Python на macOS) — иначе TLS-рукопожатие
            # с googleapis.com падает на verify.
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def aclose(self) -> None:
        """Закрыть HTTP-сессию (вызывается при остановке бота)."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
        request_timeout: float | None = None,
    ) -> str | None:
        """Один запрос к generateContent. Возвращает текст ответа или None при любой ошибке."""
        if not self.available:
            return None
        effective_timeout = (
            settings.gemini_timeout if request_timeout is None else request_timeout
        )

        gen_config: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            # Отключаем «thinking» — для классификации он лишь жжёт токены и время.
            "thinkingConfig": {"thinkingBudget": 0},
        }
        if schema is not None:
            gen_config["responseMimeType"] = "application/json"
            gen_config["responseSchema"] = schema

        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        assert settings.gemini_api_key is not None  # гарантировано self.available
        url = f"{_API_ROOT}/{settings.gemini_model}:generateContent"
        headers = {"x-goog-api-key": settings.gemini_api_key.get_secret_value()}

        try:
            session = await self._ensure_session()
            async with session.post(
                url,
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=effective_timeout),
            ) as resp:
                if resp.status != 200:
                    detail = (await resp.text())[:300]
                    log.warning("gemini_http_error", status=resp.status, detail=detail)
                    return None
                payload = await resp.json()
        except (TimeoutError, aiohttp.ClientError) as exc:
            log.warning("gemini_request_failed", error=str(exc))
            return None
        except Exception as exc:
            log.error("gemini_unexpected", error=str(exc))
            return None

        return extract_text(payload)

    # ── 1. Намерение пользователя (ТЗ §1.1, §7.1) ───────────────────────────
    async def classify_intent(self, text: str) -> tuple[Intent, float] | None:
        """Классифицирует свободный текст: соискатель / работодатель / неясно.

        Возвращает (Intent, confidence) либо None, если AI недоступен/ошибся.
        """
        if not self.available or not text.strip():
            return None
        key = f"intent:{text.strip().lower()[:200]}"
        cached = self._cache.get(key)
        if cached is not None:
            return cast(tuple[Intent, float], cached)

        schema = {
            "type": "OBJECT",
            "properties": {
                "intent": {
                    "type": "STRING",
                    "enum": ["seeking_job", "seeking_employee", "unknown"],
                },
                "confidence": {"type": "NUMBER"},
            },
            "required": ["intent", "confidence"],
        }
        system = (
            "Ты — классификатор намерений для Telegram-бота подбора персонала "
            "в общепите (HoReCa). По сообщению определи, кто пишет:\n"
            "• seeking_job — человек ищет работу/подработку для себя;\n"
            "• seeking_employee — работодатель ищет сотрудника, размещает вакансию;\n"
            "• unknown — намерение не ясно.\n"
            "Отвечай строго JSON. confidence — число 0..1."
        )
        raw = await self._generate(
            f"Сообщение: «{text.strip()}»", system=system, schema=schema,
            temperature=0.0, max_tokens=128,
        )
        if raw is None:
            return None
        data = parse_json_object(raw)
        if data is None or "intent" not in data:
            return None
        intent = _intent_from_label(str(data["intent"]))
        try:
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        result = (intent, confidence)
        self._cache.put(key, result)
        return result

    # ── 2. Канонизация должности HoReCa (ТЗ §4) ─────────────────────────────
    async def normalize_position(self, raw_position: str) -> str | None:
        """Сопоставляет произвольное название должности с канонической HoReCa-формой.

        Возвращает ключ из HORECA_POSITIONS либо None (нет уверенного совпадения).
        """
        if not self.available or not raw_position.strip():
            return None
        key = f"pos:{raw_position.strip().lower()[:120]}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached or None  # пустая строка в кеше = «не распознано»

        schema = {
            "type": "OBJECT",
            "properties": {"position": {"type": "STRING", "enum": _POSITION_ENUM}},
            "required": ["position"],
        }
        system = (
            "Ты сопоставляешь должность из общепита с канонической категорией. "
            "Верни ближайшую из списка или 'unknown', если это не профессия HoReCa. "
            "Примеры: 'пиццайоло'→повар, 'человек на кухню'→кухонный работник, "
            "'девушка в зал'→официант."
        )
        result = await self._generate(
            f"Должность: «{raw_position.strip()}»", system=system, schema=schema,
            temperature=0.0, max_tokens=64,
        )
        if result is None:
            return None
        data = parse_json_object(result)
        position = str((data or {}).get("position", "unknown"))
        normalized = position if position in HORECA_POSITIONS else None
        self._cache.put(key, normalized or "")
        return normalized

    # ── 3. Структурирование требований вакансии (ТЗ §3.1) ───────────────────
    async def structure_requirements(self, raw_text: str) -> RequirementsData | None:
        """Из свободного текста требований извлекает опыт, навыки и краткую сводку."""
        if not self.available or not raw_text.strip():
            return None
        key = f"req:{raw_text.strip().lower()[:300]}"
        cached = self._cache.get(key)
        if cached is not None:
            return cast(RequirementsData, cached)

        schema = {
            "type": "OBJECT",
            "properties": {
                "experience_min": {"type": "INTEGER"},
                "skills": {"type": "ARRAY", "items": {"type": "STRING"}},
                "summary": {"type": "STRING"},
            },
            "required": ["experience_min", "skills", "summary"],
        }
        system = (
            "Ты разбираешь требования вакансии в общепите. Извлеки:\n"
            "• experience_min — минимальный опыт в годах (целое, 0 если не указан);\n"
            "• skills — список ключевых навыков/качеств (3-7 коротких пунктов);\n"
            "• summary — одно предложение-резюме требований для кандидата.\n"
            "Отвечай строго JSON на русском."
        )
        raw = await self._generate(
            f"Требования вакансии: «{raw_text.strip()}»", system=system, schema=schema,
            temperature=0.1, max_tokens=512,
        )
        if raw is None:
            return None
        data = parse_json_object(raw)
        if data is None:
            return None
        try:
            exp = int(data.get("experience_min", 0) or 0)
        except (TypeError, ValueError):
            exp = 0
        skills_raw = data.get("skills") or []
        skills = [str(s).strip() for s in skills_raw if str(s).strip()][:7]
        result = RequirementsData(
            experience_min=max(0, exp),
            skills=skills,
            summary=str(data.get("summary", "")).strip(),
        )
        self._cache.put(key, result)
        return result

    # ── 4. Объяснение совместимости для карточки (💡 усиление ТЗ) ────────────
    async def explain_match(
        self, *, viewer: str, candidate_desc: str, vacancy_desc: str
    ) -> str | None:
        """Короткая фраза «почему подходит» для свайп-карточки.

        viewer: 'candidate' (смотрит вакансию) | 'employer' (смотрит кандидата).
        """
        if not self.available:
            return None
        # Кеш по паре (кандидат, вакансия): повторный показ той же карточки или
        # обратное направление просмотра не дёргают сеть и дают стабильный текст.
        key = (
            f"explain:{viewer}:"
            f"{candidate_desc.strip().lower()[:200]}|{vacancy_desc.strip().lower()[:200]}"
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached or None

        if viewer == "candidate":
            task = "Объясни кандидату одним коротким предложением, чем эта вакансия ему подходит."
        else:
            task = "Объясни работодателю одним коротким предложением, чем этот кандидат подходит."
        system = (
            "Ты — рекрутер общепита. Дай дружелюбную подсказку строго в одно "
            "предложение (до 18 слов), без вступлений и кавычек. Только по фактам ниже."
        )
        prompt = f"{task}\n\nКандидат: {candidate_desc}\n\nВакансия: {vacancy_desc}"
        # Подсказка — необязательная: ограничиваем ожидание, чтобы медленный AI
        # не тормозил листание карточек (фолбэк — карточка без подсказки).
        raw = await self._generate(
            prompt,
            system=system,
            temperature=0.4,
            max_tokens=96,
            request_timeout=min(settings.gemini_timeout, 6.0),
        )
        if raw is None:
            return None  # транзиентный сбой не кешируем — попробуем снова позже
        hint = raw.strip().strip('"').splitlines()[0][:280]
        self._cache.put(key, hint)
        return hint or None

    # ── 5. «Причёсывание» текста «о себе» кандидата ─────────────────────────
    async def polish_about(self, raw_text: str) -> str | None:
        """Делает из черновика «о себе» аккуратный текст для работодателей."""
        if not self.available or len(raw_text.strip()) < 10:
            return None
        key = f"about:{raw_text.strip().lower()[:300]}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached or None

        system = (
            "Ты помогаешь соискателю в общепите улучшить раздел «о себе». "
            "Перепиши текст: грамотно, дружелюбно, по делу, от первого лица, "
            "2-3 предложения. Не выдумывай факты, которых нет. Без кавычек и пояснений."
        )
        raw = await self._generate(
            f"Черновик: «{raw_text.strip()}»", system=system, temperature=0.6, max_tokens=256,
        )
        polished = (raw or "").strip().strip('"')
        self._cache.put(key, polished)
        return polished or None

    # ── 6. Разбор времени собеседования из живой речи (ТЗ §5.2) ─────────────
    async def parse_interview_slots(
        self, text: str, *, now_local_iso: str
    ) -> list[str] | None:
        """Разбирает свободный текст в список слотов 'YYYY-MM-DD HH:MM' (местное время).

        Возвращает None, если AI недоступен; [] — если время не найдено.
        """
        if not self.available or not text.strip():
            return None
        schema = {
            "type": "OBJECT",
            "properties": {
                "slots": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["slots"],
        }
        system = (
            "Ты извлекаешь дату и время собеседования из текста работодателя. "
            f"Текущий момент (местное время): {now_local_iso}. "
            "Верни до 3 будущих слотов в формате 'YYYY-MM-DD HH:MM'. "
            "'завтра', 'в пятницу', 'после обеда (15:00)', 'утром (10:00)' — "
            "разрешай относительно текущего момента. Только будущее. Строго JSON."
        )
        raw = await self._generate(
            f"Текст: «{text.strip()}»", system=system, schema=schema,
            temperature=0.0, max_tokens=256,
        )
        if raw is None:
            return None
        data = parse_json_object(raw)
        if data is None:
            return []
        slots = data.get("slots") or []
        return [str(s).strip() for s in slots if str(s).strip()][:3]

    # ── 7. AI-поддержка: ответы на вопросы пользователей (ТЗ §6, §10) ───────
    async def answer_support(self, question: str, *, context: str | None = None) -> str | None:
        """Отвечает на свободный вопрос пользователя о работе бота.

        `context` — недавняя история диалога и статус пользователя; учитывается
        и в ключе кеша, иначе разным пользователям достался бы один ответ.
        """
        if not self.available or not question.strip():
            return None
        ctx_key = str(hash(context)) if context else "0"
        key = f"faq:{ctx_key}:{question.strip().lower()[:200]}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached or None

        system = (
            "Ты — поддержка и консультант Telegram-бота «Smart Chef HR». "
            "Отвечай на вопросы пользователей о работе бота, о компании, тарифах, "
            "оплате и реферальной программе — опираясь на справку ниже.\n\n"
            f"=== Справка о сервисе ===\n{COMPANY_INFO}\n=== конец справки ===\n\n"
            "Команды бота: /menu /search /profile /subscription /invite /help.\n"
            "Отвечай кратко (2-4 предложения), дружелюбно, по-русски и только по "
            "теме бота и компании. Не выдумывай фактов, которых нет в справке. "
            "Если вопрос не по теме — мягко верни человека к меню (/menu)."
        )
        prompt = question.strip()
        if context:
            prompt = f"История диалога:\n{context}\n\nТекущий вопрос:\n{prompt}"
        raw = await self._generate(prompt, system=system, temperature=0.5, max_tokens=320)
        answer = (raw or "").strip()
        self._cache.put(key, answer)
        return answer or None


# Синглтон — импортируется хендлерами и сервисами как `from app.services.gemini import gemini`.
gemini = GeminiService()
