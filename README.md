# Smart Chef HR 🍳

Telegram-бот для автоматического подбора персонала в сфере общественного питания. Соискатели и работодатели общаются с ботом, бот сам собирает анкеты, матчит, назначает собеседования и шлёт напоминания — **без участия человека**.

Подробное ТЗ — [TZ.md](./TZ.md). Архитектура и правила разработки — [CLAUDE.md](./CLAUDE.md).

## Возможности

- 🧠 Автоматическое распознавание намерения (соискатель / работодатель).
- 🤖 **AI-слой (Google Gemini)** — понимает живую речь, канонизирует должности,
  структурирует требования вакансии, объясняет «почему подходит» на карточках,
  улучшает текст «о себе», разбирает время собеседования из речи, отвечает на
  вопросы пользователей. Полностью опционален — без ключа бот работает на правилах.
- 📝 Пошаговый сбор анкет через FSM.
- 🎯 Матчинг кандидатов и вакансий по 5 критериям (город, должность, опыт, зарплата, график).
- 📅 Согласование времени собеседования.
- 🔔 Напоминания за 24 ч и за 2 ч.
- 💳 Платные подписки (1 000 ₸ / 10 000 ₸ / 20 000 ₸) с preview-режимом до оплаты.
- 🎁 Реферальная программа с кешбеком 300 ₸ и выводом на Kaspi.
- 📊 Зеркалирование всех данных в Google Sheets — админ-панель из коробки.

## Стек

Python 3.11 · aiogram 3 · PostgreSQL 16 · SQLAlchemy 2 (async) · Alembic · Redis · APScheduler · Google Sheets API · **Google Gemini API** · structlog · Docker.

## Быстрый старт

```bash
# 1. Клонировать и заполнить env
cp .env.example .env
# отредактировать BOT_TOKEN, ADMIN_IDS
# (опционально) GEMINI_API_KEY — ключ из https://aistudio.google.com/apikey
#   включает AI-функции; пусто → бот работает на rule-based логике

# 2. Поднять окружение
make up                # docker compose up -d

# 3. Накатить миграции
make migrate           # alembic upgrade head

# 4. Запустить бота
make run               # python -m app
# или
docker compose logs -f bot
```

## Структура

```
app/
├── handlers/      # aiogram Routers — тонкий слой UI
├── services/      # бизнес-логика (matching, intent, gemini, payments, referrals)
├── repositories/  # доступ к БД
├── db/            # SQLAlchemy модели + сессия
├── states/        # FSM-состояния
├── keyboards/     # фабрики inline/reply клавиатур
├── middlewares/   # DI БД, throttling, проверка подписки
└── locales/       # все строки UI (ru)
```

## Разработка

```bash
make lint       # ruff + mypy
make format     # ruff format
make test       # pytest
make migration m="add referrals table"  # новая миграция
make psql       # консоль PostgreSQL
```

## Railway

Бот деплоится как **worker-сервис** (long-polling, без HTTP-порта и healthcheck). Сборка через `Dockerfile`, миграции прогоняются как pre-deploy command.

### 1. Создайте проект и плагины

В Railway dashboard:

1. **New Project → Deploy from GitHub repo** → выберите этот репозиторий (ветка `main`).
2. В проект добавьте плагины:
   - **PostgreSQL** (`+ New → Database → PostgreSQL`) — даст `DATABASE_URL`.
   - **Redis** (`+ New → Database → Redis`) — даст `REDIS_URL`.

### 2. Привяжите переменные плагинов к сервису бота

Откройте сервис бота → **Variables** → **Add Reference**:

- `DATABASE_URL` → `${{Postgres.DATABASE_URL}}`
- `REDIS_URL` → `${{Redis.REDIS_URL}}`

Приложение само нормализует `postgres://…` в `postgresql+asyncpg://…` для async SQLAlchemy (`app/config.py:async_db_url`), а APScheduler получит sync-вариант через `sync_db_url`.

### 3. Задайте остальные env vars

Обязательные:

| Переменная | Значение |
|---|---|
| `BOT_TOKEN` | токен от [@BotFather](https://t.me/BotFather) |
| `BOT_USERNAME` | юзернейм бота без `@` |
| `ADMIN_IDS` | `[123,456]` — список Telegram ID админов |
| `ENVIRONMENT` | `prod` |
| `LOG_LEVEL` | `INFO` |
| `TIMEZONE` | `Asia/Almaty` |

Опциональные (включают доп. функции):

| Переменная | Зачем |
|---|---|
| `GEMINI_API_KEY` | включает AI-слой ([ai.google.dev](https://aistudio.google.com/apikey)); без ключа бот работает на правилах |
| `GEMINI_MODEL` | по умолчанию `gemini-2.5-flash` |
| `GOOGLE_SA_JSON` | весь JSON service-account одной строкой → зеркалирование в Google Sheets |
| `GOOGLE_SA_JSON_B64` | альтернатива: base64 от JSON (удобнее для multiline-значений) |
| `GOOGLE_SHEET_ID` | ID таблицы; без него Sheets-синк отключён |
| `PAYMENT_PROVIDER` | `manual` / `telegram` / `kaspi` (по умолчанию `manual`) |

> ⚠️ Не задавайте `DB_URL` и `GOOGLE_SA_JSON_PATH` на Railway — они нужны только для локального Docker Compose. Если они выставлены пустыми строками, приложение их корректно игнорирует.

### 4. Запуск

`railway.json` уже настроен:

- **Build**: `Dockerfile` (multi-stage, non-root user, `tini` как PID 1).
- **Pre-deploy**: `alembic upgrade head` — миграции прогоняются перед каждым деплоем.
- **Start**: `python -m app` — long-polling bot.
- **Restart**: `ON_FAILURE` (до 10 попыток), `drainingSeconds: 15` — даёт боту корректно закрыть Redis/Postgres/Bot-сессию по SIGTERM.

Откройте **Deployments** — после первого пуша Railway сам соберёт образ, прогонит миграции и запустит бота. В логах должно появиться:

```
{"event": "starting", "env": "prod", "bot": "<your_bot>", "ai_enabled": <true/false>, ...}
{"event": "scheduler started"}
```

### 5. Проверка

- Напишите `/start` боту в Telegram.
- В Railway logs смотрите structured-логи (`structlog` JSON).
- Для `psql` к Postgres: Railway → Postgres plugin → **Connect → psql** (или через локальный `railway connect`).

## Тестовый режим

- Подписка сейчас поддерживает simulation-flow: пользователь выбирает тариф и может активировать его тестово прямо из бота кнопкой `🧪 Активировать тестово`.
- Работодатель больше не обязан вводить БИН при регистрации.
- Соискатель заполняет район/адрес поиска работы; резюме не требуется.
- Один Telegram-аккаунт может иметь обе роли: соискатель и работодатель. Переключение — через кнопку `🔄 Сменить роль`.

### Полезные админ-команды

- `/admin` — список всех админ-команд
- `/pending` — работодатели на модерации
- `/candidates_active` — активные соискатели
- `/vacancies_active` — активные вакансии
- `/vacancies_closed` — закрытые вакансии
- `/applications` — отклики и взаимные интересы
- `/subscribers` — активные подписки и недавние оплаты
- `/history <tg_id> [limit]` — история диалога пользователя
- `/logic` — где менять бизнес-логику в коде

## Документация

- [TZ.md](./TZ.md) — техническое задание заказчика.
- [CLAUDE.md](./CLAUDE.md) — правила архитектуры и работы AI-агента.
- [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) — компоненты и потоки данных.
- [docs/DATABASE.md](./docs/DATABASE.md) — схема БД, инварианты.
- [docs/SHEETS.md](./docs/SHEETS.md) — маппинг таблиц в Google Sheets.

## Лицензия

Proprietary. © 2026 Smart Chef HR.
