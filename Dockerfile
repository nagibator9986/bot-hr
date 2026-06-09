# syntax=docker/dockerfile:1.7

# ── Builder: компилируем зависимости (нужны build-essential/libpq-dev) ───────
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# deps-слой (кешируется): пустой stub пакета даёт setuptools.find собрать `app`,
# а pip ставит зависимости из pyproject. Реальный код приедет следующим COPY.
COPY pyproject.toml README.md ./
RUN mkdir -p app && touch app/__init__.py \
    && pip install --upgrade pip \
    && pip install .

# Реальный код: переустанавливаем только сам проект (без зависимостей — быстро).
COPY app ./app
RUN pip install --no-deps --force-reinstall .

# ── Runtime: только рантайм-библиотеки, без компиляторов ──────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Almaty \
    PATH="/opt/venv/bin:$PATH"

# libpq5 — рантайм-библиотека для asyncpg/psycopg2 (вместо тяжёлого libpq-dev).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        tini \
        tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Готовый venv с зависимостями и установленным пакетом `app`.
COPY --from=builder /opt/venv /opt/venv
# Миграции прогоняются как pre-deploy шаг (alembic на PATH из venv).
COPY alembic ./alembic
COPY alembic.ini ./

RUN useradd -m -u 1000 smartchef && chown -R smartchef:smartchef /app
USER smartchef

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app"]
