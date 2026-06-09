"""promoters/promo_codes.code → единый уникальный индекс

В b2e4 код-колонки были созданы как UNIQUE constraint (uq_*_code) + отдельный
НЕуникальный индекс (ix_*_code). Модель же объявляет `unique=True, index=True`,
что SQLAlchemy выражает одним УНИКАЛЬНЫМ индексом ix_*_code (без uq-констрейнта).
Приводим БД к модели — иначе autogenerate/`alembic check` видят дрейф.

Revision ID: d4e0a1b2c3f5
Revises: c3d9f1a2b8e4
Create Date: 2026-06-09 00:05:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d4e0a1b2c3f5"
down_revision: str | Sequence[str] | None = "c3d9f1a2b8e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("promoters", "promo_codes"):
        op.drop_constraint(f"uq_{table}_code", table, type_="unique")
        op.drop_index(f"ix_{table}_code", table_name=table)
        op.create_index(f"ix_{table}_code", table, ["code"], unique=True)


def downgrade() -> None:
    for table in ("promoters", "promo_codes"):
        op.drop_index(f"ix_{table}_code", table_name=table)
        op.create_index(f"ix_{table}_code", table, ["code"], unique=False)
        op.create_unique_constraint(f"uq_{table}_code", table, ["code"])
