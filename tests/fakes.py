"""Лёгкие фейки репозиториев/сессии для unit-тестов сервисов без БД.

Postgres-специфику (ON CONFLICT, partial unique, JSONB) на уровне сервиса не
тестируем — её обеспечивают миграции. Здесь проверяем бизнес-ветвления:
идемпотентность, лимиты, разовое начисление бонуса, отказы.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from app.core.exceptions import InsufficientBalanceError
from app.utils.time import utcnow


class FakeSession:
    """Минимальная async-сессия: сервисам нужны только flush/commit/refresh."""

    def __init__(self) -> None:
        self.flushed = 0
        self.committed = 0

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1

    async def refresh(self, obj: Any, attrs: Any = None) -> None:
        return None


# ─────────────────────────────── Платежи ───────────────────────────────────
class FakePaymentRepo:
    """Имитирует UNIQUE(provider_payment_id) через множество уже виденных id."""

    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.records: list[SimpleNamespace] = []
        self._id = 0

    async def record(
        self,
        *,
        user_id: int,
        provider: str,
        provider_payment_id: str,
        amount: int,
        tariff: Any,
        status: Any = None,
        raw_payload: str | None = None,
    ) -> SimpleNamespace | None:
        if provider_payment_id in self.seen:
            return None  # ON CONFLICT DO NOTHING
        self.seen.add(provider_payment_id)
        self._id += 1
        payment = SimpleNamespace(
            id=self._id,
            user_id=user_id,
            provider=provider,
            provider_payment_id=provider_payment_id,
            amount=amount,
            tariff=tariff,
            subscription_id=None,
        )
        self.records.append(payment)
        return payment


class FakeSubscriptionRepo:
    def __init__(self, active: SimpleNamespace | None = None) -> None:
        self._active = active
        self.created: list[SimpleNamespace] = []
        self.deactivated: list[SimpleNamespace] = []
        self.incremented = 0
        self._id = 0

    async def get_active(self, user_id: int) -> SimpleNamespace | None:
        return self._active

    async def create(
        self, *, user_id: int, tariff: Any, started_at: Any, expires_at: Any
    ) -> SimpleNamespace:
        self._id += 1
        sub = SimpleNamespace(
            id=self._id,
            user_id=user_id,
            tariff=tariff,
            started_at=started_at,
            expires_at=expires_at,
            is_active=True,
            candidates_viewed=0,
            reminders_sent=0,
        )
        self.created.append(sub)
        self._active = sub
        return sub

    async def deactivate(self, sub: SimpleNamespace) -> None:
        sub.is_active = False
        self.deactivated.append(sub)

    async def increment_viewed(self, sub: SimpleNamespace) -> None:
        sub.candidates_viewed += 1
        self.incremented += 1


def make_subscription(
    *,
    tariff: str = "candidate",
    expires_in_days: int = 30,
    candidates_viewed: int = 0,
    is_active: bool = True,
) -> SimpleNamespace:
    now = utcnow()
    return SimpleNamespace(
        id=1,
        user_id=1,
        tariff=tariff,
        started_at=now,
        expires_at=now + timedelta(days=expires_in_days),
        is_active=is_active,
        candidates_viewed=candidates_viewed,
        reminders_sent=0,
    )


# ─────────────────────────────── Рефералы ──────────────────────────────────
def make_referral(
    *,
    referee_id: int,
    bonus_amount: int,
    referrer_id: int | None = None,
    promoter_id: int | None = None,
    status: str = "pending",
) -> SimpleNamespace:
    return SimpleNamespace(
        referrer_id=referrer_id,
        promoter_id=promoter_id,
        referee_id=referee_id,
        bonus_amount=bonus_amount,
        status=status,
        granted_at=None,
    )


def make_promoter(*, promoter_id: int = 1, user_id: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=promoter_id, user_id=user_id, total_earned=0, bonus_amount=1000)


class FakeReferralRepo:
    def __init__(self, pending: SimpleNamespace | None = None) -> None:
        self._pending = pending
        self.granted: list[SimpleNamespace] = []

    async def get_pending_for_referee(self, referee_id: int) -> SimpleNamespace | None:
        return self._pending

    async def mark_granted(self, ref: SimpleNamespace) -> None:
        ref.status = "granted"
        self.granted.append(ref)
        self._pending = None  # после начисления больше не pending (идемпотентность)


class FakeBalanceRepo:
    def __init__(self, balance: int = 0) -> None:
        self.balance_obj = SimpleNamespace(
            balance=balance, total_earned=0, total_withdrawn=0
        )
        self.credits: list[tuple[int, int]] = []
        self.debits: list[tuple[int, int]] = []

    async def get_or_create(self, user_id: int) -> SimpleNamespace:
        return self.balance_obj

    async def credit(self, user_id: int, amount: int) -> SimpleNamespace:
        self.balance_obj.balance += amount
        self.balance_obj.total_earned += amount
        self.credits.append((user_id, amount))
        return self.balance_obj

    async def debit(self, user_id: int, amount: int) -> SimpleNamespace:
        if self.balance_obj.balance < amount:  # имитируем атомарный гард в БД
            raise InsufficientBalanceError()
        self.balance_obj.balance -= amount
        self.balance_obj.total_withdrawn += amount
        self.debits.append((user_id, amount))
        return self.balance_obj


class FakePromoterRepo:
    def __init__(self, promoter: SimpleNamespace | None = None) -> None:
        self._promoter = promoter
        self.earned: list[tuple[SimpleNamespace, int]] = []

    async def get(self, promoter_id: int) -> SimpleNamespace | None:
        return self._promoter

    async def add_earned(self, promoter: SimpleNamespace, amount: int) -> None:
        promoter.total_earned += amount
        self.earned.append((promoter, amount))


class FakeWithdrawalRepo:
    def __init__(self) -> None:
        self.created: list[SimpleNamespace] = []

    async def create(
        self, *, user_id: int, amount: int, kaspi_phone: str
    ) -> SimpleNamespace:
        req = SimpleNamespace(
            user_id=user_id, amount=amount, kaspi_phone=kaspi_phone, status="pending"
        )
        self.created.append(req)
        return req


# ─────────────────────────────── Промокоды ─────────────────────────────────
def make_promo_code(
    *,
    code: str = "ABC123",
    tariff: str = "candidate",
    duration_days: int = 30,
    max_uses: int | None = None,
    used_count: int = 0,
    is_active: bool = True,
    expires_at: Any = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        code=code,
        tariff=tariff,
        duration_days=duration_days,
        max_uses=max_uses,
        used_count=used_count,
        is_active=is_active,
        expires_at=expires_at,
    )


class FakePromoCodeRepo:
    def __init__(self, promo: SimpleNamespace | None = None, increment_ok: bool = True) -> None:
        self._promo = promo
        self._increment_ok = increment_ok
        self.incremented = 0

    async def get_by_code(self, code: str) -> SimpleNamespace | None:
        return self._promo

    async def increment_used(self, promo: SimpleNamespace) -> bool:
        self.incremented += 1
        return self._increment_ok
