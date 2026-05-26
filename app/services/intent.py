"""Распознавание намерения пользователя из свободного текста (ТЗ §1.1, §7.1).

Двухуровневая схема:
  • `detect_intent` — rule-based на леммах + словарь ключевых слов. Быстрый,
    бесплатный, покрывает ~85 % коротких сообщений («ищу работу», «нужен повар»).
  • `resolve_intent` — async-обёртка: если правила не уверены, подключает Gemini
    (см. services/gemini.py). Закрывает живую речь («надоело без дела сидеть»).

Хендлеры зовут `resolve_intent`; `detect_intent` остаётся чистой синхронной
функцией — её удобно юнит-тестировать без сети.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.constants import Intent
from app.services.gemini import gemini
from app.utils.text import lemma, normalize, tokenize

# Сырые слова — лемматизируются при импорте, чтобы сравнение шло на нормальных формах.
_SEEKER_RAW: frozenset[str] = frozenset({
    "работа", "вакансия", "трудоустройство", "найти", "искать", "устроиться",
    "соискатель", "резюме", "подработка", "смена",
})

_EMPLOYER_RAW: frozenset[str] = frozenset({
    # Профессии (упоминание = работодатель ищет)
    "сотрудник", "работник", "повар", "помощник", "официант", "бариста",
    "кондитер", "посудомойщик",
    # Действия найма — однозначно работодатель
    "нанять", "требуется", "требоваться", "разместить", "наём",
    # «нужен/нужна» НЕ включён — амбивалентно («нужна работа» vs «нужен повар»)
})


def _lemmatize_set(words: frozenset[str]) -> frozenset[str]:
    """Объединение сырых и лемматизированных форм — устойчиво к причудам морфологии
    (pymorphy3 даёт «барист» для несклоняемого «бариста» и т.п.).
    """
    out: set[str] = set(words)
    for w in words:
        out.add(lemma(w))
    return frozenset(out)


_SEEKER_KEYWORDS: frozenset[str] = _lemmatize_set(_SEEKER_RAW)
_EMPLOYER_KEYWORDS: frozenset[str] = _lemmatize_set(_EMPLOYER_RAW)

# Контекстные модификаторы (склоняют чашу весов).
_SEEKER_PHRASES: frozenset[str] = frozenset({
    "ищу работу", "ищу подработку", "хочу работать", "нужна работа",
    "есть вакансии", "хочу устроиться",
})

_EMPLOYER_PHRASES: frozenset[str] = frozenset({
    "нужен сотрудник", "ищу сотрудника", "ищу повара", "хочу разместить",
    "нанять", "разместить вакансию", "ищем работника", "требуется",
})


@dataclass(frozen=True, slots=True)
class IntentResult:
    intent: Intent
    confidence: float  # 0..1


def detect_intent(text: str) -> IntentResult:
    """Грубое определение намерения. Не падает на пустых строках."""
    if not text or not text.strip():
        return IntentResult(Intent.UNKNOWN, 0.0)

    low = text.lower().strip()
    seeker_score = 0
    employer_score = 0

    # 1. Точные фразы (вес 3)
    for phrase in _SEEKER_PHRASES:
        if phrase in low:
            seeker_score += 3
    for phrase in _EMPLOYER_PHRASES:
        if phrase in low:
            employer_score += 3

    # 2. Леммы + сырые токены (страховка от багов лемматизации)
    raw_tokens = set(tokenize(low))
    all_forms = raw_tokens | {lemma(t) for t in raw_tokens}
    seeker_score += len(all_forms & _SEEKER_KEYWORDS)
    employer_score += len(all_forms & _EMPLOYER_KEYWORDS)

    # 3. Эвристика «требуется X» — однозначно работодатель.
    #    «нужен/нужна» НЕ используем — амбивалентно («нужна работа»/«нужен повар»).
    norm = normalize(low)
    if "требоваться" in norm and (all_forms & _EMPLOYER_KEYWORDS):
        employer_score += 2

    total = seeker_score + employer_score
    if total == 0:
        return IntentResult(Intent.UNKNOWN, 0.0)

    if seeker_score > employer_score:
        return IntentResult(Intent.SEEKING_JOB, seeker_score / total)
    if employer_score > seeker_score:
        return IntentResult(Intent.SEEKING_EMPLOYEE, employer_score / total)

    return IntentResult(Intent.UNKNOWN, 0.5)


# Уверенность rule-based, ниже которой подключаем AI (UNKNOWN или спорный счёт).
_RULE_CONFIDENCE_FLOOR = 0.6


async def resolve_intent(text: str) -> IntentResult:
    """Намерение с AI-подстраховкой.

    Правила сработали уверенно → отдаём их (быстро, без обращения к сети).
    Иначе спрашиваем Gemini; если и он не уверен — возвращаем rule-based результат.
    """
    rule = detect_intent(text)
    if rule.intent is not Intent.UNKNOWN and rule.confidence >= _RULE_CONFIDENCE_FLOOR:
        return rule

    ai = await gemini.classify_intent(text)
    if ai is not None:
        intent, confidence = ai
        if intent is not Intent.UNKNOWN:
            return IntentResult(intent, confidence)

    return rule
