.DEFAULT_GOAL := help
.PHONY: help install run up down logs migrate migration downgrade lint format test psql shell clean

PYTHON ?= python
COMPOSE ?= docker compose
SERVICE ?= bot

help:  ## Показать список команд
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:  ## Установить deps локально (без Docker)
	$(PYTHON) -m pip install -e ".[dev]"

run:  ## Запустить бота локально
	$(PYTHON) -m app

up:  ## docker compose up -d
	$(COMPOSE) up -d

down:  ## docker compose down
	$(COMPOSE) down

restart:  ## Рестарт бота в контейнере
	$(COMPOSE) restart $(SERVICE)

logs:  ## Логи бота
	$(COMPOSE) logs -f $(SERVICE)

ps:  ## Статус контейнеров
	$(COMPOSE) ps

migrate:  ## Применить миграции
	alembic upgrade head

migration:  ## Создать новую миграцию: make migration m="add foo"
	@if [ -z "$(m)" ]; then echo "Usage: make migration m=\"message\""; exit 1; fi
	alembic revision --autogenerate -m "$(m)"

downgrade:  ## Откатить последнюю миграцию
	alembic downgrade -1

lint:  ## ruff check + mypy
	ruff check app tests alembic
	mypy app

format:  ## ruff format
	ruff format app tests alembic
	ruff check --fix app tests alembic

test:  ## Запустить тесты
	pytest

test-cov:  ## Тесты с coverage
	pytest --cov=app --cov-report=term-missing

psql:  ## Открыть psql в контейнере БД
	$(COMPOSE) exec postgres psql -U smartchef -d smartchef

shell:  ## Python-шелл в контейнере бота
	$(COMPOSE) exec $(SERVICE) python

clean:  ## Удалить cache и build артефакты
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .mypy_cache .ruff_cache .pytest_cache .coverage htmlcov dist build *.egg-info
