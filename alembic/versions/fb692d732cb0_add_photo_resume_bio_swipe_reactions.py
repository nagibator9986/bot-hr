"""add photo resume bio swipe reactions

Revision ID: fb692d732cb0
Revises: 70b822db1c9c
Create Date: 2026-05-20 10:55:59.081728

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fb692d732cb0"
down_revision: str | Sequence[str] | None = "70b822db1c9c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Примечание: таблица apscheduler_jobs создаётся самим APScheduler'ом и не
# управляется этими миграциями — autogenerate её игнорируем.


def upgrade() -> None:
    op.add_column(
        "candidates", sa.Column("photo_file_id", sa.String(length=256), nullable=False)
    )
    op.add_column(
        "candidates", sa.Column("resume_file_id", sa.String(length=256), nullable=False)
    )
    op.add_column(
        "candidates", sa.Column("resume_file_name", sa.String(length=256), nullable=True)
    )
    op.add_column("candidates", sa.Column("about", sa.Text(), nullable=True))

    op.add_column(
        "matches", sa.Column("candidate_reaction", sa.String(length=8), nullable=True)
    )
    op.add_column(
        "matches", sa.Column("employer_reaction", sa.String(length=8), nullable=True)
    )
    op.add_column(
        "matches", sa.Column("candidate_seen_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "matches", sa.Column("employer_seen_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        op.f("ix_matches_candidate_reaction"), "matches", ["candidate_reaction"], unique=False
    )
    op.create_index(
        op.f("ix_matches_employer_reaction"), "matches", ["employer_reaction"], unique=False
    )

    op.add_column(
        "vacancies", sa.Column("photo_file_id", sa.String(length=256), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("vacancies", "photo_file_id")
    op.drop_index(op.f("ix_matches_employer_reaction"), table_name="matches")
    op.drop_index(op.f("ix_matches_candidate_reaction"), table_name="matches")
    op.drop_column("matches", "employer_seen_at")
    op.drop_column("matches", "candidate_seen_at")
    op.drop_column("matches", "employer_reaction")
    op.drop_column("matches", "candidate_reaction")
    op.drop_column("candidates", "about")
    op.drop_column("candidates", "resume_file_name")
    op.drop_column("candidates", "resume_file_id")
    op.drop_column("candidates", "photo_file_id")
