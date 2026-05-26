"""Доменные константы и enum'ы. Не зависят от ничего, кроме stdlib."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    CANDIDATE = "candidate"
    EMPLOYER = "employer"
    ADMIN = "admin"


class Intent(StrEnum):
    SEEKING_JOB = "seeking_job"
    SEEKING_EMPLOYEE = "seeking_employee"
    UNKNOWN = "unknown"


class CandidateStatus(StrEnum):
    NEW = "new"
    SEARCHING = "searching"
    OFFERED = "offered"
    INVITED = "invited"
    INTERVIEWED = "interviewed"
    HIRED = "hired"
    REJECTED = "rejected"


class VacancyStatus(StrEnum):
    ACTIVE = "active"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class MatchDecision(StrEnum):
    PENDING = "pending"
    MUTUAL = "mutual"                      # обе стороны лайкнули
    ACCEPTED_BY_CANDIDATE = "accepted_by_candidate"
    ACCEPTED_BY_EMPLOYER = "accepted_by_employer"
    REJECTED_BY_CANDIDATE = "rejected_by_candidate"
    REJECTED_BY_EMPLOYER = "rejected_by_employer"


class Reaction(StrEnum):
    """Реакция в свайп-просмотре карточек (Дайвинчик-стиль)."""

    LIKE = "like"
    SKIP = "skip"


class VerificationStatus(StrEnum):
    """Статус проверки работодателя (HR-сторона)."""

    PENDING = "pending"      # ожидает проверки
    APPROVED = "approved"    # проверен, может публиковать вакансии
    REJECTED = "rejected"    # отклонён


class InterviewStatus(StrEnum):
    PROPOSED = "proposed"          # работодатель предложил слоты, кандидат ещё не выбрал
    SCHEDULED = "scheduled"
    REMINDED_24H = "reminded_24h"
    REMINDED_2H = "reminded_2h"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class Tariff(StrEnum):
    CANDIDATE = "candidate"
    EMPLOYER_BASIC = "employer_basic"
    EMPLOYER_EXTENDED = "employer_extended"


class Schedule(StrEnum):
    SHIFT = "shift"
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    FLEXIBLE = "flexible"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentPurpose(StrEnum):
    SUBSCRIPTION = "subscription"
    RENEWAL = "renewal"


class ReferralStatus(StrEnum):
    PENDING = "pending"      # друг перешёл, ещё не оплатил
    GRANTED = "granted"      # бонус начислен
    REJECTED = "rejected"    # фрод / отказ


class WithdrawalStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    REJECTED = "rejected"


# ── Лимиты тарифов работодателя ───────────────────────────────────────────
TARIFF_LIMITS: dict[Tariff, int | None] = {
    Tariff.CANDIDATE: None,                # без лимита просмотров вакансий
    Tariff.EMPLOYER_BASIC: 20,
    Tariff.EMPLOYER_EXTENDED: 50,
}

# ── Длительность подписки ─────────────────────────────────────────────────
SUBSCRIPTION_DAYS: int = 30

# ── Окна уведомлений об окончании подписки ────────────────────────────────
SUBSCRIPTION_EXPIRY_REMINDERS_DAYS: tuple[int, ...] = (3, 0)

# ── Напоминания о собеседовании ───────────────────────────────────────────
INTERVIEW_REMINDERS_HOURS: tuple[int, ...] = (24, 2)

# ── Матчинг ───────────────────────────────────────────────────────────────
MATCH_THRESHOLD: int = 70

MATCH_WEIGHTS: dict[str, int] = {
    "city": 40,
    "position": 30,
    "experience": 15,
    "salary": 10,
    "schedule": 5,
}

# Допуск по зарплате: насколько ожидание кандидата может превышать верх вилки
# вакансии и пара всё ещё считается совместимой (0.2 = +20%). Сверх допуска —
# пара отбрасывается. Единое правило для обеих сторон просмотра.
SALARY_TOLERANCE: float = 0.20

# ── Должности HoReCa (общепит) ────────────────────────────────────────────
# value (канонич. норм. форма) → человекочитаемый ярлык для кнопок.
HORECA_POSITIONS: dict[str, str] = {
    "повар": "Повар",
    "су-шеф": "Су-шеф",
    "шеф-повар": "Шеф-повар",
    "пекарь": "Пекарь",
    "кондитер": "Кондитер",
    "бариста": "Бариста",
    "бармен": "Бармен",
    "официант": "Официант",
    "хостес": "Хостес",
    "администратор": "Администратор зала",
    "кухонный работник": "Кухонный работник",
    "посудомойщик": "Посудомойщик",
    "курьер": "Курьер",
}

# Синонимы → канонич. норм. форма (для свободного ввода и матчинга).
POSITION_SYNONYMS: dict[str, str] = {
    "шеф": "шеф-повар",
    "chef": "шеф-повар",
    "су шеф": "су-шеф",
    "sous-chef": "су-шеф",
    "cook": "повар",
    "повар-универсал": "повар",
    "повар универсал": "повар",
    "повар горячего цеха": "повар",
    "повар холодного цеха": "повар",
    "помощник повара": "кухонный работник",
    "помощник на кухню": "кухонный работник",
    "кухработник": "кухонный работник",
    "barista": "бариста",
    "официантка": "официант",
    "бариста-кассир": "бариста",
    "пиццамейкер": "повар",
    "пиццайоло": "повар",
    "сушист": "повар",
    "кассир": "администратор",
    "уборщик": "кухонный работник",
    "посудница": "посудомойщик",
    "мойщик посуды": "посудомойщик",
}
