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

Проект готовится как worker service: HTTP-порт и healthcheck не нужны, бот запускается polling-ом через Dockerfile.

1. Создайте на Railway PostgreSQL и Redis services.
2. В переменных bot service задайте `BOT_TOKEN`, `BOT_USERNAME`, `ADMIN_IDS`, `REDIS_URL`, `ENVIRONMENT=prod`, `LOG_LEVEL=INFO`.
3. Для базы можно использовать стандартный `DATABASE_URL` Railway; приложение само преобразует его в `postgresql+asyncpg://` для async SQLAlchemy.
4. Для Google Sheets на Railway используйте `GOOGLE_SA_JSON` или `GOOGLE_SA_JSON_B64`; локальный `GOOGLE_SA_JSON_PATH` оставлен для Docker Compose.
5. `railway.json` включает Dockerfile build, `alembic upgrade head` как pre-deploy command и restart policy `ON_FAILURE`.

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
