"""vacancy salary range

Revision ID: 3c7ac4fa70ad
Revises: d668dd65083a
Create Date: 2026-05-20 15:06:12.486194

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c7ac4fa70ad"
down_revision: str | Sequence[str] | None = "d668dd65083a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vacancies",
        sa.Column("salary_min", sa.Numeric(precision=10, scale=0), nullable=False),
    )
    op.add_column(
        "vacancies",
        sa.Column("salary_max", sa.Numeric(precision=10, scale=0), nullable=False),
    )
    op.drop_column("vacancies", "salary")
    op.create_check_constraint(
        "salary_range_ordered", "vacancies", "salary_max >= salary_min"
    )


def downgrade() -> None:
    op.drop_constraint("salary_range_ordered", "vacancies", type_="check")
    op.add_column(
        "vacancies",
        sa.Column("salary", sa.Numeric(precision=10, scale=0), nullable=False),
    )
    op.drop_column("vacancies", "salary_max")
    op.drop_column("vacancies", "salary_min")
