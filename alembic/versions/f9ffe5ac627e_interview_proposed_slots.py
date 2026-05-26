"""interview proposed slots

Revision ID: f9ffe5ac627e
Revises: 3c7ac4fa70ad
Create Date: 2026-05-20 15:49:34.157040

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f9ffe5ac627e"
down_revision: str | Sequence[str] | None = "3c7ac4fa70ad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interviews",
        sa.Column("proposed_slots", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.alter_column(
        "interviews",
        "scheduled_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "interviews",
        "scheduled_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
    )
    op.drop_column("interviews", "proposed_slots")
