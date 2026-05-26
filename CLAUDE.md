# Smart Chef HR — Claude Code Instructions

> **Project**: Telegram-бот для автоматического подбора персонала в сфере общественного питания (повара, кухонный персонал, HoReCa).
> **Domain**: HR-Tech, кадровое агентство в Telegram, B2B/B2C SaaS-подписка.
> **Source of truth**: [ТЗ.md](./TZ.md) — техническое задание заказчика, перенесённое из PDF.

Этот файл — **рабочая инструкция для Claude Code**. Он описывает архитектуру, инварианты, конвенции и подводные камни проекта. Читай его перед любой нетривиальной задачей.

---

## 1. Что строим (TL;DR)

Бот в Telegram, который:
1. **Определяет намерение** пользователя из свободного текста (соискатель vs работодатель).
2. **Собирает анкету** — пошаговый FSM-диалог (имя, город, должность, опыт, зарплата, график, контакт).
3. **Матчит** кандидатов и вакансии по 5 критериям: город, должность, опыт, зарплата, график.
4. **Назначает собеседования** — согласует время между обеими сторонами без участия человека.
5. **Шлёт напоминания** — за 24 ч и за 2 ч до собеседования.
6. **Монетизируется**: подписки (1 000 ₸ для кандидата, 10 000 / 20 000 ₸ для работодателя), реферальная программа (300 ₸ за приведённого друга, вывод на Kaspi).
7. **Отчитывается**: всё дублируется в Google Sheets (4 листа — Applicants, Employers, Vacancies, Interviews) как админ-панель «из коробки».

**Принципиальное требование**: весь процесс — **без участия человека**. Бот сам ведёт диалог, сам подбирает, сам назначает встречи.

---

## 2. Технологический стек

| Слой | Технология | Версия | Зачем именно это |
|---|---|---|---|
| Язык | Python | 3.11+ | `asyncio`, structural pattern matching, `tomllib` |
| Bot framework | **aiogram** | 3.13+ | Современный async API, FSM из коробки, Router-архитектура |
| База данных | **PostgreSQL** | 16 | JSONB для гибких полей анкеты, `tsvector` для FTS, надёжные транзакции |
| ORM | SQLAlchemy | 2.0 (async) | Декларативные модели, async-engine, миграции через Alembic |
| Миграции | Alembic | 1.13+ | Версионирование схемы |
| FSM storage | Redis | 7 | Быстрый доступ, TTL, переживает рестарт бота |
| Кеш / rate-limit | Redis | 7 | Тот же инстанс |
| Конфиг | pydantic-settings | 2.x | Type-safe `.env`, валидация на старте |
| Логирование | structlog | 24.x | Структурные JSON-логи, контекст-биндинг |
| Планировщик | APScheduler | 3.10+ | Напоминания 24 ч / 2 ч, продление подписок |
| Google Sheets | gspread + google-auth | latest | Service Account, batch-обновления |
| HTTP-клиент | aiohttp | 3.10+ | Идёт из aiogram; на нём же REST к Gemini |
| AI / LLM | **Google Gemini API** | gemini-2.5-flash | NLP-слой (§6.6): intent, должности, требования, подсказки. Опционален |
| Тесты | pytest + pytest-asyncio | latest | Unit + integration; БД через testcontainers |
| Линт / формат | ruff + mypy | latest | Один тул вместо black+isort+flake8 |
| Контейнер | Docker + docker-compose | — | Один `docker compose up` для всего |

**Не используем без явной причины**: SQLite (нет JSONB и concurrent writes), Django ORM, sync-aiogram 2.x, telebot, pyTelegramBotAPI.

---

## 3. Структура репозитория

```
telegrambotchelus/
├── CLAUDE.md                       # этот файл
├── TZ.md                           # ТЗ заказчика (cleaned-up из PDF)
├── README.md                       # инструкция запуска для людей
├── pyproject.toml                  # deps + ruff + mypy + pytest конфиг
├── .env.example                    # шаблон переменных окружения
├── .gitignore
├── docker-compose.yml              # postgres + redis + bot + (опц.) adminer
├── Dockerfile
├── Makefile                        # make run / migrate / lint / test
├── alembic.ini
├── alembic/
│   ├── env.py                      # async-friendly env
│   └── versions/                   # миграции
├── docs/
│   ├── ARCHITECTURE.md             # схема компонентов, потоки данных
│   ├── DATABASE.md                 # ER-диаграмма, описание таблиц
│   └── SHEETS.md                   # маппинг таблиц БД → листов Google
├── app/
│   ├── __main__.py                 # точка входа: python -m app
│   ├── bot.py                      # сборка Bot, Dispatcher, регистрация роутеров
│   ├── config.py                   # Settings (pydantic-settings)
│   ├── core/
│   │   ├── logger.py               # настройка structlog
│   │   ├── exceptions.py           # доменные исключения
│   │   └── constants.py            # enum'ы: Intent, Status, Tariff, Schedule
│   ├── db/
│   │   ├── base.py                 # DeclarativeBase + naming convention
│   │   ├── session.py              # engine + async_sessionmaker
│   │   └── models/                 # SQLAlchemy модели (по одной на файл)
│   │       ├── user.py             # общий User (Telegram ID, роль, баланс)
│   │       ├── candidate.py        # анкета соискателя
│   │       ├── employer.py         # компания-работодатель
│   │       ├── vacancy.py          # вакансия
│   │       ├── match.py            # связь candidate↔vacancy + статус
│   │       ├── interview.py        # запись на собеседование
│   │       ├── subscription.py     # подписка/тариф/срок
│   │       ├── payment.py          # платежи (лог)
│   │       └── referral.py         # реф. связи + баланс + выводы
│   ├── repositories/               # data-access слой; вся работа с БД здесь
│   ├── services/                   # бизнес-логика (без I/O Telegram-а)
│   │   ├── intent.py               # классификация намерения (правила → Gemini)
│   │   ├── gemini.py               # клиент Google Gemini API (AI-слой)
│   │   ├── enrichment.py           # AI-обёртки: должность, требования, слоты
│   │   ├── matching.py             # алгоритм подбора
│   │   ├── scheduler.py            # APScheduler jobs
│   │   ├── notifications.py        # отправка сообщений по событиям
│   │   ├── payments.py             # генерация ссылок/QR, проверка статуса
│   │   ├── referrals.py            # генерация ссылок, начисление, выплаты
│   │   ├── access_control.py       # проверка лимитов и подписок
│   │   └── google_sheets.py        # синхронизация с Google Sheets
│   ├── handlers/                   # aiogram Routers (тонкие — только I/O)
│   │   ├── common.py               # /start, intent recognition
│   │   ├── candidate.py            # сценарий соискателя
│   │   ├── employer.py             # сценарий работодателя
│   │   ├── interview.py            # запись/отказ/подтверждение
│   │   ├── subscription.py         # оплата, статус подписки
│   │   ├── referral.py             # «Пригласить друга», вывод
│   │   └── admin.py                # команды админа
│   ├── keyboards/                  # фабрики клавиатур (inline / reply)
│   ├── states/                     # aiogram FSM States (StatesGroup)
│   ├── middlewares/                # DI БД, throttling, проверка доступа
│   ├── utils/                      # validators, formatters, normalize_text
│   └── locales/ru.py               # все строки UI (одно место для перевода)
└── tests/
    ├── conftest.py
    ├── unit/
    └── integration/
```

**Правило**: один модуль — одна ответственность. Если в `handlers/candidate.py` появляется SQL — это баг, выноси в repository.

---

## 4. Архитектурные правила (READ THIS FIRST)

### 4.1 Слои и направление зависимостей

```
handlers  →  services  →  repositories  →  db.models
   ↑           ↑                ↑
keyboards   external APIs    (только SQLAlchemy)
   ↑       (sheets, kaspi)
locales
```

- **handlers** — тонкие. Только: парс сообщения → вызов сервиса → ответ пользователю. **Никакого SQL и бизнес-логики.**
- **services** — толстые. Знают про доменные правила: что такое «матч», когда начислять кешбек, как считать лимит.
- **repositories** — чистая работа с БД, возвращают модели/DTO. Не знают про Telegram.
- **models** — SQLAlchemy ORM. Не содержат бизнес-логики, только структуру и простые constraint'ы.

Если хендлер импортирует `sqlalchemy` — это запах. Если репозиторий импортирует `aiogram` — это баг.

### 4.2 База — единственный источник правды

Google Sheets — **вторичная** проекция БД для админа. БД не должна зависеть от Sheets. Если синхронизация с Sheets падает — это не должно ломать сценарий пользователя. Все sheets-вызовы оборачиваем в `try/except` с логированием.

### 4.3 Async везде

Бот, БД, HTTP, Sheets — всё async. Никаких `time.sleep`, `requests.get`, `psycopg2`. Если что-то синхронное (gspread) — оборачивай в `asyncio.to_thread(...)`.

### 4.4 Транзакции — на уровне сервиса

Сервис открывает сессию (через middleware/DI), вызывает несколько репозиториев, в конце коммитит. Хендлер транзакциями не управляет.

### 4.5 FSM — Redis

Любой многошаговый диалог = `StatesGroup` + RedisStorage. Не храним состояние в памяти — бот должен переживать рестарт без потери прогресса заполнения анкеты.

### 4.6 Идемпотентность платежей и кешбека

- Платёж = уникальный `payment_id` от провайдера. Двойная нотификация не должна продлевать подписку дважды.
- Кешбек начисляется один раз на пару `(referrer_id, referee_id)`. Уникальный constraint на эту пару в БД.

---

## 5. Доменная модель (БД)

> Полная схема в [docs/DATABASE.md](./docs/DATABASE.md). Здесь — самое важное для понимания.

### Сущности

- **User** — любой Telegram-пользователь. Поля: `tg_id` (unique), `role` (`candidate | employer | admin`), `language`, `created_at`. Роль определяется при первом интенте.
- **Candidate** — анкета соискателя (1:1 с User, если роль = candidate). Поля: `name`, `age`, `city`, `desired_position`, `experience_years`, `previous_jobs`, `schedule`, `expected_salary`, `contact`, `status` (enum).
- **Employer** — компания (1:1 с User). Поля: `company_name`, `city`, `contact_person`, `phone`.
- **Vacancy** — вакансия (N:1 к Employer). Поля: `position`, `city`, `salary`, `schedule`, `requirements` (JSONB: `{experience_min, skills[]}`), `address`, `status` (`active | in_progress | closed`).
- **Match** — кандидат ↔ вакансия. Создаётся matcher-ом. Поля: `score`, `decision` (`pending | accepted | rejected_by_candidate | rejected_by_employer`), таймстампы.
- **Interview** — назначенное собеседование (1:1 от Match). Поля: `scheduled_at`, `address`, `status` (`scheduled | reminded_24h | reminded_2h | completed | cancelled`).
- **Subscription** — активная подписка пользователя. Поля: `user_id`, `tariff` (`candidate | employer_basic | employer_extended`), `started_at`, `expires_at`, `is_active`, `candidates_viewed` (для лимита работодателя).
- **Payment** — лог транзакций. `provider_payment_id` UNIQUE, `amount`, `currency=KZT`, `status`, `purpose` (`subscription | renewal`).
- **Referral** — связь `referrer_id → referee_id` (UNIQUE), `bonus_amount`, `granted_at` (NULL до оплаты friend'ом), `status`.
- **ReferralBalance** — `user_id`, `balance` (текущий), `total_earned`, `total_withdrawn`.
- **WithdrawalRequest** — заявка на вывод: `user_id`, `amount`, `kaspi_phone`, `status` (`pending | paid | rejected`), таймстампы.

### Enum'ы → `app/core/constants.py`

```python
class Role(StrEnum):
    CANDIDATE = "candidate"
    EMPLOYER = "employer"
    ADMIN = "admin"

class CandidateStatus(StrEnum):
    NEW = "new"
    SEARCHING = "searching"
    OFFERED = "offered"          # предложена вакансия
    INVITED = "invited"          # приглашён на собес
    INTERVIEWED = "interviewed"
    HIRED = "hired"
    REJECTED = "rejected"

class VacancyStatus(StrEnum):
    ACTIVE = "active"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"

class Tariff(StrEnum):
    CANDIDATE = "candidate"                # 1 000 ₸
    EMPLOYER_BASIC = "employer_basic"      # 10 000 ₸, лимит 20
    EMPLOYER_EXTENDED = "employer_extended"  # 20 000 ₸, лимит 50

class Schedule(StrEnum):
    SHIFT = "shift"        # сменный
    FULL_TIME = "full_time"  # полный день
    PART_TIME = "part_time"
    FLEXIBLE = "flexible"
```

### Инварианты БД (constraint'ы / триггеры)

1. `User.tg_id` UNIQUE.
2. `Referral(referrer_id, referee_id)` UNIQUE — кешбек начисляется один раз.
3. `Referral.referrer_id != Referral.referee_id` — самоприглашение запрещено (CHECK).
4. `Payment.provider_payment_id` UNIQUE — защита от двойной обработки вебхука.
5. `Subscription.expires_at > started_at` (CHECK).
6. Один активный `Subscription` на `(user_id, tariff)` — partial unique index `WHERE is_active=true`.

---

## 6. Ключевые алгоритмы

### 6.1 Intent Recognition — `services/intent.py`

Двухуровневая схема (см. также §6.6 — AI-слой):

1. **Rule-based** (`detect_intent`, синхронная, чистая) — lowercase + lemmatize
   (pymorphy3) + словари ключевых слов. Чей score выше — тот интент. ~85 % на
   коротких фразах, ноль обращений к сети.
2. **AI-fallback** (`resolve_intent`, async) — если правила вернули `UNKNOWN`
   или низкую уверенность (< 0.6), запрос уходит в Gemini. Закрывает живую речь
   («надоело без дела сидеть», «возьмём пару рук на кухню»).

Хендлеры зовут `resolve_intent`. `detect_intent` остаётся чистой — её удобно
юнит-тестировать без сети. Если AI выключен — `resolve_intent` == `detect_intent`.

### 6.2 Matching — `services/matching.py`

Вакансия активна → находим всех «свободных» кандидатов в той же роли. Скор:

```
score = 0
if candidate.city == vacancy.city:                              score += 40
if candidate.desired_position similar_to vacancy.position:      score += 30
if candidate.experience_years >= vacancy.experience_min:        score += 15
if candidate.expected_salary <= vacancy.salary:                 score += 10
if schedules_overlap(candidate.schedule, vacancy.schedule):     score += 5
```

Минимальный порог match'а: **70**. Кандидаты сортируются по score DESC. Город и должность — обязательные критерии (если не совпали — отбрасываем).

Похожесть должности — нормализованное сравнение + словарь синонимов (`повар = chef = шеф-повар`).

### 6.3 Interview scheduling — `services/scheduler.py`

Шаги:
1. Кандидат жмёт «✅ Да» → создаётся `Match.decision = accepted_by_candidate`.
2. Бот пишет работодателю: «Найден кандидат… Назначить?».
3. Работодатель отправляет 1–3 слота времени (текстом или через date-picker inline).
4. Бот предлагает слоты кандидату → кандидат выбирает.
5. Создаётся `Interview(scheduled_at, address, status=scheduled)`.
6. APScheduler ставит два job'а: `remind(interview_id, "24h")` и `remind(..., "2h")`.

Все job'ы — **idempotent**: если статус уже `reminded_24h`, повторный запуск ничего не делает.

### 6.4 Доступ и лимиты — `services/access_control.py`

Декоратор/middleware `@require_subscription(role=...)`:
- если подписки нет → preview-режим (см. п. 10.2 ТЗ): скрываем адрес/компанию/контакты.
- если работодатель открыл `subscription.candidates_viewed >= limit` → блок + предложение апгрейда.
- если `expires_at < now()` → деактивируем подписку, шлём «продлите».

### 6.5 Referral — `services/referrals.py`

- Ссылка вида `https://t.me/<bot_username>?start=ref_<user_id>`.
- При `/start ref_<X>` создаём `Referral(referrer=X, referee=current_user)` со статусом `pending`.
- После оплаты referee срабатывает hook → `referrer.balance += 300`, `referral.status = granted`.
- Защита от накрутки: один `tg_id` = один referee, проверка по `phone_hash` (если собрали номер), rate-limit на регистрации с одного IP/устройства.
- Вывод: только при `balance >= 1000`. Заявка падает в `WithdrawalRequest` (status=pending) — админ обрабатывает вручную (MVP), Kaspi API — позже.

### 6.6 AI-слой — `services/gemini.py` + `services/enrichment.py`

Генеративный AI (Google Gemini) подключён как **необязательный усиливающий
слой**. Транспорт — REST поверх `aiohttp` (без тяжёлых SDK).

**Железное правило — graceful degradation.** Нет `GEMINI_API_KEY` / запрос упал /
выключено флагом `GEMINI_ENABLED` — каждый AI-метод возвращает `None`, вызывающий
код откатывается на rule-based логику. AI *улучшает* бота, но **никогда** не
является единственной точкой отказа. Тесты обязаны покрывать оба пути.

Где подключён AI (7 точек):

| Точка | Метод | Фолбэк без AI |
|---|---|---|
| Намерение из свободного текста | `classify_intent` | rule-based `detect_intent` |
| Канонизация должности HoReCa | `normalize_position` | словарь `POSITION_SYNONYMS` |
| Требования вакансии → навыки | `structure_requirements` | regex по опыту |
| «Почему подходит» на карточке | `explain_match` | подсказка не показывается |
| «Причёсывание» текста «о себе» | `polish_about` | сохраняется текст как есть |
| Время собеседования из речи | `parse_interview_slots` | строгий формат `ДД.ММ ЧЧ:ММ` |
| Ответы на вопросы (поддержка) | `answer_support` | стандартное «не понял команду» |

Конвенции AI-слоя:
- `gemini` — синглтон; `enrichment.py` оборачивает «правила → AI» для хендлеров.
- Идемпотентные запросы (intent/должность/требования/поддержка) кешируются LRU.
- «Thinking» у модели отключён (`thinkingBudget: 0`) — для классификации это
  лишние токены и латентность.
- Жёсткий таймаут (`GEMINI_TIMEOUT`); любое исключение логируется и гасится.
- AI-сервис не знает про aiogram и БД: на входе текст, на выходе — структура.

---

## 7. Конфигурация (.env)

Все секреты — только в `.env`, в коде — `Settings` из `app/config.py`:

```python
class Settings(BaseSettings):
    bot_token: SecretStr
    db_url: PostgresDsn
    redis_url: RedisDsn
    google_sa_json_path: Path | None = None
    google_sheet_id: str | None = None
    payment_provider: Literal["telegram", "kaspi", "manual"] = "manual"
    admin_ids: list[int] = []
    gemini_api_key: SecretStr | None = None   # пусто → AI-слой выключен
    gemini_model: str = "gemini-2.5-flash"
    gemini_enabled: bool = True
    log_level: str = "INFO"
    environment: Literal["dev", "stage", "prod"] = "dev"
    model_config = SettingsConfigDict(env_file=".env", extra="forbid")
```

`settings.ai_available` — единый предикат «можно ли звать AI» (включён И есть ключ).

**Никогда не коммить `.env`**. В репо только `.env.example`.

---

## 8. Команды разработки (Makefile)

```bash
make run              # python -m app
make migrate          # alembic upgrade head
make migration m="..." # alembic revision --autogenerate
make lint             # ruff check + mypy
make format           # ruff format
make test             # pytest
make up               # docker compose up -d
make down             # docker compose down
make logs             # docker compose logs -f bot
make psql             # psql внутрь контейнера БД
```

---

## 9. Что делать / чего не делать

### ✅ Делать

- Любую работу с БД — через репозитории.
- Все строки UI — в `locales/ru.py` (готовим почву для kk/en).
- Inline-клавиатуры с `callback_data` — через `aiogram.filters.callback_data.CallbackData` (type-safe).
- Логировать каждый внешний вызов (Telegram API, Sheets, Kaspi) с `correlation_id`.
- Писать pytest-тесты на `services/matching.py`, `services/access_control.py`, `services/referrals.py` — это критичная бизнес-логика.
- При изменении схемы БД — **сразу** делать миграцию через Alembic, не править `alembic/versions/*` руками.

### ❌ Не делать

- Не использовать `print` — только `logger`.
- Не хардкодить тарифы / лимиты / суммы кешбека в коде — выносить в БД или в `core/constants.py`.
- Не делать sync HTTP-запросы в хендлерах.
- Не дёргать Telegram API из сервисов напрямую — сервис должен возвращать данные/событие, хендлер форматирует и шлёт.
- Не использовать `SELECT *` в репозиториях — явно перечислять колонки или загружать модели целиком.
- Не верить вебхукам платежей без проверки подписи провайдера.
- Не показывать контакт кандидата / адрес вакансии без активной подписки — это нарушение п. 10.11 ТЗ («нельзя получить контакты без оплаты»).
- Не блокировать event-loop. Если используешь gspread (sync) — через `asyncio.to_thread`.

---

## 10. Известные подводные камни

1. **Google Sheets rate limit**: 100 запросов / 100 сек / user. Используем batch-обновления (`spreadsheet.values_batch_update`), а не построчно. Если поток событий высокий — буферизуем и шлём пачками раз в N сек.
2. **APScheduler + рестарт**: используем `SQLAlchemyJobStore`, чтобы job'ы напоминаний переживали рестарт.
3. **WhatsApp Bot из п. 7.2 ТЗ**: в MVP делаем **только Telegram**. WhatsApp — отдельная фаза (нужен Business API, верификация номера, отдельный провайдер). Архитектура должна позволять подключить второй транспорт — поэтому сервисы не знают про aiogram конкретно, общаются через события.
4. **Платежи**: в MVP — `payment_provider = "manual"` (админ подтверждает). Telegram Payments — следующий шаг. Kaspi Pay — отдельная интеграция (нужен договор).
5. **AI-слой (Gemini)**: rule-based intent даёт ~85% на коротких сообщениях — это быстрый и бесплатный путь по умолчанию. Gemini подключён как **fallback** на живую речь и сложные случаи (§6.6), но всегда опционален: нет ключа — бот работает на правилах. Не делать AI единственной точкой отказа; не звать AI там, где справляются правила (это $$$ и латентность).
6. **Часовые пояса**: всё храним в `TIMESTAMP WITH TIME ZONE` в UTC. На вывод — конвертируем в `Asia/Almaty` (+05:00).
7. **Лимиты работодателя**: «открыто 20 из 20» считаем по `candidates_viewed` — инкрементируем **в транзакции** при первом раскрытии контакта (не при просмотре превью).
8. **Реф-фрод**: не доверяй только `tg_id` — он бесплатный. Доп. проверки: один номер телефона = один аккаунт, тротлинг регистраций, ручной апрув вывода (MVP).

---

## 11. Roadmap (по фазам)

| Фаза | Содержание | Готово когда |
|---|---|---|
| **0. Скелет** | Структура, конфиг, БД, Alembic, Docker, CI lint | `make up` поднимает всё, `make migrate` отрабатывает |
| **1. Core flow** | Intent → анкета кандидата → вакансия работодателя → матчинг → собес | Сквозной сценарий проходит в Telegram |
| **2. Reminders** | APScheduler, напоминания 24/2 ч, статусы | Job'ы пишутся в БД, переживают рестарт |
| **3. Sheets** | 4 листа, синхронизация, фильтры для админа | Каждое действие отражается в Sheets в течение 5 сек |
| **4. Payments** | Подписки, preview-режим, лимиты | Контакт открывается только после оплаты |
| **5. Referrals** | Реф-ссылки, кешбек, заявка на вывод | 300 ₸ начисляется после оплаты friend'ом |
| **6. Hardening** | Метрики, алерты, нагрузочное, защита от фрода | 99% аптайм, < 500 мс p95 latency хендлеров |
| **7. WhatsApp** | Второй транспорт через WhatsApp Business API | Те же сценарии работают в WA |

---

## 12. Контакт со мной (Claude)

- При нетривиальном изменении схемы БД — **сначала** покажи план миграции, потом пиши код.
- При добавлении нового handler'а — сначала добавь FSM-состояния и сервис, потом тонкий handler.
- Если ТЗ противоречит сам себе — отметь конфликт в ответе и предложи решение, не угадывай молча.
- Перед коммитом большого изменения — прогони `make lint && make test`.
- Все user-facing строки — на **русском** (язык пользователей и заказчика).

> Если в задаче не хватает информации — спроси, а не выдумывай. Это финансовый продукт (платежи, выплаты) — цена ошибки высокая.
