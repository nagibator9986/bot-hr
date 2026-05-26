# Схема базы данных

> Все модели — в [app/db/models/](../app/db/models/). Этот документ — ER-обзор и описание инвариантов.

## ER-диаграмма (упрощённая)

```
        ┌─────────┐
        │  User   │   tg_id UNIQUE
        │ (1)     │
        └────┬────┘
   ┌─────────┼──────────────────┬──────────────────┐
   │ 1:1     │ 1:1              │ 1:1              │ 1:N
   ▼         ▼                  ▼                  ▼
┌─────────┐ ┌──────────┐ ┌──────────────────┐ ┌───────────────┐
│Candidate│ │ Employer │ │ ReferralBalance  │ │ Subscription  │
└────┬────┘ └────┬─────┘ └──────────────────┘ └───────────────┘
     │            │ 1:N
     │            ▼
     │       ┌─────────┐
     │       │ Vacancy │
     │       └────┬────┘
     │ N:N        │
     └─►┌─────────▼──┐
        │   Match    │  UNIQUE(candidate_id, vacancy_id)
        └──────┬─────┘
               │ 1:1
               ▼
         ┌──────────┐
         │Interview │
         └──────────┘

┌──────────┐    ┌─────────┐    ┌──────────────────┐
│  User    │ N:1│Referral │ 1:N│ ReferralBalance  │
└──────────┘    └─────────┘    └──────────────────┘
                  UNIQUE(referrer, referee)
                  UNIQUE(referee)              ┌──────────────┐
                  CHECK referrer<>referee      │  Payment     │
                                                │ provider_id  │
                                                │ UNIQUE       │
                                                └──────────────┘
```

## Таблицы

### users

| Колонка | Тип | Особенности |
|---|---|---|
| `id` | PK | |
| `tg_id` | BIGINT | UNIQUE, INDEX |
| `tg_username` | VARCHAR(64) | nullable |
| `role` | VARCHAR(16) | `candidate`/`employer`/`admin`, nullable пока не выбрано |
| `language` | VARCHAR(8) | default `ru` |
| `is_blocked` | BOOLEAN | default false |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

### candidates (1:1 с users)

Поля анкеты из ТЗ §2.1: `name`, `age`, `city` (INDEX), `desired_position` + `position_normalized` (для матчинга, INDEX), `experience_years`, `previous_jobs`, `schedule`, `expected_salary`, `contact`.

`status` — enum (см. `CandidateStatus`): NEW/SEARCHING/OFFERED/INVITED/INTERVIEWED/HIRED/REJECTED.

### employers + vacancies

`employers` — 1:1 с users (`user_id` UNIQUE).
`vacancies` — 1:N от employer. JSONB `requirements` для гибких полей.

### matches

Связка кандидат ↔ вакансия. UNIQUE(candidate_id, vacancy_id) — один matcher не создаёт дубли.
`score` — 0..100. `decision` — enum.

### interviews

1:1 от match. `scheduled_at` — `TIMESTAMP WITH TIME ZONE`. Статус — enum, важный для idempotent-напоминаний (`reminded_24h`, `reminded_2h`).

### subscriptions

Одна активная на пользователя (partial unique index `WHERE is_active=true`).

CHECK: `expires_at > started_at`.

`candidates_viewed` — счётчик для лимита работодателя; инкремент в транзакции при первом раскрытии контакта.

### payments

Лог транзакций. **UNIQUE(provider_payment_id)** — ключевой инвариант для идемпотентности webhook'ов.

### referrals

UNIQUE(referrer_id, referee_id) — кешбек не начисляется дважды.
UNIQUE(referee_id) — один реферер на пользователя.
CHECK referrer_id != referee_id — самоприглашение запрещено.

### referral_balances + withdrawal_requests

`balance`, `total_earned`, `total_withdrawn` хранятся отдельно от логов транзакций для O(1) чтения.
`WithdrawalRequest` — заявка на вывод (Kaspi).

## Соглашения

- **Naming convention** — `app/db/base.py`. Стабильные имена constraint'ов для Alembic.
- **Timestamps** — всегда `TIMESTAMP WITH TIME ZONE`, в коде — `datetime` с UTC.
- **Деньги** — `NUMERIC(10, 0)` (₸ без копеек). `Decimal` в коде; для UI — int.
- **Enum'ы** — хранятся как `VARCHAR`, не PostgreSQL ENUM (проще миграции).
- **Удаления** — CASCADE для дочерних (Candidate, Employer); RESTRICT для платёжных (Payment, WithdrawalRequest) чтобы не потерять историю.

## Производительность

- `vacancies(city, position_normalized, status)` — частый запрос матчера. Можно добавить составной индекс при росте.
- `subscriptions(user_id) WHERE is_active=true` — partial index уже есть.
- `interviews(scheduled_at)` — INDEX для джобов напоминаний.
- Для матчера по нескольким полям сразу — рассмотреть `pg_trgm` + GIN для нечёткого совпадения должности.
