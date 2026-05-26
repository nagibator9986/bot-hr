# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Almaty

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        tini \
        tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── deps layer (кешируется) ─────────────────────────────────────────────────
# Трюк: пустой stub пакета даёт setuptools.find собрать `app`, а pip — поставить
# зависимости из pyproject.toml. Реальный код приедет следующим COPY и подхватится
# editable install'ом.
COPY pyproject.toml README.md ./
RUN mkdir -p app && touch app/__init__.py && \
    pip install --upgrade pip && \
    pip install -e .

# ── code layer ──────────────────────────────────────────────────────────────
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# Non-root
RUN useradd -m -u 1000 smartchef && chown -R smartchef:smartchef /app
USER smartchef

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app"]
