"""Доменные исключения. Все ошибки уровня бизнес-логики наследуют от SmartChefError."""

from __future__ import annotations


class SmartChefError(Exception):
    """Базовое исключение приложения."""

    code: str = "smartchef_error"
    user_message: str = "Произошла ошибка. Попробуйте позже."

    def __init__(self, message: str | None = None, *, user_message: str | None = None) -> None:
        super().__init__(message or self.code)
        if user_message:
            self.user_message = user_message


# ── Подписки и доступ ────────────────────────────────────────────────────
class SubscriptionRequiredError(SmartChefError):
    code = "subscription_required"
    user_message = "Для доступа к этой информации требуется активная подписка."


class SubscriptionExpiredError(SmartChefError):
    code = "subscription_expired"
    user_message = "Срок действия подписки истёк. Продлите доступ."


class CandidateLimitReachedError(SmartChefError):
    code = "candidate_limit_reached"
    user_message = "Лимит просмотров кандидатов исчерпан. Обновите тариф."


# ── Платежи ───────────────────────────────────────────────────────────────
class PaymentError(SmartChefError):
    code = "payment_error"
    user_message = "Не удалось обработать оплату. Свяжитесь с поддержкой."


class DuplicatePaymentError(PaymentError):
    code = "duplicate_payment"


# ── Реферальная система ───────────────────────────────────────────────────
class ReferralError(SmartChefError):
    code = "referral_error"


class SelfReferralError(ReferralError):
    code = "self_referral"
    user_message = "Нельзя пригласить самого себя 🙂"


class AlreadyReferredError(ReferralError):
    code = "already_referred"
    user_message = "Вы уже зарегистрированы по другой реферальной ссылке."


class InsufficientBalanceError(ReferralError):
    code = "insufficient_balance"
    user_message = "На балансе недостаточно средств для вывода."


# ── Промокоды ─────────────────────────────────────────────────────────────
class PromoError(SmartChefError):
    code = "promo_error"


class PromoInvalidError(PromoError):
    code = "promo_invalid"
    user_message = "Промокод не найден, истёк или больше не действует."


class PromoAlreadyUsedError(PromoError):
    code = "promo_already_used"
    user_message = "Вы уже активировали этот промокод."


# ── Матчинг и собеседования ───────────────────────────────────────────────
class NoMatchesFoundError(SmartChefError):
    code = "no_matches"
    user_message = "Пока подходящих вариантов нет. Мы сообщим, как только появятся."


class InterviewConflictError(SmartChefError):
    code = "interview_conflict"
    user_message = "Это время уже занято. Выберите другое."
