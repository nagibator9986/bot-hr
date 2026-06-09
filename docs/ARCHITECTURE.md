# Архитектура Smart Chef HR

## Высокоуровневая диаграмма

```
                 ┌──────────────┐
                 │  Telegram    │
                 │  пользователь│
                 └──────┬───────┘
                        │
                        ▼
              ┌──────────────────┐
              │  aiogram 3       │
              │  (long polling)  │
              └──────┬───────────┘
                     │
   ┌─────────────────┼───────────────────────┐
   │ Middlewares (DI: Session, User, Throttle)│
   └─────────────────┼───────────────────────┘
                     │
              ┌──────▼──────┐
              │  Handlers   │ ← FSM states (Redis)
              │  (thin UI)  │
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │  Services   │ ← бизнес-логика
              │             │
              └──┬──┬──┬──┬─┘
                 │  │  │  └────────────────┐
                 │  │  └─────┐             │
                 │  └──┐     │             │
                 ▼     ▼     ▼             ▼
         Repositories APScheduler  Google Sheets
                 │            (jobs)   (mirror)
                 ▼
           ┌──────────┐
           │PostgreSQL│
           └──────────┘
```

## Компоненты

### 1. aiogram Dispatcher

Запускается в `app/__main__.py`. Использует `RedisStorage` для FSM, `SQLAlchemyJobStore` для APScheduler. Polling, не webhooks (MVP).

### 2. Middlewares (order matters)

1. **DbSessionMiddleware** (outer) — открывает `AsyncSession`, кладёт в `data['session']`, коммитит при успехе/откатывает при исключении.
2. **UserMiddleware** (outer) — `get_or_create` User по `tg_id`, кладёт в `data['user']`.
3. **ThrottleMiddleware** (per-update) — 10 апдейтов / 5 сек на пользователя.

### 3. Routers

Каждый Router — отдельный домен:

- `common` — `/start`, intent recognition.
- `candidate` — FSM анкеты соискателя (9 шагов).
- `employer` — FSM создания вакансии (10 шагов).
- `interview` — приём «Да/Нет», согласование слотов.
- `subscription` — `/pay`, выбор тарифа, статус.
- `referral` — реф-ссылка, баланс, заявка на вывод.
- `admin` — `/grant`, `/payouts`, `/paid`.

### 4. Services (бизнес-логика)

| Сервис | Ответственность |
|---|---|
| `intent.py` | Распознавание намерения (rule-based + леммы, AI-фолбэк). |
| `gemini.py` | Клиент Google Gemini (7 AI-точек, graceful degradation, LRU-кеш). |
| `enrichment.py` | Обёртки «правила → AI»: должность, требования, слоты для хендлеров. |
| `matching.py` | Скоринг пары (кандидат, вакансия), поиск кандидатов / вакансий. |
| `browse.py` | Свайп-движок: следующая карточка, реакция, взаимный матч. |
| `profile.py` | Рендер карточек/анкет, маскировка данных в preview-режиме. |
| `access_control.py` | Проверка активной подписки и лимита просмотров. |
| `payments.py` | Идемпотентная активация подписки по `provider_payment_id`. |
| `promo.py` | Активация подписки по промокоду (бесплатно, без реф-бонуса). |
| `referrals.py` | Привязка реферера/промоутера, начисление после оплаты, вывод. |
| `verification.py` | Модерация работодателя (pending → approve/reject). |
| `scheduler.py` | APScheduler job'ы: напоминания 24/2 ч, истечение подписки. |
| `notifications.py` | Рассылка по событиям + авто-уведомление о новых матчах. |
| `conversation.py` | Лог входящих/исходящих сообщений (история для админа и AI-контекст). |
| `roles.py` | Определение/переключение роли пользователя. |
| `google_sheets.py` | Async-фасад над gspread, зеркало БД; не ломает сценарий при сбое. |

### 5. Repositories

Чистый data-access на SQLAlchemy 2.0 async. Один класс на агрегат: `UserRepo`, `CandidateRepo`, `EmployerRepo`, `VacancyRepo`, `MatchRepo`, `InterviewRepo`, `SubscriptionRepo`, `PaymentRepo`, `PaymentClaimRepo`, `ReferralRepo`, `BalanceRepo`, `WithdrawalRepo`, `PromoterRepo`, `PromoCodeRepo`, `ConversationRepo`.

Денежные счётчики/балансы обновляются атомарным `UPDATE ... SET x = x + n`
(а не read-modify-write) — защита от потерянных обновлений при гонке.

### 6. Хранилища

- **PostgreSQL 16** — основное хранилище. `asyncpg` для приложения, `psycopg` для APScheduler.
- **Redis 7** — FSM-storage + кеш + throttle (если уйдём из памяти процесса).
- **Google Sheets** — вторичная проекция для админа. Никогда не блокирует основной сценарий.

## Потоки данных

> **Подбор реализован свайпами (Дайвинчик-стиль), а не push-уведомлениями.**
> Кандидат листает вакансии, работодатель — кандидатов; контакты открываются
> при взаимном лайке. Push-уведомление `announce_new_*` лишь сообщает
> противоположной стороне «появился новый вариант, загляните в листание».

### Поток 1: Соискатель → свайп → взаимный матч

```
/start → role=candidate → FSM CandidateForm (анкета + фото)
                          ↓ commit
                       Candidate row
                          ↓
        BrowseService.next_for_candidate (matching + дедуп показанных)
                          ↓
     карточка вакансии (❤️/👎, AI-подсказка «почему подходит»)
                          ↓
        ❤️ → MatchRepo.react → если обе стороны лайкнули → decision = MUTUAL
```

### Поток 2: Взаимный матч → собеседование

```
MUTUAL → обе стороны получают контакты (при активной подписке; иначе preview)
       ↓
работодатель: «📅 Предложить время» → 1-3 слота (строгий формат ДД.ММ ЧЧ:ММ или речь→AI)
       ↓
слоты уходят кандидату кнопками → кандидат выбирает слот
       ↓
Interview(scheduled_at, status=scheduled) + APScheduler 2 job'а (24 ч / 2 ч)
       ↓
обе стороны уведомлены; строка-зеркало в Google Sheets (лист Interviews)
```

### Поток 3: Платёж → активация

```
/pay → tariff_keyboard → PaymentCB
                            ↓
                PaymentService.create_payment_link
                            ↓
                       (provider)
                            ↓
                 webhook / admin /grant
                            ↓
       PaymentService.confirm_payment (idempotent by provider_payment_id)
                            ↓
              Subscription(is_active=True, expires_at=+30d)
                            ↓
              ReferralService.grant_on_payment(referee_id)
                            ↓
              (если был referrer) +300 ₸ на balance
```

## Инварианты

1. **Один источник правды — PostgreSQL.** Google Sheets — read-mostly mirror.
2. **Идемпотентность платежей** — UNIQUE(provider_payment_id).
3. **Идемпотентность реферралов** — UNIQUE(referrer_id, referee_id) + UNIQUE(referee_id).
4. **CHECK no_self_referral** — на уровне БД.
5. **Транзакционность бизнес-операций** — на уровне сервиса; middleware коммитит на выходе.
6. **Async-only I/O** — никаких блокирующих вызовов в event-loop.

## Что в скоупе MVP, а что — после

| Фаза | Скоуп |
|---|---|
| MVP (фазы 0-3 в CLAUDE.md) | Все 9 шагов анкеты, матчинг, собес, напоминания, Google Sheets. |
| Phase 4 | Платный доступ + preview-режим. |
| Phase 5 | Реферальная программа. |
| Phase 6 | Метрики, алерты, нагрузочное. |
| Phase 7 | WhatsApp Business API как второй транспорт. |
