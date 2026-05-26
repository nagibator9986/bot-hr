"""candidate area and conversation history

Revision ID: a1f8c9d4e5b7
Revises: f9ffe5ac627e
Create Date: 2026-05-21 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1f8c9d4e5b7"
down_revision: str | Sequence[str] | None = "f9ffe5ac627e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("candidates", sa.Column("preferred_area", sa.String(length=128), nullable=True))
    op.alter_column("candidates", "resume_file_id", existing_type=sa.String(length=256), nullable=True)

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=True),
        sa.Column("message_type", sa.String(length=24), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("callback_data", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_conversation_messages_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_messages")),
    )
    op.create_index(
        op.f("ix_conversation_messages_direction"),
        "conversation_messages",
        ["direction"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_messages_message_type"),
        "conversation_messages",
        ["message_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_messages_user_id"),
        "conversation_messages",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_conversation_messages_user_created",
        "conversation_messages",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_messages_user_created", table_name="conversation_messages")
    op.drop_index(op.f("ix_conversation_messages_user_id"), table_name="conversation_messages")
    op.drop_index(op.f("ix_conversation_messages_message_type"), table_name="conversation_messages")
    op.drop_index(op.f("ix_conversation_messages_direction"), table_name="conversation_messages")
    op.drop_table("conversation_messages")

    op.alter_column("candidates", "resume_file_id", existing_type=sa.String(length=256), nullable=False)
    op.drop_column("candidates", "preferred_area")
