"""employer verification fields

Revision ID: d668dd65083a
Revises: fb692d732cb0
Create Date: 2026-05-20 14:22:39.036892

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d668dd65083a"
down_revision: str | Sequence[str] | None = "fb692d732cb0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# apscheduler_jobs управляется самим APScheduler — autogenerate её игнорируем.


def upgrade() -> None:
    op.add_column("employers", sa.Column("bin", sa.String(length=12), nullable=True))
    op.add_column(
        "employers",
        sa.Column(
            "phone_verified", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.add_column(
        "employers",
        sa.Column(
            "verification_status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "employers", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "employers", sa.Column("verification_note", sa.String(length=256), nullable=True)
    )
    op.create_index(op.f("ix_employers_bin"), "employers", ["bin"], unique=False)
    op.create_index(
        op.f("ix_employers_verification_status"),
        "employers",
        ["verification_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_employers_verification_status"), table_name="employers")
    op.drop_index(op.f("ix_employers_bin"), table_name="employers")
    op.drop_column("employers", "verification_note")
    op.drop_column("employers", "verified_at")
    op.drop_column("employers", "verification_status")
    op.drop_column("employers", "phone_verified")
    op.drop_column("employers", "bin")
