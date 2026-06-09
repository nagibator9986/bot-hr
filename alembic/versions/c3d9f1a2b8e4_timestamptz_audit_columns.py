"""created_at/updated_at → TIMESTAMP WITH TIME ZONE

Служебные временные метки из TimestampMixin создавались как TIMESTAMP WITHOUT
TIME ZONE, тогда как доменные поля времени (expires_at, scheduled_at, ...) —
timezone-aware. Выравниваем: всё хранится в UTC как timestamptz (CLAUDE.md §10.6).

Конвертация data-driven (по information_schema), чтобы покрыть все таблицы
TimestampMixin без хардкода списка. Наивные значения трактуются как UTC.

Revision ID: c3d9f1a2b8e4
Revises: b2e4c7a91d30
Create Date: 2026-06-09 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d9f1a2b8e4"
down_revision: str | Sequence[str] | None = "b2e4c7a91d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _audit_columns(target_data_type: str) -> list[tuple[str, str]]:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND column_name IN ('created_at', 'updated_at')
              AND data_type = :dt
            ORDER BY table_name, column_name
            """
        ),
        {"dt": target_data_type},
    )
    return [(row[0], row[1]) for row in rows]


def upgrade() -> None:
    for table_name, column_name in _audit_columns("timestamp without time zone"):
        op.execute(
            sa.text(
                f'ALTER TABLE "{table_name}" '
                f'ALTER COLUMN "{column_name}" '
                f"TYPE TIMESTAMP WITH TIME ZONE "
                f"USING \"{column_name}\" AT TIME ZONE 'UTC'"
            )
        )


def downgrade() -> None:
    for table_name, column_name in _audit_columns("timestamp with time zone"):
        op.execute(
            sa.text(
                f'ALTER TABLE "{table_name}" '
                f'ALTER COLUMN "{column_name}" '
                f"TYPE TIMESTAMP WITHOUT TIME ZONE "
                f"USING \"{column_name}\" AT TIME ZONE 'UTC'"
            )
        )
