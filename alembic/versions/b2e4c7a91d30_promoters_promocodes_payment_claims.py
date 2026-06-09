"""promoters, promo codes, payment claims + promoter referrals

Revision ID: b2e4c7a91d30
Revises: a1f8c9d4e5b7
Create Date: 2026-06-07 10:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2e4c7a91d30"
down_revision: str | Sequence[str] | None = "a1f8c9d4e5b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── promoters ─────────────────────────────────────────────────────────
    op.create_table(
        "promoters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("bonus_amount", sa.Numeric(precision=10, scale=0), nullable=False),
        sa.Column(
            "total_earned",
            sa.Numeric(precision=10, scale=0),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_promoters_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promoters")),
        sa.UniqueConstraint("code", name=op.f("uq_promoters_code")),
    )
    op.create_index(op.f("ix_promoters_code"), "promoters", ["code"], unique=False)
    op.create_index(op.f("ix_promoters_user_id"), "promoters", ["user_id"], unique=False)

    # ── promo_codes ───────────────────────────────────────────────────────
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("tariff", sa.String(length=32), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("used_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promo_codes")),
        sa.UniqueConstraint("code", name=op.f("uq_promo_codes_code")),
    )
    op.create_index(op.f("ix_promo_codes_code"), "promo_codes", ["code"], unique=False)

    # ── payment_claims ────────────────────────────────────────────────────
    op.create_table(
        "payment_claims",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tariff", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=0), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_payment_claims_user_id_users"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"], ["users.id"],
            name=op.f("fk_payment_claims_admin_id_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_claims")),
    )
    op.create_index(op.f("ix_payment_claims_user_id"), "payment_claims", ["user_id"], unique=False)
    op.create_index(op.f("ix_payment_claims_status"), "payment_claims", ["status"], unique=False)

    # ── referrals: источником может быть промоутер ────────────────────────
    op.add_column("referrals", sa.Column("promoter_id", sa.Integer(), nullable=True))
    op.alter_column("referrals", "referrer_id", existing_type=sa.Integer(), nullable=True)
    op.create_index(op.f("ix_referrals_promoter_id"), "referrals", ["promoter_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_referrals_promoter_id_promoters"),
        "referrals",
        "promoters",
        ["promoter_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        op.f("ck_referrals_exactly_one_source"),
        "referrals",
        "(referrer_id IS NOT NULL) <> (promoter_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_referrals_exactly_one_source"), "referrals", type_="check"
    )
    op.drop_constraint(
        op.f("fk_referrals_promoter_id_promoters"), "referrals", type_="foreignkey"
    )
    op.drop_index(op.f("ix_referrals_promoter_id"), table_name="referrals")
    op.alter_column("referrals", "referrer_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("referrals", "promoter_id")

    op.drop_index(op.f("ix_payment_claims_status"), table_name="payment_claims")
    op.drop_index(op.f("ix_payment_claims_user_id"), table_name="payment_claims")
    op.drop_table("payment_claims")

    op.drop_index(op.f("ix_promo_codes_code"), table_name="promo_codes")
    op.drop_table("promo_codes")

    op.drop_index(op.f("ix_promoters_user_id"), table_name="promoters")
    op.drop_index(op.f("ix_promoters_code"), table_name="promoters")
    op.drop_table("promoters")
